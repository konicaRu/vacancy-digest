import tempfile
import unittest
from datetime import date
from pathlib import Path

from vd.workcal import is_workday


def year_2026() -> str:
    """Производственный календарь 2026 в формате isdayoff.ru (1 — выходной), живой ответ от 21.10.2026."""
    days = []
    off_weekdays = {(1, 1), (1, 2), (1, 5), (1, 6), (1, 7), (1, 8), (1, 9), (2, 23), (3, 9), (5, 1), (5, 11),
                    (6, 12), (11, 4), (12, 31)}
    d = date(2026, 1, 1)
    while d.year == 2026:
        days.append("1" if d.weekday() >= 5 or (d.month, d.day) in off_weekdays else "0")
        d = date.fromordinal(d.toordinal() + 1)
    return "".join(days)


class WorkcalTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        return year_2026() + "\n"

    def test_calendar_days_and_cache(self):
        cases = {date(2026, 10, 21): True,    # среда
                 date(2026, 10, 24): False,   # суббота
                 date(2026, 11, 4): False,    # День народного единства, среда
                 date(2026, 1, 9): False}     # перенос выходного
        for day, expected in cases.items():
            with self.subTest(day=day):
                self.assertEqual(is_workday(day, self.dir, self.fetch), (expected, None))
        self.assertEqual(self.calls, ["https://isdayoff.ru/api/getdata?year=2026"])  # скачали один раз
        self.assertTrue((self.dir / "calendar-2026.txt").exists())

    def test_unavailable_calendar_falls_back_to_weekdays(self):
        def down(url):
            raise ConnectionError("нет сети")
        workday, warning = is_workday(date(2026, 11, 4), self.dir, down)
        self.assertTrue(workday)  # среда по правилу пн–пт, хотя праздник
        self.assertIn("пн–пт", warning)
        self.assertFalse(is_workday(date(2026, 10, 24), self.dir, down)[0])  # суббота
        self.assertFalse((self.dir / "calendar-2026.txt").exists())  # плохое не кэшируем — завтра попробуем снова

    def test_garbage_answer_is_not_trusted(self):
        workday, warning = is_workday(date(2026, 11, 4), self.dir, lambda url: "<html>error</html>")
        self.assertTrue(workday)
        self.assertIsNotNone(warning)


if __name__ == "__main__":
    unittest.main()
