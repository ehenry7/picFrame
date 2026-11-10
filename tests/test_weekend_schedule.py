import ast
from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class WeekendScheduleTests(unittest.TestCase):
    def test_all_schedule_day_selectors(self):
        for filename, expected_count in (("app.py", 3), ("local_slideshow.py", 1)):
            tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
            selectors = [
                node for node in ast.walk(tree)
                if isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Call)
                and isinstance(node.left.func, ast.Attribute)
                and node.left.func.attr == "weekday"
            ]
            self.assertEqual(len(selectors), expected_count)
            for selector in selectors:
                expression = compile(ast.Expression(selector), filename, "eval")
                for day in range(7):
                    with self.subTest(file=filename, day=day):
                        now = datetime(2026, 11, 9 + day, 12)
                        self.assertEqual(eval(expression, {"now": now}), day in (4, 5))

    def test_slideshow_and_ping_use_correct_hours_every_day(self):
        config = {
            "active_start_weekday": "08:00", "active_end_weekday": "09:00",
            "active_start_weekend": "10:00", "active_end_weekend": "11:00",
        }
        for filename, function_name in (
            ("local_slideshow.py", "is_within_active_hours"), ("app.py", "ping")
        ):
            tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
            function = next(node for node in tree.body
                            if isinstance(node, ast.FunctionDef) and node.name == function_name)
            function.decorator_list = []
            clock = Mock()
            clock.strptime = datetime.strptime
            namespace = {
                "datetime": clock, "logger": Mock(), "load_config": lambda: config,
                "jsonify": lambda value: value, "APP_INSTANCE_ID": "test",
                "is_slideshow_running": lambda: False,
            }
            exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), namespace)
            for day in range(7):
                for hour in (8, 10, 12):
                    with self.subTest(function=function_name, day=day, hour=hour):
                        clock.now.return_value = datetime(2026, 11, 9 + day, hour, 30)
                        expected = hour == (10 if day in (4, 5) else 8)
                        result = (namespace[function_name](config)
                                  if function_name == "is_within_active_hours"
                                  else namespace[function_name]()["is_active_hours"])
                        self.assertEqual(result, expected)
