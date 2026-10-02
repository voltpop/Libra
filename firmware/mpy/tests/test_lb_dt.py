import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_dt


class Dates(unittest.TestCase):
    def test_known_points(self):
        for u, want in [(0, [1970, 1, 1, 0, 0, 0]), (59, [1970, 1, 1, 0, 0, 59]),
                        (86399, [1970, 1, 1, 23, 59, 59]), (951782400, [2000, 2, 29, 0, 0, 0]),
                        (1709164800, [2024, 2, 29, 0, 0, 0]), (1709251200, [2024, 3, 1, 0, 0, 0]),
                        (1700000000, [2023, 11, 14, 22, 13, 20]), (1790946000, [2026, 10, 2, 13, 0, 0]),
                        (4102444800, [2100, 1, 1, 0, 0, 0]), (4107542400, [2100, 3, 1, 0, 0, 0])]:
            self.assertEqual(lb_dt.to_fields(u), want, u)
            self.assertEqual(lb_dt.to_unix(*want), u, want)

    def test_text(self):
        self.assertEqual(lb_dt.text(1790946000), "2026-10-02 13:00:00")
        self.assertEqual(lb_dt.text(0), "1970-01-01 00:00:00")

    def test_leap_rules(self):
        for y, leap in [(1900, False), (2000, True), (2023, False), (2024, True), (2100, False), (2400, True)]:
            self.assertEqual(lb_dt.is_leap(y), leap, y)
        self.assertEqual(lb_dt.days_in_month(2024, 2), 29)
        self.assertEqual(lb_dt.days_in_month(2100, 2), 28)
        self.assertEqual([lb_dt.days_in_month(2026, m) for m in range(1, 13)],
                         [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])

    def test_round_trip_over_a_wide_sweep(self):
        for u in range(0, 4102444800, 86400 * 3 + 3671):
            self.assertEqual(lb_dt.to_unix(*lb_dt.to_fields(u)), u)

    @unittest.skipUnless(sys.implementation.name == "cpython", "needs CPython's calendar")
    def test_matches_the_standard_library(self):
        import time
        for u in range(0, 4102444800, 86400 * 5 + 7919):
            self.assertEqual(lb_dt.to_fields(u), list(time.gmtime(u)[:6]), u)

    def test_rejects_impossible_dates(self):
        for bad in [(2026, 2, 29, 0, 0, 0), (2026, 4, 31, 0, 0, 0), (2026, 13, 1, 0, 0, 0),
                    (2026, 0, 1, 0, 0, 0), (2026, 1, 0, 0, 0, 0), (2026, 1, 1, 24, 0, 0),
                    (2026, 1, 1, 0, 60, 0), (2026, 1, 1, 0, 0, 60), (1969, 12, 31, 0, 0, 0),
                    (2026, 1, 1, -1, 0, 0), (2400, 1, 1, 0, 0, 0)]:
            with self.assertRaises(ValueError, msg=repr(bad)):
                lb_dt.to_unix(*bad)
        self.assertEqual(lb_dt.to_unix(2024, 2, 29, 23, 59, 59), 1709251199)


if __name__ == "__main__":
    unittest.main()
