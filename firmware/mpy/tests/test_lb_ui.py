import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_fakes
import lb_oath
import lb_session as ls
import lb_ui
from lb_rig import Rig

GOOD = b"otpauth://totp/Lab:rfc?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&digits=8&issuer=Lab"
WRONG = [3] * 10
try:
    import json
except ImportError:
    json = None


def shot(r):
    """Every screen description must serialise (the browser renderer receives it as JSON)."""
    s = r.ui.screen()
    if json:
        json.dumps(s)
    return s


def ready(**kw):
    kw.setdefault("push_to_show", False)  # most tests are about other things; the device default is ON
    r = Rig(**kw)
    r.unlock()
    assert r.id == "Idle", r.id
    return r


class Lock(unittest.TestCase):
    def test_boots_locked_and_dots_hide_directions(self):
        r = Rig()
        s = shot(r)
        self.assertEqual(s["id"], "Locked")
        self.assertTrue(s["status"]["locked"])
        r.combo([0, 1, 2])
        s = shot(r)
        self.assertEqual(s["body"]["dots"], 3)
        self.assertNotIn("UP", repr(s["body"]))
        r.press("BACK")
        self.assertEqual(shot(r)["body"]["dots"], 0)

    def test_unlock_to_idle(self):
        r = Rig()
        r.unlock()
        s = shot(r)
        self.assertEqual((s["id"], s["status"]["locked"]), ("Idle", False))

    def test_wrong_combo_toast_and_keeps_typing(self):
        r = Rig()
        r.combo(WRONG)
        r.press("SELECT")
        s = shot(r)
        self.assertEqual(s["id"], "Locked")  # no blocking dialog
        self.assertIn("9 left", s["toast"])
        r.combo([0, 1])
        self.assertEqual(shot(r)["body"]["dots"], 2)  # typing is not blocked by the message
        self.assertEqual(r.haptic.last, "error")

    def test_short_and_long_combos(self):
        r = Rig()
        r.combo([0, 1, 2])
        r.press("SELECT")
        self.assertIn("8 to 16", shot(r)["toast"])
        r.combo([0] * 20)
        self.assertEqual(shot(r)["body"]["dots"], 16)  # extra presses ignored

    def test_delay_shown_and_enforced(self):
        r = Rig()
        for _ in range(4):
            r.combo(WRONG)
            r.press("SELECT")
        self.assertIn("Wait 5 s", shot(r)["toast"])
        r.run(3000)
        r.unlock()
        self.assertEqual(r.id, "Locked")
        self.assertIn("Wait", shot(r)["toast"])
        r.run(5000)
        r.unlock()
        self.assertEqual(r.id, "Idle")

    def test_wipe_screen_and_dead_buttons(self):
        r = Rig()
        for _ in range(10):
            r.combo(WRONG)
            r.press("SELECT")
            r.clock.advance(4000000)
        self.assertEqual(shot(r)["id"], "Wiped")
        r.unlock()
        self.assertEqual(r.id, "Wiped")

    def test_idle_timeout_and_long_back(self):
        r = ready()
        r.run(59000)
        self.assertEqual(r.id, "Idle")
        r.run(2000)
        self.assertEqual(r.id, "Locked")
        r.unlock()
        r.press("BACK")
        self.assertEqual(r.id, "Idle")  # a short Back on Idle does nothing
        r.hold("BACK", 1100)
        self.assertEqual(r.id, "Locked")

    def test_activity_postpones_lock(self):
        r = ready()
        for _ in range(4):
            r.run(40000)
            r.press("UP")
            r.press("BACK")
        self.assertNotEqual(r.id, "Locked")

    def test_power_cycle_keeps_lockout(self):
        r = Rig()
        for _ in range(5):
            r.combo(WRONG)
            r.press("SELECT")
            r.run(40000)
        r.boot()
        self.assertEqual(r.id, "Locked")
        r.unlock()
        self.assertEqual(r.id, "Locked")  # the pending delay survives the reboot
        self.assertIn("Wait", shot(r)["toast"])


