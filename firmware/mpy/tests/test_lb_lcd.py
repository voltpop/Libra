import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
sys.path.insert(0, "pico")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_lcd
from lb_lcd import LcdView, Marquee, fit, two, bar, raw_lines
from lb_rig import Rig

GOOD = b"otpauth://totp/Lab:rfc?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&digits=8&issuer=Lab"


def lines(r, marquee=False):
    return LcdView(marquee=marquee).lines(r.ui.screen(), r.clock.ticks())


def ready():
    r = Rig(push_to_show=False)
    r.unlock()
    return r


def sane(testcase, l1, l2):
    for ln in (l1, l2):
        testcase.assertEqual(len(ln), 16, repr(ln))
        testcase.assertTrue(all(32 <= ord(c) < 127 or c in "\x00\x01\x02\x03\x04" for c in ln), repr(ln))  # ASCII plus the custom symbols


class Helpers(unittest.TestCase):
    def test_fit(self):
        self.assertEqual(fit("abc"), "abc" + " " * 13)
        self.assertEqual(fit("x" * 20), "x" * 16)
        self.assertEqual(fit(""), " " * 16)
        self.assertEqual(fit("abcdef", 4), "abcd")

    def test_ascii_only(self):
        self.assertEqual(fit("Jürgen"), "J?rgen" + " " * 10)
        self.assertEqual(fit("a\nb\x07c"), "a?b?c" + " " * 11)
        self.assertEqual(fit(chr(0x264E) + chr(0x1F512)), "\x00\x01" + " " * 14)  # custom symbols pass through

    def test_two(self):
        self.assertEqual(two("Libra", "L1 12:45"), "Libra   L1 12:45")
        self.assertEqual(len(two("A" * 30, "12:45")), 16)
        self.assertTrue(two("A" * 30, "12:45").endswith(" 12:45"))
        self.assertEqual(two("ab", ""), "ab" + " " * 14)
        self.assertEqual(len(two("x", "y" * 30)), 16 + 14)  # right side is never cut: caller's job

    def test_bar(self):
        self.assertEqual(bar(0, 10), ".........."[:10])
        self.assertEqual(bar(500, 10), "#####.....")
        self.assertEqual(bar(1000, 10), "#" * 10)
        self.assertEqual(bar(999, 10), "#########.")
        self.assertEqual(bar(-5, 4), "....")
        self.assertEqual(bar(5000, 4), "####")


class Scrolling(unittest.TestCase):
    TEXT = "Unlock to continue - Sign commit 4f2a9c"

    def test_short_text_is_static(self):
        m = Marquee()
        self.assertEqual(m.view("hello", 0), fit("hello"))
        self.assertEqual(m.view("hello", 99999), fit("hello"))
        self.assertEqual(m.view("x" * 16, 5), "x" * 16)

    def test_long_text_pauses_then_scrolls_then_wraps(self):
        m = Marquee()
        t = self.TEXT
        self.assertEqual(m.view(t, 1000), t[:16])
        self.assertEqual(m.view(t, 1000 + lb_lcd.PAUSE_MS - 1), t[:16])
        self.assertEqual(m.view(t, 1000 + lb_lcd.PAUSE_MS + lb_lcd.STEP_MS), t[1:17])
        full = len(t) + lb_lcd.GAP
        # the last character reaches the left edge, followed by the blank gap, then the restart
        w = m.view(t, 1000 + lb_lcd.PAUSE_MS + (len(t) - 1) * lb_lcd.STEP_MS)
        self.assertEqual(w, t[-1] + " " * lb_lcd.GAP + t[:16 - 1 - lb_lcd.GAP])
        period = lb_lcd.PAUSE_MS + full * lb_lcd.STEP_MS
        self.assertEqual(m.view(t, 1000 + period), t[:16])  # back at the start, paused again

    def test_new_text_restarts_the_scroll(self):
        m = Marquee()
        m.view(self.TEXT, 0)
        m.view(self.TEXT, 5000)
        other = "Totally different text that is long"
        self.assertEqual(m.view(other, 5100), other[:16])

    def test_every_window_is_16_wide(self):
        m = Marquee()
        for t in range(0, 40000, 137):
            self.assertEqual(len(m.view(self.TEXT, t)), 16)

    def test_survives_tick_wraparound(self):
        import lb_ticks
        m = Marquee()
        start = lb_ticks.PERIOD - 500
        self.assertEqual(m.view(self.TEXT, start), self.TEXT[:16])
        later = (start + 1200 + lb_lcd.STEP_MS * 3) % lb_ticks.PERIOD
        self.assertEqual(m.view(self.TEXT, later), self.TEXT[3:19])


