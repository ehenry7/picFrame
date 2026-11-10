"""Flag downloads are mocked; rendering is exercised without slideshow startup."""

import ast
import os
import queue
import shutil
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import requests
from PIL import Image

from utils.country_flags import CountryFlagCache


ROOT = Path(__file__).resolve().parents[1]


def png(size=(128, 96), color=(200, 80, 40, 255)):
    with BytesIO() as output:
        Image.new("RGBA", size, color).save(output, format="PNG")
        return output.getvalue()


class CountryFlagCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / "tests" / f".country_flags_{uuid.uuid4().hex}"
        self.addCleanup(lambda: shutil.rmtree(self.directory, ignore_errors=True))
        self.http = self.enterContext(patch("utils.country_flags.requests.get"))
        self.response = Mock(content=png())
        self.http.return_value = self.response
        self.cache = self.make_cache()

    def make_cache(self, **kwargs):
        cache = CountryFlagCache(self.directory, **kwargs)
        self.addCleanup(cache.close)
        return cache

    def drain(self, cache=None):
        (cache or self.cache)._queue.join()

    def test_miss_downloads_on_worker_and_memory_hits_do_not_repeat(self):
        caller = threading.get_ident()
        worker_threads = []

        def download(*args, **kwargs):
            worker_threads.append(threading.get_ident())
            return self.response

        self.http.side_effect = download
        self.assertIsNone(self.cache.get("FR"))
        self.drain()
        image = self.cache.get("fr")
        self.assertEqual(image.size, (128, 96))
        self.assertEqual(image.mode, "RGBA")
        self.assertIs(self.cache.get("fr"), image)
        self.http.assert_called_once_with("https://flagcdn.com/128x96/fr.png", timeout=(3, 5))
        self.assertNotEqual(worker_threads, [caller])
        self.assertTrue((self.directory / "fr_128x96.png").is_file())
        self.response.close.assert_called_once()

    def test_slow_download_does_not_block_lookup_or_duplicate_work(self):
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def download(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Download was not released")
            return self.response

        self.http.side_effect = download
        try:
            self.assertIsNone(self.cache.get("fr"))
            self.assertTrue(entered.wait(2))
            for _ in range(50):
                self.assertIsNone(self.cache.get("fr"))
            self.http.assert_called_once()
        finally:
            release.set()
        self.drain()
        self.assertIsNotNone(self.cache.get("fr"))

    def test_disk_hit_works_without_http_after_restart(self):
        self.directory.mkdir()
        (self.directory / "fr_128x96.png").write_bytes(png())
        self.assertIsNone(self.cache.get("fr"))
        self.drain()
        self.assertIsNotNone(self.cache.get("fr"))
        self.http.assert_not_called()
        self.cache.close()
        restarted = self.make_cache()
        self.assertIsNone(restarted.get("fr"))
        self.drain(restarted)
        self.assertIsNotNone(restarted.get("fr"))
        self.http.assert_not_called()

    def test_invalid_iso_codes_and_sizes_never_schedule_work(self):
        for code in (None, "", "zz", "../fr", "fr.png", 1, ["fr"]):
            self.assertIsNone(self.cache.get(code))
        for size in (None, "../128x96", "999999x999999", "128X96", ["128x96"]):
            self.assertIsNone(self.cache.get("fr", size))
        self.assertIsNone(self.cache._worker)
        self.http.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_supported_sizes_are_separate_cache_entries(self):
        self.http.side_effect = lambda url, **kwargs: Mock(
            content=png(tuple(map(int, url.split("/")[-2].split("x")))))
        for size in ("128x96", "192x144", "256x192"):
            self.assertIsNone(self.cache.get("fr", size))
            self.drain()
            self.assertEqual(self.cache.get("fr", size).size, tuple(map(int, size.split("x"))))
        self.assertEqual(self.http.call_count, 3)

    def test_manual_country_names_and_iso_overrides_are_normalized(self):
        for country in (" France ", "FRANCE", "france", " FR "):
            self.cache.get(country)
            self.drain()
            self.assertIsNotNone(self.cache.get(country))
        self.http.assert_called_once_with("https://flagcdn.com/128x96/fr.png", timeout=(3, 5))

    def test_failures_are_logged_and_backoff_grows_until_success(self):
        now = [100]
        cache = self.make_cache(clock=lambda: now[0], retry_seconds=10, max_retry_seconds=15)
        self.http.side_effect = requests.Timeout("offline")
        for start, next_retry in ((100, 110), (110, 125)):
            now[0] = start
            with self.assertLogs("utils.country_flags", level="WARNING") as logs:
                self.assertIsNone(cache.get("fr"))
                self.drain(cache)
            self.assertIn("offline", logs.output[0])
            self.assertIn("retry in", logs.output[0])
            attempts = self.http.call_count
            now[0] = next_retry - 1
            for _ in range(10):
                self.assertIsNone(cache.get("fr"))
            self.assertEqual(self.http.call_count, attempts)
        now[0] = 125
        self.http.side_effect = None
        self.assertIsNone(cache.get("fr"))
        self.drain(cache)
        self.assertIsNotNone(cache.get("fr"))
        self.assertNotIn(("fr", "128x96"), cache._failures)

    def test_http_errors_and_invalid_images_are_not_cached(self):
        for response in (
            Mock(content=png(), raise_for_status=Mock(side_effect=requests.HTTPError("404"))),
            Mock(content=b"not an image"),
            Mock(content=png((1, 1))),
            Mock(content=b"x" * (1024 * 1024 + 1)),
        ):
            with self.subTest(response=response):
                cache = self.make_cache()
                self.http.return_value = response
                with self.assertLogs("utils.country_flags", level="WARNING"):
                    self.assertIsNone(cache.get("fr"))
                    self.drain(cache)
                self.assertIsNone(cache.get("fr"))
                self.assertFalse((self.directory / "fr_128x96.png").exists())
                response.close.assert_called_once()

    def test_corrupt_disk_cache_is_logged_and_replaced(self):
        self.directory.mkdir()
        path = self.directory / "fr_128x96.png"
        path.write_bytes(b"broken")
        with self.assertLogs("utils.country_flags", level="WARNING") as logs:
            self.cache.get("fr")
            self.drain()
        self.assertIn("Cannot read cached country flag", logs.output[0])
        self.assertIsNotNone(self.cache.get("fr"))
        self.assertEqual(path.read_bytes(), self.response.content)

    def test_disk_write_failure_still_keeps_download_in_memory(self):
        self.directory.write_bytes(b"not a directory")
        with self.assertLogs("utils.country_flags", level="WARNING") as logs:
            self.cache.get("fr")
            self.drain()
        self.assertTrue(any("Cannot save country flag" in line for line in logs.output))
        self.assertIsNotNone(self.cache.get("fr"))
        self.directory.unlink()

    def test_queue_and_memory_are_bounded(self):
        cache = self.make_cache(max_pending=1, max_images=1)
        entered = threading.Event()
        release = threading.Event()

        def download(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Download was not released")
            return self.response

        self.http.side_effect = download
        try:
            cache.get("fr")
            self.assertTrue(entered.wait(2))
            cache.get("us")
            cache.get("de")
            self.assertEqual(cache._queue.qsize(), 1)
            self.assertEqual(len(cache._pending), 2)
        finally:
            release.set()
        self.drain(cache)
        self.assertEqual(self.http.call_count, 2)
        self.assertEqual(len(cache._images), 1)
        cache.get("fr")
        self.drain(cache)
        self.assertIsNotNone(cache.get("fr"))
        self.assertEqual(self.http.call_count, 2)  # Evicted images reload from disk.


class CountryFlagDrawingTests(unittest.TestCase):
    def setUp(self):
        source = ROOT / "local_slideshow.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "draw_overlay")
        self.cache = Mock()
        self.flag = Image.new("RGBA", (128, 96), (200, 80, 40, 255))
        self.cache.get.return_value = self.flag
        namespace = {
            "pygame": pygame, "Image": Image, "datetime": datetime, "timedelta": timedelta,
            "parse_color": lambda value: (255, 255, 255),
            "load_country_codes": lambda: {"france": "fr"},
            "country_flags": self.cache,
            "overlay_data": Mock(get=Mock(return_value=(None, None))),
            "draw_text_with_outline": Mock(), "load_icon": Mock(return_value=None),
            "load_font": lambda path, size: pygame.font.Font(None, size),
            "get_default_font_path": lambda: None,
            "get_weather_and_forecast": Mock(side_effect=AssertionError("Weather in draw")),
            "get_tides": Mock(side_effect=AssertionError("Tides in draw")),
        }
        self.namespace = namespace
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        self.draw = namespace["draw_overlay"]
        self.http = self.enterContext(patch("requests.get", side_effect=AssertionError("HTTP in drawing")))

    def test_flag_only_preserves_size_opacity_and_all_positions(self):
        for position, origin in (
            ("top_left", (7, 9)), ("top_right", (265, 9)),
            ("bottom_left", (7, 195)), ("bottom_right", (265, 195)),
        ):
            with self.subTest(position=position):
                screen = pygame.Surface((400, 300), pygame.SRCALPHA)
                screen.fill((0, 0, 0, 0))
                config = {
                    "show_photo_date": False, "show_photo_location": False,
                    "country_flag_position": position, "country_flag_opacity": 0.5,
                    "country_flag_offset_x": 7, "country_flag_offset_y": 9,
                }
                self.draw(screen, 400, 300, config, None, {"country": "France"})
                self.cache.get.assert_called_with("France", "128x96")
                self.assertEqual(screen.get_bounding_rect(), pygame.Rect(*origin, 128, 96))
                self.assertEqual(screen.get_at(origin), (200, 80, 40, 127))
                self.assertEqual(self.flag.getpixel((0, 0)), (200, 80, 40, 255))
        self.http.assert_not_called()

    def test_explicit_country_code_is_used_for_flag(self):
        screen = pygame.Surface((400, 300), pygame.SRCALPHA)
        self.draw(screen, 400, 300, {}, None, {"countryCode": " FR ", "country": "France"})
        self.cache.get.assert_called_once_with(" FR ", "128x96")

    def test_weather_and_tides_render_from_snapshots_without_network(self):
        pygame.font.init()
        self.addCleanup(pygame.font.quit)
        font = pygame.font.Font(None, 20)
        weather = {
            "current": {"weather": [{"icon": "01d", "description": "sunny"}],
                        "main": {"temp": 20}},
            "forecast": [{"icon": "01d", "day": "Tomorrow", "max_temp": 22, "min_temp": 14}],
        }
        tides = [{"time": datetime.now().astimezone().isoformat(),
                  "type": "high", "height": 2.0}]
        self.namespace["overlay_data"].get.return_value = (weather, tides)
        screen = pygame.Surface((800, 600), pygame.SRCALPHA)
        config = {"show_clock": True, "show_weather": True, "show_tides": True}
        self.draw(screen, 800, 600, config, font)
        self.namespace["overlay_data"].get.assert_called_once_with(config)
        self.namespace["get_weather_and_forecast"].assert_not_called()
        self.namespace["get_tides"].assert_not_called()
        self.assertTrue(self.namespace["draw_text_with_outline"].called)
        self.http.assert_not_called()

    def test_weather_renders_temperature_and_icon_bottom_right(self):
        pygame.font.init()
        self.addCleanup(pygame.font.quit)
        font = pygame.font.Font(None, 20)
        weather = {
            "current": {
                "city": "Haifa",
                "weather": [{"icon": "01d", "description": "clear sky"}],
                "main": {"temp": 20},
                "wind_speed": 5,
                "precipitation": 0,
            },
            "forecast": [{
                "day": "Tomorrow",
                "max_temp": 22,
                "min_temp": 14,
                "precipitation": 1.0,
            }],
        }
        self.namespace["overlay_data"].get.return_value = (weather, None)
        screen = pygame.Surface((800, 600), pygame.SRCALPHA)
        self.draw(screen, 800, 600, {"show_clock": False, "show_weather": True}, font)

        rendered_text = [
            call.args[1] for call in self.namespace["draw_text_with_outline"].call_args_list
        ]
        self.assertEqual(rendered_text, ["20°C"])
        weather_calls = self.namespace["draw_text_with_outline"].call_args_list
        self.assertEqual(len(weather_calls), 1)
        text_x, text_y = weather_calls[0].args[5]
        self.assertGreater(text_x, 400)  # Right half of the display.
        self.assertGreater(text_y, 450)  # Bottom area of the display.
        self.assertTrue(weather_calls[0].args[2].get_height() <= 30)
        icon_call = self.namespace["load_icon"].call_args_list[-1]
        self.assertEqual(icon_call.args[0], "01d")

    def test_miss_and_disabled_flag_do_not_draw(self):
        screen = pygame.Surface((400, 300), pygame.SRCALPHA)
        self.cache.get.return_value = None
        self.draw(screen, 400, 300, {}, None, {"country": "France"})
        self.assertEqual(screen.get_bounding_rect().size, (0, 0))
        self.cache.reset_mock()
        self.draw(screen, 400, 300, {"show_country_flag": False}, None, {"country": "France"})
        self.cache.get.assert_not_called()
        self.http.assert_not_called()


class OverlayDataCacheTests(unittest.TestCase):
    def setUp(self):
        source = ROOT / "local_slideshow.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        node = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "OverlayDataCache")
        self.weather = Mock(return_value={"current": {"temperature": 20}})
        self.tides = Mock(return_value=[{"type": "high"}])
        self.now = [0]
        namespace = {"queue": queue, "threading": threading, "time": time,
                     "logger": Mock()}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
        self.cache = namespace["OverlayDataCache"](
            self.weather, self.tides, clock=lambda: self.now[0])
        self.addCleanup(self.cache.close)
        self.config = {"show_weather": True, "show_clock": True, "show_tides": True}
        self.http = self.enterContext(patch("requests.get", side_effect=AssertionError("Unexpected HTTP")))

    def test_loaders_run_on_worker_and_snapshots_refresh_without_blocking(self):
        caller = threading.get_ident()
        threads = []
        self.weather.side_effect = lambda config: threads.append(threading.get_ident()) or {"current": {}}
        self.assertEqual(self.cache.get(self.config), (None, None))
        self.cache._queue.join()
        self.assertEqual(self.cache.get(self.config), ({"current": {}}, [{"type": "high"}]))
        self.assertNotEqual(threads, [caller])
        self.weather.assert_called_once()
        self.now[0] = 2
        self.cache.get(self.config)
        self.cache._queue.join()
        self.assertEqual(self.weather.call_count, 2)
        self.assertEqual(self.tides.call_count, 2)

    def test_pending_refresh_keeps_old_snapshot_and_has_no_queue_growth(self):
        self.cache.get(self.config)
        self.cache._queue.join()
        old = self.cache.get(self.config)
        entered = threading.Event()
        release = threading.Event()

        def slow_loader(config):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Loader not released")
            return {"updated": True}

        self.weather.side_effect = slow_loader
        self.now[0] = 2
        try:
            self.assertEqual(self.cache.get(self.config), old)
            self.assertTrue(entered.wait(2))
            for _ in range(50):
                self.assertEqual(self.cache.get(self.config), old)
            self.assertEqual(self.cache._queue.qsize(), 0)
        finally:
            release.set()
        self.cache._queue.join()
        self.assertEqual(self.cache.get(self.config)[0], {"updated": True})

    def test_disabled_loaders_are_skipped_and_settings_changes_hide_old_data(self):
        self.cache.get(self.config)
        self.cache._queue.join()
        disabled = {**self.config, "show_weather": False, "show_tides": False}
        self.assertEqual(self.cache.get(disabled), (None, None))
        self.cache._queue.join()
        self.assertEqual(self.cache.get(disabled), (None, None))
        self.weather.assert_called_once()
        self.tides.assert_called_once()

    def test_loader_exception_does_not_stop_other_loader_or_worker(self):
        self.weather.side_effect = ValueError("synthetic failure")
        self.cache.get(self.config)
        self.cache._queue.join()
        self.assertEqual(self.cache.get(self.config), (None, [{"type": "high"}]))
        self.assertTrue(self.cache._worker.is_alive())
        self.http.assert_not_called()

    def test_drawing_never_calls_network_backed_getters(self):
        source = ROOT / "local_slideshow.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        draw = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "draw_overlay")
        calls = {node.func.id for node in ast.walk(draw)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertNotIn("get_weather_and_forecast", calls)
        self.assertNotIn("get_tides", calls)


if __name__ == "__main__":
    unittest.main()