class Home(unittest.TestCase):
    def test_tap_shows_qr_and_back_returns(self):
        r = ready()
        r.press("PTT", 100)
        self.assertEqual(shot(r)["id"], "ShowQR")
        r.press("BACK")
        self.assertEqual(r.id, "Idle")

    def test_long_ptt_on_idle_does_nothing(self):
        r = ready()
        r.hold("PTT", 2000)
        self.assertEqual(r.id, "Idle")

    def test_showqr_times_out(self):
        r = ready()
        r.press("PTT", 100)
        r.run(29000)
        self.assertEqual(r.id, "ShowQR")
        r.session.activity()  # keep the idle lock out of the way; only the QR timeout is tested
        r.run(2000)
        self.assertEqual(r.id, "Idle")

    def test_any_dpad_opens_accounts_and_select_opens_settings(self):
        for b in ("UP", "DOWN", "LEFT", "RIGHT"):
            r = ready()
            r.press(b)
            self.assertEqual(r.id, "Accounts", b)
        r = ready()
        r.press("SELECT")
        self.assertEqual(r.id, "Settings")

    def test_status_bar(self):
        r = ready()
        st = shot(r)["status"]
        self.assertEqual(st["level"], "L1")
        self.assertEqual((len(st["time"]), st["time"][2]), (5, ":"))
        r.clock.trusted_flag = False
        self.assertEqual(shot(r)["status"]["time"], "--:--")


