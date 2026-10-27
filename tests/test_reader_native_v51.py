import unittest
from datetime import datetime
from conexion.reader import display_date


class NativeDateTests(unittest.TestCase):
    def test_calendar_tooltip_formats_use_windows_local_time(self):
        expected = datetime(2026, 10, 27, 17, 10).timestamp()
        for value in (
            "Tue 2026-10-27 17:10",
            "2026-10-27 17:10",
            "10/27/2026 5:10 PM",
            "October 27, 2026 5:10 PM",
            "martes 27 de octubre de 2026 17:10",
            "27/10/2026 17:10",
        ):
            with self.subTest(value=value):
                self.assertEqual(display_date(value), (expected, 60))

    def test_relative_ambiguous_and_body_text_are_not_calendar_timestamps(self):
        for value in (
            "17:10",
            "Sun 23:08",
            "ayer",
            "hace un minuto",
            "Código 012345 2026-10-27 17:10",
            "2026-02-30 17:10",
            None,
        ):
            self.assertIsNone(display_date(value))


if __name__ == "__main__":
    unittest.main()