class Screens(unittest.TestCase):
    def test_locked(self):
        r = Rig()
        l1, l2 = lines(r)
        sane(self, l1, l2)
        self.assertTrue(l1.startswith("\x01 Locked"))  # closed padlock, then the word
        self.assertEqual(l2.strip(), "Enter your combo")
        r.combo([0, 1, 2])
        self.assertEqual(lines(r)[1], "***" + " " * 13)  # dots only, never the directions

    def test_locked_with_a_waiting_host_request(self):
        r = Rig()
        r.session.request("SIGN", "USB", "Sign commit 4f2a9c")
        r.run(100)
        raw = raw_lines(r.ui.screen())
        self.assertEqual(raw[1], "Unlock to continue - Sign commit 4f2a9c")
        self.assertEqual(lines(r)[1], "Unlock to contin")
        self.assertEqual(lines(r, marquee=True)[1], "Unlock to contin")

    def test_idle(self):
        r = ready()
        l1, l2 = lines(r)
        sane(self, l1, l2)
        self.assertTrue(l1.startswith("\x00 \x04") and "L1" in l1)  # the libra sign stands in for the name
        self.assertEqual(l2.strip(), "D-pad: accounts")

    def test_accounts_and_cursor(self):
        r = ready()
        r.press("DOWN")
        l1, l2 = lines(r)
        self.assertTrue(l1.startswith("Accounts") and l1.endswith("1/4"))
        self.assertEqual(l2.strip(), ">GitHub alice")
        r.press("DOWN")
        r.press("DOWN")
        r.press("DOWN")
        l1, l2 = lines(r)
        self.assertTrue(l1.endswith("4/4"))
        self.assertTrue(l2.startswith(">Work Vault"))
        self.assertIn("[hold]", raw_lines(r.ui.screen())[1])

    def test_empty_accounts(self):
        r = Rig(seed=False, push_to_show=False)
        r.unlock()
        r.press("DOWN")
        self.assertEqual(lines(r)[1].strip(), "None: scan a QR")

    def test_code_screen(self):
        r = ready()
        r.press("DOWN")
        r.press("SELECT")
        l1, l2 = lines(r)
        sane(self, l1, l2)
        self.assertEqual(l1[3], " ")
        self.assertTrue(l1.rstrip().endswith("s"))
        self.assertEqual(l2.strip(), "alice")
        r.press("BACK")
        r.press("DOWN")
        r.press("DOWN")
        r.press("SELECT")
        self.assertTrue(lines(r)[0].rstrip().endswith("HOTP"))

    def test_confirm_and_hold_bar(self):
        r = ready()
        r.ui.scan(GOOD)
        l1, l2 = lines(r)
        self.assertEqual((l1.strip(), l2.strip()), ("Add account?", "Lab rfc"))
        r.down("PTT")
        r.run(300)
        l1, l2 = lines(r)
        self.assertTrue(l1.startswith("Hold "))
        self.assertIn("#", l1)
        self.assertIn(".", l1)
        self.assertEqual(l2.strip(), "Lab rfc")  # the request stays on screen while you hold
        sane(self, l1, l2)

    def test_host_request(self):
        r = ready()
        r.session.request("SIGN", "USB", "Sign commit 4f2a9c")
        r.run(100)
        l1, l2 = lines(r)
        self.assertTrue(l1.startswith("Approve?") and l1.rstrip().endswith("SIGN"))
        self.assertEqual(l2, "Sign commit 4f2a")
        self.assertEqual(raw_lines(r.ui.screen())[1], "Sign commit 4f2a9c")

    def test_reveal_and_combo_fallback(self):
        r = ready()
        r.press("DOWN")
        for _ in range(3):
            r.press("DOWN")
        r.press("SELECT")
        self.assertEqual(lines(r)[0].strip(), "Reveal code?")
        r.fp.mode = "nomatch"
        r.hold("PTT", 700)
        l1, l2 = lines(r)
        self.assertEqual((l1, l2.strip()), ("FP failed: combo", "Enter combo"))
        r.combo([0, 0])
        self.assertEqual(lines(r)[1], "**" + " " * 14)

    def test_toast_replaces_line_two(self):
        r = Rig()
        r.combo([3] * 10)
        r.press("SELECT")
        l1, l2 = lines(r)
        self.assertTrue(l2.startswith("Wrong combo. 9 le"[:16]))
        self.assertEqual(raw_lines(r.ui.screen())[1], "Wrong combo. 9 left")
        self.assertTrue(l1.startswith("\x01 Locked"))  # closed padlock, then the word

    def test_notice_wrapping(self):
        self.assertEqual(lb_lcd._wrap2("Approved"), ("Notice", "Approved"))
        self.assertEqual(lb_lcd._wrap2("Set the clock first"), ("Set the clock", "first"))
        a, b = lb_lcd._wrap2("Xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self.assertEqual((len(a), b[:3]), (16, "xxx"))
        r = ready()
        r.clock.trusted_flag = False
        r.press("DOWN")
        r.press("SELECT")
        self.assertEqual(tuple(x.strip() for x in lines(r)), ("Set the clock", "first"))

    def test_show_text_and_wiped(self):
        r = ready()
        r.ui.scan(b"https://example.com/pay?to=attacker")
        l1, l2 = lines(r)
        self.assertEqual(l1.strip(), "Unknown QR")
        self.assertEqual(l2, "https://example.")
        w = Rig()
        for _ in range(10):
            w.combo([3] * 10)
            w.press("SELECT")
            w.clock.advance(4000000)
        self.assertEqual(tuple(x.strip() for x in lines(w)), ("WIPED", "Restore backup"))

    def test_unicode_account_is_shown_safely(self):
        sc = {"id": "TOTPCode", "title": "x", "lines": [], "hints": {}, "hold": None, "toast": None,
              "status": {"time": "12:00", "level": "L1", "locked": False},
              "body": {"code": "123 456", "remaining": 9, "account": "Jürgen ‮"}}
        l1, l2 = LcdView(marquee=False).lines(sc, 0)
        self.assertEqual(l2.strip(), "J?rgen ?")

    def test_every_state_fits_the_display(self):
        r = Rig()
        seen = set()
        script = [
            lambda: r.combo([0, 1]), lambda: r.press("BACK"), lambda: r.unlock(),
            lambda: r.press("SELECT"), lambda: r.press("DOWN"), lambda: r.press("SELECT"),
            lambda: r.press("BACK"), lambda: r.press("BACK"), lambda: r.ui.scan(GOOD),
            lambda: r.down("PTT"), lambda: r.run(300), lambda: r.up("PTT"), lambda: r.run(100),
            lambda: r.press("BACK"), lambda: r.ui.scan(b"junk"), lambda: r.press("BACK"),
            lambda: r.ui.scan(b"otpauth://totp/a?x=1"), lambda: r.run(3500),
            lambda: r.session.request("DECRYPT", "USB", "Decrypt payroll.xlsx.gpg " + "x" * 60),
            lambda: r.run(200), lambda: r.press("PTT", 100), lambda: r.run(31000),
        ]
        for step in script:
            step()
            for marquee in (False, True):
                sc = r.ui.screen()
                seen.add(sc["id"])
                l1, l2 = LcdView(marquee=marquee).lines(sc, r.clock.ticks())
                sane(self, l1, l2)
        self.assertGreaterEqual(len(seen), 6)


class Symbols(unittest.TestCase):
    CODES = {"libra": "\x00", "lock": "\x01", "link": "\x02", "bt": "\x03", "unlock": "\x04"}

    def idle(self, usb=False, ble=False):
        r = Rig()
        r.unlock()
        r.run(100)
        r.usb = usb
        r.ble = ble
        r.run(40)
        return LcdView(marquee=False).lines(r.ui.screen(), r.clock.ticks())

    def test_idle_shows_the_libra_sign_and_an_open_padlock(self):
        l1, l2 = self.idle()
        self.assertTrue(l1.startswith("\x00 \x04"))
        self.assertNotIn("Libra", l1)
        self.assertNotIn("\x02", l1)  # not connected
        self.assertNotIn("\x03", l1)  # no BLE
        self.assertEqual(len(l1), 16)

    def test_a_chain_link_while_usb_is_plugged_in(self):
        l1, _ = self.idle(usb=True)
        self.assertTrue(l1.startswith("\x00 \x04 \x02"))
        self.assertNotIn("\x03", l1)

    def test_bluetooth_while_ble_is_active(self):
        l1, _ = self.idle(ble=True)
        self.assertTrue(l1.startswith("\x00 \x04 \x03"))
        self.assertNotIn("\x02", l1)

    def test_every_symbol_at_once_still_leaves_the_level_and_time(self):
        l1, _ = self.idle(usb=True, ble=True)
        self.assertTrue(l1.startswith("\x00 \x04 \x02 \x03"))
        self.assertEqual(len(l1), 16)
        self.assertIn("L1", l1)
        self.assertRegex(l1[-5:], r"\d\d:\d\d") if hasattr(self, "assertRegex") else None

    def test_the_locked_screen_shows_the_closed_padlock(self):
        r = Rig()
        r.run(100)
        l1, _ = LcdView(marquee=False).lines(r.ui.screen(), r.clock.ticks())
        self.assertTrue(l1.startswith("\x01 Locked"))

    def test_only_idle_and_locked_use_them_and_lines_stay_16_wide(self):
        r = Rig()
        r.unlock()
        r.usb = True
        r.ble = True
        r.run(100)
        for screen_cmd in (lambda: None, lambda: r.press("DOWN"), lambda: r.press("BACK"), lambda: r.press("SELECT")):
            screen_cmd()
            r.run(100)
            for line in LcdView(marquee=False).lines(r.ui.screen(), r.clock.ticks()):
                self.assertEqual(len(line), 16)

    def test_glyphs_are_valid_5x8_bitmaps(self):
        self.assertEqual(len(lb_lcd.GLYPHS), 5)
        self.assertEqual(len(set(lb_lcd.GLYPHS)), 5)  # all different
        for g in lb_lcd.GLYPHS:
            self.assertEqual(len(g), 8)
            self.assertTrue(all(0 <= row < 32 for row in g))
            self.assertTrue(any(g))

    def test_each_symbol_maps_to_its_slot_and_back(self):
        syms = (lb_lcd.SYM_LIBRA, lb_lcd.SYM_LOCK, lb_lcd.SYM_LINK, lb_lcd.SYM_BT, lb_lcd.SYM_UNLOCK)
        for i, sym in enumerate(syms):
            self.assertEqual(fit(sym)[0], chr(i))
            self.assertEqual(lb_lcd.printable(chr(i)), sym)
        self.assertEqual(fit("\x05")[0], "?")  # anything else stays an error mark

    def test_the_status_carries_usb_and_ble(self):
        r = Rig()
        r.run(20)
        st = r.ui.screen()["status"]
        self.assertFalse(st["usb"] or st["ble"])
        r.usb = True
        r.ble = True
        st = r.ui.screen()["status"]
        self.assertTrue(st["usb"] and st["ble"])

    def test_the_shell_fallback_prints_the_real_symbols(self):
        import hw_lcd
        said = []
        d = hw_lcd.TextDisplay(said.append)
        d.show(lb_lcd.fit(lb_lcd.SYM_LIBRA + " " + lb_lcd.SYM_UNLOCK + " " + lb_lcd.SYM_LINK + " " + lb_lcd.SYM_BT),
               lb_lcd.fit("x"))
        self.assertIn(chr(0x264E) + " " + chr(0x1F513) + " " + chr(0x1F517) + " " + chr(0x16D2), said[0])


if __name__ == "__main__":
    unittest.main()