class Accounts(unittest.TestCase):
    def test_list_cursor_and_clamp(self):
        r = ready()
        r.press("DOWN")
        s = shot(r)
        self.assertEqual((s["body"]["total"], s["body"]["cursor"]), (4, 0))
        self.assertEqual(s["body"]["rows"][0]["text"], "GitHub alice")
        r.press("UP")
        self.assertEqual(shot(r)["body"]["cursor"], 0)
        for _ in range(10):
            r.press("DOWN")
        self.assertEqual(shot(r)["body"]["cursor"], 3)
        self.assertTrue(shot(r)["body"]["rows"][3]["hold"])

    def test_empty_list(self):
        r = Rig(seed=False, push_to_show=False)
        r.unlock()
        r.press("DOWN")
        s = shot(r)
        self.assertEqual(s["body"]["total"], 0)
        self.assertIn("No accounts yet", s["lines"])
        r.press("SELECT")  # nothing to open
        self.assertEqual(r.id, "Accounts")

    def test_long_list_scrolls(self):
        r = Rig(seed=False, push_to_show=False)
        for i in range(10):
            r.oath.add(lb_oath.Entry("a%d" % i, "JBSWY3DPEHPK3PXP"), approved=True)
        r.unlock()
        r.press("DOWN")
        for _ in range(8):
            r.press("DOWN")
        s = shot(r)
        self.assertEqual(len(s["body"]["rows"]), 6)
        self.assertEqual(s["body"]["rows"][s["body"]["cursor"]]["text"], "a8")

    def test_totp_code_ring_and_rollover(self):
        r = ready()
        r.press("DOWN")
        r.press("SELECT")
        s = shot(r)
        self.assertEqual(s["id"], "TOTPCode")
        self.assertEqual(s["title"], "GitHub")
        b = s["body"]
        self.assertEqual(len(b["code"].replace(" ", "")), 6)
        self.assertEqual(b["code"][3], " ")
        self.assertTrue(0 < b["remaining"] <= 30)
        self.assertEqual(b["ring"], b["remaining"] * 1000 // 30)
        first = b["code"]
        r.run(31000)
        s2 = shot(r)
        self.assertEqual(s2["id"], "TOTPCode")
        self.assertNotEqual(s2["body"]["code"], first)  # rolled over without leaving the screen

    def test_period_60_and_8_digits(self):
        r = ready()
        r.press("DOWN")
        r.press("DOWN")
        r.press("SELECT")
        b = shot(r)["body"]
        self.assertEqual(len(b["code"].replace(" ", "")), 8)
        self.assertEqual(b["ring"], b["remaining"] * 1000 // 60)

    def test_hotp_advances_each_open(self):
        r = ready()
        r.press("DOWN")
        r.press("DOWN")
        r.press("DOWN")
        codes = []
        for _ in range(3):
            r.press("SELECT")
            codes.append(shot(r)["body"]["code"])
            self.assertIsNone(shot(r)["body"]["remaining"])
            r.press("BACK")
        self.assertEqual(len(set(codes)), 3)
        self.assertEqual(r.store.rec[3]["counter"], 3)

    def test_cursor_returns_to_the_account_you_opened(self):
        r = ready()
        r.press("DOWN")
        r.press("DOWN")
        r.press("DOWN")
        r.press("SELECT")
        r.press("BACK")
        self.assertEqual(shot(r)["body"]["cursor"], 2)
        r.press("SELECT")
        r.press("BACK")
        self.assertEqual(shot(r)["body"]["cursor"], 2)

    def test_back_levels(self):
        r = ready()
        r.press("DOWN")
        r.press("SELECT")
        r.press("BACK")
        self.assertEqual(r.id, "Accounts")
        r.press("BACK")
        self.assertEqual(r.id, "Idle")

    def test_untrusted_clock_notice_only_for_totp(self):
        r = ready()
        r.clock.trusted_flag = False
        r.press("DOWN")
        r.press("SELECT")
        s = shot(r)
        self.assertEqual((s["id"], s["lines"]), ("Notice", ["Set the clock first"]))
        r.press("BACK")
        self.assertEqual(r.id, "Accounts")
        r.press("DOWN")
        r.press("DOWN")
        r.press("SELECT")
        self.assertEqual(r.id, "TOTPCode")  # HOTP needs no clock

    def test_notice_dismiss_and_timeout(self):
        r = ready()
        r.clock.trusted_flag = False
        r.press("DOWN")
        r.press("SELECT")
        r.press("SELECT")
        self.assertEqual(r.id, "Accounts")
        r.press("SELECT")
        self.assertEqual(r.id, "Notice")
        r.run(3100)
        self.assertEqual(r.id, "Accounts")


class Reveal(unittest.TestCase):
    def open_reveal(self, r):
        r.press("DOWN")
        for _ in range(3):
            r.press("DOWN")
        r.press("SELECT")

    def test_needs_a_hold(self):
        r = ready()
        self.open_reveal(r)
        s = shot(r)
        self.assertEqual(s["id"], "RevealPrompt")
        self.assertEqual(s["hints"]["ptt"], "Hold: reveal")
        r.hold("PTT", 300)
        self.assertEqual(r.id, "RevealPrompt")
        self.assertEqual(shot(r)["toast"], "Keep holding to approve")
        r.down("PTT")
        r.run(600)
        s = shot(r)
        self.assertEqual(s["id"], "TOTPCode")  # visible while PTT is still held
        self.assertEqual(s["title"], "Work Vault")

    def test_progress_ring_while_holding(self):
        r = ready()
        self.open_reveal(r)
        r.down("PTT")
        r.run(250)
        p = shot(r)["hold"]
        self.assertTrue(0 < p < 1000, p)
        r.run(400)
        self.assertEqual(shot(r)["id"], "TOTPCode")

    def test_back_cancels_the_reveal(self):
        r = ready()
        self.open_reveal(r)
        r.press("BACK")
        self.assertEqual(r.id, "Accounts")
        self.assertIsNone(r.session.pending())

    def test_code_keeps_rolling_over_while_held(self):
        r = ready()
        self.open_reveal(r)
        r.down("PTT")
        r.run(600)
        c1 = shot(r)["body"]["code"]
        r.run(31000)
        self.assertEqual(shot(r)["id"], "TOTPCode")
        self.assertNotEqual(shot(r)["body"]["code"], c1)
        r.up("PTT")


def add_protected_hotp(r):
    r.oath.add(lb_oath.Entry("safe", "JBSWY3DPEHPK3PXP", issuer="Safe", type=lb_oath.HOTP,
                             reveal_requires_hold=True), approved=True)


def open_protected(r, index):
    r.press("DOWN")
    for _ in range(index):
        r.press("DOWN")
    r.press("SELECT")


def reveal(r, ms=600):
    r.down("PTT")
    r.run(ms)


class RevealHides(unittest.TestCase):
    """A hold-to-reveal code is visible only while PTT is held."""

    def test_visible_while_held_hidden_on_release(self):
        r = ready()
        open_protected(r, 3)
        reveal(r)
        s = shot(r)
        self.assertEqual(s["id"], "TOTPCode")
        digits = s["body"]["code"].replace(" ", "")
        self.assertEqual(s["hints"]["ptt"], "Release: hide")
        r.up("PTT")
        r.run(40)
        h = shot(r)
        self.assertEqual(h["id"], "RevealPrompt")
        self.assertIn("Code hidden", h["toast"])
        self.assertNotIn(digits, repr(h))  # nothing of the code is left in the screen description
        self.assertNotIn(digits[:3] + " " + digits[3:], repr(h))
        self.assertIsNotNone(r.session.pending())  # a fresh reveal request is waiting

    def test_showing_it_again_needs_a_real_hold(self):
        r = ready()
        open_protected(r, 3)
        reveal(r)
        r.up("PTT")
        r.run(40)
        r.hold("PTT", 150)  # a tap does nothing
        self.assertEqual(r.id, "RevealPrompt")
        self.assertIn("Keep holding", shot(r)["toast"])
        reveal(r)
        self.assertEqual(r.id, "TOTPCode")
        r.up("PTT")
        r.run(40)
        self.assertEqual(r.id, "RevealPrompt")

    def test_hotp_shows_the_same_code_and_burns_one_counter(self):
        r = ready()
        add_protected_hotp(r)
        open_protected(r, 4)
        reveal(r)
        first = shot(r)["body"]["code"]
        self.assertEqual(r.store.rec[5]["counter"], 1)
        r.up("PTT")
        r.run(40)
        reveal(r)
        self.assertEqual(shot(r)["body"]["code"], first)  # same code, not the next one
        self.assertEqual(r.store.rec[5]["counter"], 1)
        r.up("PTT")
        r.run(40)
        reveal(r)
        self.assertEqual(shot(r)["body"]["code"], first)
        self.assertEqual(r.store.rec[5]["counter"], 1)

    def test_leaving_the_account_forgets_the_hotp_code(self):
        r = ready()
        add_protected_hotp(r)
        open_protected(r, 4)
        reveal(r)
        first = shot(r)["body"]["code"]
        r.up("PTT")
        r.run(40)
        r.press("BACK")  # leave the account
        r.press("SELECT")  # open it again
        reveal(r)
        self.assertNotEqual(shot(r)["body"]["code"], first)  # a new visit uses the next counter
        self.assertEqual(r.store.rec[5]["counter"], 2)

    def test_lock_forgets_the_hotp_code(self):
        r = ready()
        add_protected_hotp(r)
        open_protected(r, 4)
        reveal(r)
        first = shot(r)["body"]["code"]
        r.up("PTT")
        r.run(40)
        r.session.lock("BACK")
        r.run(100)
        r.unlock()
        open_protected(r, 4)
        reveal(r)
        self.assertNotEqual(shot(r)["body"]["code"], first)
        self.assertEqual(r.store.rec[5]["counter"], 2)  # the lock forgot the old code

    def test_hiding_drops_the_code_from_memory_not_just_from_the_screen(self):
        r = ready()
        open_protected(r, 3)
        reveal(r)
        digits = r.ui.screen()["body"]["code"].replace(" ", "")
        r.up("PTT")
        r.run(40)
        self.assertNotIn("code", r.ui._d)
        self.assertNotIn(digits, repr(r.ui._d))
        self.assertNotIn(digits, repr(r.ui.screen()))

    def test_locking_drops_the_stashed_hotp_code_from_memory(self):
        r = ready()
        add_protected_hotp(r)
        open_protected(r, 4)
        reveal(r)
        digits = r.ui.screen()["body"]["code"].replace(" ", "")  # the screen groups digits with a space
        self.assertIsNotNone(r.ui._stash)
        r.up("PTT")
        r.run(40)
        self.assertEqual(r.ui._stash[1], digits)  # kept while the account stays open
        r.session.lock("IDLE")
        r.run(100)
        self.assertIsNone(r.ui._stash)  # gone the moment the device locks

    def test_combo_approval_shows_then_hides_by_itself(self):
        r = ready()
        r.fp.mode = "nomatch"
        open_protected(r, 3)
        r.hold("PTT", 700)
        self.assertEqual(r.id, "ComboApprove")
        r.combo(lb_fakes.DEMO_COMBO)
        r.press("SELECT")
        self.assertEqual(r.id, "TOTPCode")  # no PTT is held, so it cannot be released
        for _ in range(7):
            r.session.activity()
            r.run(1000)
        self.assertEqual(r.id, "TOTPCode")
        for _ in range(2):
            r.session.activity()
            r.run(1000)
        self.assertEqual(r.id, "RevealPrompt")

    def test_other_accounts_are_unaffected(self):
        r = ready()
        r.press("DOWN")
        r.press("SELECT")  # GitHub, not protected
        self.assertEqual(r.id, "TOTPCode")
        self.assertEqual(shot(r)["hints"]["ptt"], "")
        r.hold("PTT", 1000)
        self.assertEqual(r.id, "TOTPCode")
        self.assertEqual(len(shot(r)["body"]["code"].replace(" ", "")), 6)
        r.run(10000)
        self.assertEqual(r.id, "TOTPCode")

    def test_hide_also_when_back_is_not_pressed_and_lcd_shows_no_code(self):
        r = ready()
        open_protected(r, 3)
        reveal(r)
        digits = shot(r)["body"]["code"].replace(" ", "")
        import lb_lcd
        shown = " ".join(lb_lcd.LcdView(marquee=False).lines(r.ui.screen(), r.clock.ticks()))
        self.assertIn(digits[:3], shown)  # visible while held
        r.up("PTT")
        r.run(40)
        shown = " ".join(lb_lcd.LcdView(marquee=False).lines(r.ui.screen(), r.clock.ticks()))
        self.assertNotIn(digits[:3] + " " + digits[3:], shown)
        self.assertNotIn(digits, shown)

    def test_a_pocket_press_cannot_reveal(self):
        r = ready()
        open_protected(r, 3)
        r.hold("PTT", 300)  # too short
        self.assertEqual(r.id, "RevealPrompt")
        self.assertNotIn("code", shot(r)["body"])


class Enrol(unittest.TestCase):
    def test_scan_confirm_hold_adds(self):
        r = ready()
        self.assertTrue(r.ui.scan(GOOD))
        s = shot(r)
        self.assertEqual(s["id"], "ConfirmOTP")
        self.assertEqual(s["lines"][:2], ["Lab", "rfc"])
        self.assertIn("SHA1 8 digits", s["lines"][2])
        self.assertEqual(len(r.oath.list()), 4)  # nothing stored before approval
        r.hold("PTT", 600)
        s = shot(r)
        self.assertEqual((s["id"], s["lines"]), ("Notice", ["Added rfc"]))
        self.assertEqual(len(r.oath.list()), 5)
        r.run(3100)
        s = shot(r)
        self.assertEqual(s["id"], "Accounts")
        self.assertEqual(s["body"]["rows"][s["body"]["cursor"]]["text"], "Lab rfc")  # lands on the new one

    def test_early_release_adds_nothing(self):
        r = ready()
        r.ui.scan(GOOD)
        r.hold("PTT", 300)
        self.assertEqual(r.id, "ConfirmOTP")
        self.assertEqual(len(r.oath.list()), 4)

    def test_back_cancels(self):
        r = ready()
        r.ui.scan(GOOD)
        r.press("BACK")
        self.assertEqual(r.id, "Idle")
        self.assertEqual(len(r.oath.list()), 4)
        self.assertIsNone(r.session.pending())

    def test_scan_from_accounts_screen_too(self):
        r = ready()
        r.press("DOWN")
        self.assertTrue(r.ui.scan(GOOD))
        self.assertEqual(r.id, "ConfirmOTP")

    def test_scan_ignored_when_locked_or_busy(self):
        r = Rig()
        self.assertFalse(r.ui.scan(GOOD))
        self.assertEqual(r.id, "Locked")
        r2 = ready()
        r2.press("PTT", 100)
        self.assertFalse(r2.ui.scan(GOOD))
        self.assertEqual(r2.id, "ShowQR")

    def test_bad_otpauth_is_a_notice(self):
        r = ready()
        r.ui.scan(b"otpauth://totp/a?secret=JBSWY3DPEHPK3PXP&image=http://evil")
        s = shot(r)
        self.assertEqual(s["id"], "Notice")
        self.assertIn("Bad OTP code", s["lines"][0])
        self.assertEqual(r.haptic.last, "error")

    def test_unknown_qr_shows_source_never_acts(self):
        r = ready()
        r.ui.scan(b"https://evil.example/\x1b[31mhi\n\xff")
        s = shot(r)
        self.assertEqual(s["id"], "ShowText")
        self.assertEqual(s["lines"][1], "https://evil.example/?[31mhi??")
        self.assertIsNone(r.session.pending())
        r.press("BACK")
        self.assertEqual(r.id, "Idle")

    def test_long_unknown_text_is_cut(self):
        r = ready()
        r.ui.scan(b"x" * 400)
        t = shot(r)["lines"][1]
        self.assertTrue(len(t) < 170 and t.endswith("..."))

    def test_lookalike_name_rejected_before_confirm(self):
        r = ready()
        r.ui.scan(b"otpauth://totp/bob%E2%80%AEevil?secret=JBSWY3DPEHPK3PXP")
        s = shot(r)
        self.assertEqual(s["id"], "Notice")
        self.assertIn("Rejected", s["lines"][0])
        self.assertEqual(len(r.oath.list()), 4)

    def test_duplicate(self):
        r = ready()
        r.ui.scan(b"otpauth://totp/GitHub:alice?secret=JBSWY3DPEHPK3PXP&issuer=GitHub")
        self.assertEqual(shot(r)["lines"], ["Already added"])

    def test_fingerprint_failure_falls_back_to_combo(self):
        r = ready()
        r.fp.mode = "nomatch"
        r.ui.scan(GOOD)
        r.hold("PTT", 600)
        s = shot(r)
        self.assertEqual(s["id"], "ComboApprove")
        r.combo(WRONG)
        r.press("SELECT")
        s = shot(r)
        self.assertEqual(s["id"], "ComboApprove")  # stays; message is a toast
        self.assertIn("left", s["toast"])
        self.assertEqual(len(r.oath.list()), 4)
        r.run(1000)
        r.combo(lb_fakes.DEMO_COMBO)
        r.press("SELECT")
        self.assertEqual(shot(r)["lines"], ["Added rfc"])
        self.assertEqual(len(r.oath.list()), 5)

    def test_fingerprint_error_also_falls_back_and_reveal_works_with_combo(self):
        r = ready()
        r.fp.mode = "error"
        r.press("DOWN")
        for _ in range(3):
            r.press("DOWN")
        r.press("SELECT")
        r.hold("PTT", 600)
        self.assertEqual(r.id, "ComboApprove")
        r.combo(lb_fakes.DEMO_COMBO)
        r.press("SELECT")
        self.assertEqual(r.id, "TOTPCode")

    def test_combo_fallback_counts_toward_wipe(self):
        r = ready()
        r.fp.mode = "nomatch"
        r.ui.scan(GOOD)
        r.hold("PTT", 600)
        for _ in range(10):
            r.combo(WRONG)
            r.press("SELECT")
            r.clock.advance(4000000)
            r.ui.tick()
        self.assertEqual(r.id, "Wiped")


class HostRequests(unittest.TestCase):
    def test_request_while_locked_then_unlock_then_approve(self):
        r = Rig()
        rid = r.session.request("SIGN", "USB", "Sign commit 4f2a9c")
        r.run(100)
        s = shot(r)
        self.assertEqual(s["id"], "Locked")
        self.assertEqual(s["lines"], ["Unlock to continue", "Sign commit 4f2a9c"])
        r.unlock()
        s = shot(r)
        self.assertEqual(s["id"], "HostRequest")
        self.assertIn("computer", s["lines"][0])
        self.assertIsNone(r.session.decision(rid))  # unlocking is not approving
        r.hold("PTT", 1700)
        self.assertEqual(r.session.decision(rid), ls.APPROVED)
        self.assertEqual(shot(r)["lines"], ["Approved"])

    def test_sign_needs_the_long_hold(self):
        r = ready()
        rid = r.session.request("SIGN", "USB", "Sign x")
        r.run(100)
        r.hold("PTT", 1000)
        self.assertIsNone(r.session.decision(rid))
        self.assertIn("Keep holding", shot(r)["toast"])
        r.hold("PTT", 1700)
        self.assertEqual(r.session.decision(rid), ls.APPROVED)

    def test_login_is_the_short_hold(self):
        r = ready()
        rid = r.session.request("AUTH", "USB", "Login to git.example")
        r.run(100)
        r.hold("PTT", 600)
        self.assertEqual(r.session.decision(rid), ls.APPROVED)

    def test_deny_with_back(self):
        r = ready()
        rid = r.session.request("SIGN", "USB", "Sign x")
        r.run(100)
        r.press("BACK")
        self.assertEqual(r.session.decision(rid), ls.CANCELLED)
        self.assertEqual(r.id, "Idle")

    def test_swapped_request_resets_the_hold(self):
        r = ready()
        a = r.session.request("SIGN", "USB", "Sign A")
        r.run(100)
        r.down("PTT")
        r.run(1000)
        b = r.session.request("SIGN", "USB", "Sign B")
        r.run(100)
        s = shot(r)
        self.assertIn("Sign B", s["lines"][2])
        self.assertIn("Request changed", s["toast"])
        self.assertEqual(r.session.decision(a), ls.CANCELLED)
        r.run(5000)  # holding on through the swap must never approve B
        self.assertIsNone(r.session.decision(b))
        r.up("PTT")
        r.run(100)
        r.hold("PTT", 1700)
        self.assertEqual(r.session.decision(b), ls.APPROVED)

    def test_request_expires_after_30s(self):
        r = ready()
        rid = r.session.request("SIGN", "USB", "Sign x")
        for _ in range(31):
            r.session.activity()  # the user is present, so the idle lock stays off
            r.run(1000)
        self.assertEqual(r.session.decision(rid), ls.EXPIRED)
        self.assertEqual(shot(r)["lines"], ["Request expired"])

    def test_host_request_preempts_local_confirm(self):
        r = ready()
        r.ui.scan(GOOD)
        self.assertEqual(r.id, "ConfirmOTP")
        rid = r.session.request("SIGN", "USB", "Sign x")
        r.run(100)
        self.assertEqual(r.id, "HostRequest")
        self.assertEqual(len(r.oath.list()), 4)
        self.assertIn("Request changed", shot(r)["toast"])

    def test_lock_during_request_returns_to_locked(self):
        r = ready()
        r.session.request("SIGN", "USB", "Sign x")
        r.run(100)
        r.hold("BACK", 1100)  # a long Back locks, even mid-request
        r.run(100)
        self.assertEqual(r.id, "Locked")


class Hardening(unittest.TestCase):
    def test_pocket_press_into_request_screen_never_approves(self):
        r = ready()
        r.down("PTT")           # already down when the request arrives
        r.run(200)
        rid = r.session.request("SIGN", "USB", "Sign x")
        r.run(5000)
        self.assertIsNone(r.session.decision(rid))
        r.up("PTT")
        r.run(100)
        r.hold("PTT", 1700)
        self.assertEqual(r.session.decision(rid), ls.APPROVED)

    def test_ptt_held_across_lock_and_unlock(self):
        r = ready()
        r.down("PTT")
        r.session.lock("IDLE")
        r.run(100)
        r.unlock()
        rid = r.session.request("SIGN", "USB", "Sign x")
        r.run(5000)
        self.assertIsNone(r.session.decision(rid))

    def test_no_secret_in_any_screen(self):
        r = ready()
        seen = []
        secrets = ["JBSWY3DPEHPK3PXP", "GEZDGNBVGY3TQOJQ", "4a42535759"]
        steps = [lambda: r.press("SELECT"), lambda: r.press("SELECT"), lambda: r.press("BACK"),
                 lambda: r.ui.scan(GOOD), lambda: r.press("BACK"),
                 lambda: r.ui.scan(b"junk"), lambda: r.press("BACK")]
        for f in steps:
            f()
            seen.append(repr(shot(r)))
        for blob in seen:
            for sec in secrets:
                self.assertNotIn(sec, blob)
        self.assertNotIn(repr(r.oath._entries[1]._secret), "".join(seen))

    def test_unknown_button_rejected(self):
        r = ready()
        with self.assertRaises(ValueError):
            r.ui.button("POWER", True)

    def test_trail_is_bounded(self):
        r = ready()
        for _ in range(400):
            r.press("UP")
            r.press("BACK")
        self.assertLessEqual(len(r.ui.trail), lb_ui.TRAIL_MAX)

    def test_haptic_commit_pulse(self):
        r = ready()
        r.ui.scan(GOOD)
        before = r.haptic.seq
        r.hold("PTT", 600)
        self.assertGreater(r.haptic.seq, before)
        self.assertEqual(shot(r)["haptic"]["kind"], "commit")


if __name__ == "__main__":
    unittest.main()
