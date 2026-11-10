import ast
import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import requests

import local_slideshow
from utils.config_manager import _without_retired_settings
from utils.weather_cities import CITIES, DEFAULT_WEATHER_CITY


def forecast_payload():
    first_day = date.today()
    return {
        "current": {
            "temperature_2m": 22.5,
            "wind_speed_10m": 12.0,
            "precipitation": 0.4,
            "weather_code": 3,
            "is_day": 1,
        },
        "daily": {
            "time": [(first_day + timedelta(days=offset)).isoformat() for offset in range(5)],
            "temperature_2m_max": [24, 25, 26, 27, 28],
            "temperature_2m_min": [15, 16, 17, 18, 19],
            "precipitation_sum": [0, 1, 2, 3, 4],
            "weather_code": [0, 1, 2, 3, 61],
        },
    }


class OpenMeteoWeatherTests(unittest.TestCase):
    def setUp(self):
        local_slideshow._weather_and_forecast_data = None
        local_slideshow._last_weather_and_forecast_fetch = None
        local_slideshow._weather_warning_printed = False
        local_slideshow._last_weather_city = None
        local_slideshow._last_weather_units = None

    def test_selected_city_fetches_current_and_five_daily_forecasts(self):
        response = Mock()
        response.json.return_value = forecast_payload()
        config = {
            "weather_city": "Haifa",
            "weather_units": "imperial",
            "weather_update_interval_minutes": 30,
        }

        with patch.object(local_slideshow.requests, "get", return_value=response) as get:
            result = local_slideshow.get_weather_and_forecast(config)

        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], "https://api.open-meteo.com/v1/forecast")
        params = get.call_args.kwargs["params"]
        self.assertEqual((params["latitude"], params["longitude"]), (32.8192, 34.9992))
        self.assertEqual(params["timezone"], "Asia/Jerusalem")
        self.assertEqual(params["temperature_unit"], "fahrenheit")
        self.assertEqual(params["wind_speed_unit"], "mph")
        self.assertEqual(result["current"]["main"]["temp"], 22.5)
        self.assertEqual(result["current"]["weather"][0]["icon"], "04d")
        self.assertEqual(result["current"]["wind_speed"], 12.0)
        self.assertEqual(result["current"]["precipitation"], 0.4)
        self.assertEqual(len(result["forecast"]), 5)
        self.assertEqual(result["forecast"][0]["day"], "Today")
        self.assertEqual(result["forecast"][0]["precipitation"], 0)

    def test_failed_city_change_does_not_return_previous_city_weather(self):
        response = Mock()
        response.json.return_value = forecast_payload()
        with patch.object(local_slideshow.requests, "get", return_value=response):
            self.assertIsNotNone(local_slideshow.get_weather_and_forecast({
                "weather_city": "Tel Aviv",
                "weather_units": "metric",
                "weather_update_interval_minutes": 30,
            }))

        config = {
            "weather_city": "Jerusalem",
            "weather_units": "metric",
            "weather_update_interval_minutes": 30,
        }
        with patch.object(
            local_slideshow.requests,
            "get",
            side_effect=requests.exceptions.Timeout,
        ) as get:
            self.assertIsNone(local_slideshow.get_weather_and_forecast(config))
            self.assertIsNone(local_slideshow.get_weather_and_forecast(config))
        get.assert_called_once()

    def test_city_selection_and_legacy_settings_are_normalized(self):
        self.assertEqual(len(CITIES), 14)
        cleaned = _without_retired_settings({
            "weather_city": "Paris",
            "weather_api_key": "old-key",
        })
        self.assertEqual(cleaned["weather_city"], DEFAULT_WEATHER_CITY)
        self.assertNotIn("weather_api_key", cleaned)

    def test_windows_entrypoint_enables_native_certificate_trust(self):
        source = Path(local_slideshow.__file__).read_text(encoding="utf-8")
        bootstrap = ast.parse(source).body[1]
        truststore = Mock()
        namespace = {"__name__": "__main__", "os": SimpleNamespace(name="nt")}
        with patch.dict(sys.modules, {"truststore": truststore}):
            exec(compile(ast.Module(body=[bootstrap], type_ignores=[]), "<bootstrap>", "exec"),
                 namespace)
        truststore.inject_into_ssl.assert_called_once_with()

    def test_native_certificate_bootstrap_does_not_change_linux_or_imports(self):
        source = Path(local_slideshow.__file__).read_text(encoding="utf-8")
        bootstrap = ast.parse(source).body[1]
        for module_name, os_name in (("__main__", "posix"), ("local_slideshow", "nt")):
            with self.subTest(module_name=module_name, os_name=os_name):
                truststore = Mock()
                namespace = {"__name__": module_name, "os": SimpleNamespace(name=os_name)}
                with patch.dict(sys.modules, {"truststore": truststore}):
                    exec(compile(ast.Module(body=[bootstrap], type_ignores=[]),
                                 "<bootstrap>", "exec"), namespace)
                truststore.inject_into_ssl.assert_not_called()


if __name__ == "__main__":
    unittest.main()
