import os
import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_console
import lb_samples
import lb_session as ls
from lb_rig import Rig


class Env:
    def __init__(self, notes=None):
        self.rig = Rig(push_to_show=False)
        self.out = []
        self.con = lb_console.Console(self.rig, out=self.out.append, notes_path=notes)

    def do(self, line, ms=0):
        self.con.handle(line)
        self.settle(ms)

    def settle(self, ms):
        for _ in range(max(1, ms // 20)):
            self.rig.clock.advance(20)
            self.con.tick()
            self.rig.ui.tick()

    @property
    def id(self):
        return self.rig.id

    def said(self):
        return "\n".join(self.out)


class Basics(unittest.TestCase):
    def test_help_and_blank(self):
        e = Env()
        e.do("")
        e.do("   ")
        self.assertEqual(e.out, [])
        e.do("help")
        self.assertTrue(any("press NAME" in x for x in e.out))
        self.assertTrue(all(len(x) < 100 for x in e.out))

    def test_unlock_and_navigation(self):
        e = Env()
        e.do("unlock", 60)
        self.assertEqual(e.id, "Idle")
        e.do("press d", 200)
        self.assertEqual(e.id, "Accounts")
        e.do("press DOWN 40", 200)
        self.assertEqual(e.rig.ui.screen()["body"]["index"], 1)
        e.do("press b", 200)
        self.assertEqual(e.id, "Idle")

    def test_press_releases_after_the_time(self):
        e = Env()
        e.do("unlock", 60)
        e.do("press p 500")
        self.assertTrue(e.rig.ui._ptt)
        e.settle(300)
        self.assertTrue(e.rig.ui._ptt)
        e.settle(300)
        self.assertFalse(e.rig.ui._ptt)

    def test_down_up(self):
        e = Env()
        e.do("unlock", 60)
        e.do("down p", 100)
        self.assertTrue(e.rig.ui._ptt)
        e.do("up p", 100)
        self.assertFalse(e.rig.ui._ptt)
        self.assertEqual(e.id, "ShowQR")  # a tap shows my QR

    def test_hold_approves_through_the_console(self):
        e = Env()
        e.do("unlock", 60)
        e.do("host sign", 100)
        self.assertEqual(e.id, "HostRequest")
        e.do("press p 700", 1000)
        self.assertIsNotNone(e.rig.session.pending())  # too short for a signature
        e.do("press p 1700", 2200)
        self.assertIsNone(e.rig.session.pending())
        self.assertEqual(e.rig.session.decision(1), ls.APPROVED)

    def test_swap_replaces_the_request(self):
        e = Env()
        e.do("unlock", 60)
        e.do("host sign", 100)
        a = e.rig.session.pending()["id"]
        e.do("swap", 100)
        p = e.rig.session.pending()
        self.assertNotEqual(a, p["id"])
        self.assertEqual(p["summary"], lb_samples.REPLACEMENT["SIGN"])
        e.do("swap auth")
        self.assertEqual(e.rig.session.pending()["kind"], "AUTH")

    def test_scan_and_samples(self):
        e = Env()
        e.do("samples")
        self.assertEqual(len(e.out), len(lb_samples.SAMPLES))
        e.out.clear()
        e.do("scan 0")
        self.assertIn("ignored", e.said())  # locked
        e.do("unlock", 60)
        e.do("scan 0", 100)
        self.assertEqual(e.id, "ConfirmOTP")

    def test_fp_clock_time_warp(self):
        e = Env()
        e.do("fp nomatch")
        self.assertEqual(e.rig.fp.mode, "nomatch")
        e.do("clock untrusted")
        self.assertFalse(e.rig.clock.trusted_flag)
        e.do("time 1700000123")
        self.assertTrue(e.rig.clock.trusted_flag)
        self.assertEqual(e.rig.clock.now(), 1700000123)
        e.do("time demo")
        self.assertEqual(e.rig.clock.now(), lb_console.DEMO_UNIX)
        e.do("unlock", 60)
        e.do("warp 61000", 1300)
        self.assertEqual(e.id, "Locked")

    def test_reboot_and_reset(self):
        e = Env()
        for _ in range(3):
            e.rig.combo([3] * 10)
            e.rig.press("SELECT")
        self.assertEqual(e.rig.ks.attempts(), 3)
        e.do("reboot")
        self.assertEqual((e.id, e.rig.ks.attempts()), ("Locked", 3))
        e.do("reset")
        self.assertEqual(e.rig.ks.attempts(), 0)
        self.assertEqual(len(e.rig.oath.list()), 4)

    def test_status_and_trail(self):
        e = Env()
        e.do("unlock", 60)
        e.out.clear()
        e.do("status")
        self.assertIn("screen Idle", e.out[0])
        self.assertIn("accounts 4", e.out[0])
        self.assertIn("pending none", e.out[1])
        e.out.clear()
        e.do("trail")
        self.assertTrue(e.out and "btn" in e.said())

    def test_note_is_saved_with_context(self):
        path = "_test_notes.txt"  # no tempfile or os.path on MicroPython
        try:
            os.remove(path)
        except OSError:
            pass
        e = Env(notes=path)
        e.do("unlock", 60)
        e.do("press d", 200)
        e.do("note the list is hard to read\nnewline attempt")
        with open(path) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("the list is hard to read", lines[0])
        self.assertIn("screen=Accounts", lines[0])
        self.assertIn("trail=", lines[0])
        e.do("note")
        self.assertIn("error:", e.out[-1])
        e.do("note " + "x" * 2000)
        with open(path) as f:
            self.assertLess(len(f.read().splitlines()[-1]), 1500)
        os.remove(path)


class Feedback(unittest.TestCase):
    """Every state-changing command says what it did, so you can tell it worked."""

    def test_time_confirms_with_the_date_it_set(self):
        e = Env()
        e.do("time 1790946000")
        self.assertEqual(e.out[-1], "clock set to 2026-10-02 13:00:00 UTC, trusted")
        e.do("time demo")
        self.assertEqual(e.out[-1], "clock set to 2023-11-14 22:13:20 UTC, trusted")

    def test_other_commands_confirm(self):
        e = Env()
        e.do("unlock", 60)
        for line, expect in [("host sign", "request sent: SIGN"), ("swap", "request replaced: SIGN"),
                             ("fp nomatch", "fingerprint: nomatch"), ("clock untrusted", "NOT trusted"),
                             ("clock trusted", "is now trusted"), ("warp 1500", "skipped 1500 ms"),
                             ("reboot", "rebooted"), ("reset", "factory reset")]:
            e.do(line)
            self.assertIn(expect, e.out[-1], line)

    def test_status_shows_whether_the_clock_took(self):
        e = Env()
        e.do("clock untrusted")
        e.do("status")
        self.assertIn("NOT trusted", e.out[-1])
        e.do("time demo")
        e.do("status")
        self.assertIn("clock trusted", e.out[-1])
        self.assertNotIn("--:--", e.out[-1])

    def test_a_set_clock_gives_codes_and_an_unset_one_refuses(self):
        e = Env()
        e.do("clock untrusted")
        e.do("unlock", 60)
        e.do("press d", 200)
        e.do("press s", 200)
        self.assertEqual(e.rig.ui.screen()["lines"], ["Set the clock first"])
        e.do("press b", 200)
        e.do("time demo")
        e.do("press s", 200)
        self.assertEqual(e.id, "TOTPCode")

    def test_time_command_rejects_nonsense_with_a_clear_message(self):
        e = Env()
        for bad in ("time", "time soon", "time 0", "time -1", "time 99999999999", "time 12.5"):
            e.do(bad)
            self.assertTrue(e.out[-1].startswith("error:"), bad)
        self.assertEqual(e.rig.clock.now(), 1700000000 + 1)  # untouched (manual clock epoch + 1 s)


class DateText(unittest.TestCase):
    def test_known_dates(self):
        for u, want in [(0, "1970-01-01 00:00:00"), (59, "1970-01-01 00:00:59"),
                        (86399, "1970-01-01 23:59:59"), (951782400, "2000-02-29 00:00:00"),
                        (1709164800, "2024-02-29 00:00:00"), (1709251200, "2024-03-01 00:00:00"),
                        (1700000000, "2023-11-14 22:13:20"), (4102444800, "2100-01-01 00:00:00"),
                        (4107542400, "2100-03-01 00:00:00")]:
            self.assertEqual(lb_console.utc_text(u), want, u)

    @unittest.skipUnless(sys.implementation.name == "cpython", "needs CPython's calendar")
    def test_matches_the_standard_library_over_a_wide_sweep(self):
        import time
        step = 86400 * 7 + 3671  # a prime-ish stride that lands on varied hours and days
        for u in range(0, 4102444800, step):
            self.assertEqual(lb_console.utc_text(u), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(u)), u)


class BadInput(unittest.TestCase):
    def test_nothing_raises_and_errors_say_what_to_do(self):
        e = Env()
        for line in ["bogus", "press", "press x", "press s abc", "press s 0", "press s 99999999",
                     "down", "host", "host nope", "swap nope", "scan", "scan x", "scan 99", "scan -1",
                     "fp", "fp maybe", "clock", "clock soon", "time", "time abc", "time -5",
                     "time 99999999999", "warp", "warp 0", "warp 99999999", "note", "\x00\x01",
                     "press s 5 6 7", "unlock now please"]:
            before = len(e.out)
            e.do(line)  # must not raise
            if line not in ("press s 5 6 7", "unlock now please"):
                self.assertGreater(len(e.out), before, line)
                self.assertTrue(e.out[-1].startswith("error:"), (line, e.out[-1]))

    def test_aliases_and_case(self):
        e = Env()
        e.do("PRESS U", 100)
        self.assertEqual(e.rig.ui.screen()["body"]["dots"], 1)
        e.do("Press Down", 100)
        self.assertEqual(e.rig.ui.screen()["body"]["dots"], 2)


if __name__ == "__main__":
    unittest.main()
