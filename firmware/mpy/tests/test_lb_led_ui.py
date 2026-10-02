import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_fakes
import lb_led
from lb_rig import Rig

GOOD = b"otpauth://totp/Lab:rfc?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&digits=8&issuer=Lab"
WRONG = [3] * 10


def dom(c):
    return "RGB"[c.index(max(c))] if max(c) else "-"


def trace(r, ms, step=20):
    """The LED colour sampled after every 20 ms step."""
    out = []
    for _ in range(max(1, ms // step)):
        r.run(step, step)
        out.append(r.led_color())
    return out


def kinds(r):
    return [x for _, k, x in r.ui.trail if k == "haptic"]


def ready(**kw):
    kw.setdefault("push_to_show", False)
    r = Rig(**kw)
    r.unlock()
    r.run(100)
    return r


class Events(unittest.TestCase):
    def test_tap_on_idle(self):
        r = ready()
        r.press("PTT", 100)
        self.assertEqual(r.haptic.last, "tap")

    def test_a_long_press_on_idle_is_not_a_tap(self):
        r = ready()
        before = kinds(r)
        r.hold("PTT", 1500)
        self.assertEqual(kinds(r), before)

    def test_early_release_of_a_hold_is_an_abort(self):
        r = ready()
        r.ui.scan(GOOD)
        r.hold("PTT", 250)
        self.assertEqual(r.haptic.last, "abort")

    def test_a_completed_hold_ends_on_commit_not_success(self):
        r = ready()
        r.ui.scan(GOOD)
        r.hold("PTT", 700)
        self.assertEqual(r.haptic.last, "commit")  # one flash, not commit and then success on top

    def test_combo_approval_says_success(self):
        r = ready()
        r.fp.mode = "nomatch"
        r.ui.scan(GOOD)
        r.hold("PTT", 700)
        r.combo(lb_fakes.DEMO_COMBO)
        r.press("SELECT")
        self.assertEqual(r.haptic.last, "success")

    def test_wrong_combo_is_an_error(self):
        r = Rig()
        r.combo(WRONG)
        r.press("SELECT")
        self.assertEqual(r.haptic.last, "error")

    def test_a_bad_qr_is_an_error(self):
        r = ready()
        r.ui.scan(b"otpauth://totp/a?x=1")
        self.assertEqual(r.haptic.last, "error")

    def test_a_host_request_notifies(self):
        r = ready()
        r.session.request("SIGN", "USB", "Sign x")
        r.run(100)
        self.assertEqual(r.haptic.last, "notify")

    def test_zone_saved_push_on_and_a_dropped_account_say_success(self):
        r = ready()
        r.press("SELECT")
        r.press("DOWN")
        r.press("SELECT")  # Time zone
        r.press("RIGHT")
        r.press("SELECT")
        self.assertEqual(r.haptic.last, "success")
        r2 = ready(push_to_show=False)
        r2.press("SELECT")
        for _ in range(3):
            r2.press("DOWN")
        r2.press("SELECT")  # push to show: turning it on needs no hold
        self.assertEqual(r2.haptic.last, "success")
        r3 = ready()
        r3.press("SELECT")
        r3.press("DOWN")
        r3.press("DOWN")
        r3.press("SELECT")  # Reorder
        r3.press("SELECT")
        r3.press("DOWN")
        r3.press("SELECT")
        self.assertEqual(r3.haptic.last, "success")

    def test_turning_push_to_show_off_by_hold_ends_on_commit(self):
        r = Rig()
        r.unlock()
        r.press("SELECT")
        for _ in range(3):
            r.press("DOWN")
        r.press("SELECT")
        r.down("PTT")
        r.run(700)
        r.up("PTT")
        self.assertEqual(r.haptic.last, "commit")


class Colours(unittest.TestCase):
    def test_powered_unlocked_is_blue(self):
        r = ready()
        for c in trace(r, 400):
            self.assertEqual(dom(c), "B")

    def test_locked_is_blue(self):
        r = Rig()
        for c in trace(r, 1500):
            self.assertEqual(dom(c), "B")
            self.assertEqual(c[0], 0)

    def test_a_wrong_combo_blinks_red_three_times_then_back_to_blue(self):
        r = Rig()
        r.run(100)
        r.combo(WRONG)
        r.press("SELECT")
        frames = trace(r, 800)
        red = [dom(c) == "R" for c in frames]
        blinks = sum(1 for a, b in zip([False] + red, red) if b and not a)
        self.assertEqual(blinks, 3)
        self.assertEqual(dom(frames[-1]), "B")

    def test_a_hold_turns_the_blue_into_green_then_flashes_green(self):
        r = ready()
        r.ui.scan(GOOD)
        r.run(100)
        r.down("PTT")
        frames = trace(r, 700)
        r.up("PTT")
        greens = [c[1] for c in frames]
        ramp = greens[1:21]  # frame 0 is still the waiting sweep, before the hold registers
        self.assertEqual(ramp, sorted(ramp))  # green only rises during the hold
        self.assertGreater(ramp[-1], ramp[0])
        self.assertTrue(all(c[0] == 0 for c in frames))  # never red during an approval
        self.assertTrue(any(dom(c) == "G" and c[2] == 0 for c in frames))  # the green flash
        after = trace(r, 800)
        self.assertEqual(dom(after[-1]), "B")  # and back to powered

    def test_a_tap_is_a_white_blip(self):
        r = ready()
        r.down("PTT")
        r.run(60)
        r.up("PTT")
        frames = trace(r, 300)
        white = [c for c in frames if min(c) > 0 and len(set(c)) == 1]
        self.assertTrue(white)

    def test_releasing_a_hold_early_gives_an_orange_blip_not_red(self):
        r = ready()
        r.ui.scan(GOOD)
        r.run(100)
        r.down("PTT")
        r.run(250)
        r.up("PTT")
        frames = trace(r, 500)
        orange = [c for c in frames if c[0] > 0 and 0 < c[1] < c[0] and c[2] == 0]
        self.assertTrue(orange)
        self.assertFalse(any(c == (127, 0, 0) for c in frames))  # no error-red

    def test_a_visible_code_is_purple_and_hides_with_the_code(self):
        r = Rig()
        r.unlock()
        r.press("DOWN")
        r.press("SELECT")  # push to show is on: needs a hold
        r.down("PTT")
        r.run(700)
        self.assertEqual(r.id, "TOTPCode")
        purple = [c for c in trace(r, 400) if c[0] > 0 and c[2] > 0 and c[1] == 0]
        self.assertTrue(purple)
        r.up("PTT")
        frames = trace(r, 1000)
        self.assertEqual(dom(frames[-1]), "B")

    def test_a_host_request_pulses_cyan(self):
        r = ready()
        r.session.request("SIGN", "USB", "Sign x")
        frames = trace(r, 500)
        self.assertTrue(any(c[1] > 0 and c[2] > 0 and c[0] == 0 and c[1] > 60 for c in frames))

    def test_wiped_is_solid_red(self):
        r = Rig()
        for _ in range(10):
            r.combo(WRONG)
            r.press("SELECT")
            r.clock.advance(4000000)
        for c in trace(r, 600):
            self.assertEqual((dom(c), c[1], c[2]), ("R", 0, 0))

    def test_success_blinks_green_twice(self):
        r = ready()
        r.press("SELECT")
        r.press("DOWN")
        r.press("SELECT")
        r.press("RIGHT")
        r.press("SELECT")  # zone saved
        frames = trace(r, 600)
        g = [dom(c) == "G" for c in frames]
        self.assertEqual(sum(1 for a, b in zip([False] + g, g) if b and not a), 2)

    def test_brightness_never_exceeds_the_cap(self):
        r = ready()
        top = 160  # an absolute ceiling, independent of the BRIGHTNESS constant
        r.ui.scan(GOOD)
        r.hold("PTT", 700)
        for c in trace(r, 1500):
            self.assertTrue(all(0 <= x <= top for x in c), c)

    def test_a_power_cycle_does_not_replay_old_events(self):
        r = ready()
        r.press("PTT", 100)  # a tap
        r.boot()
        frames = trace(r, 300)
        self.assertFalse(any(min(c) > 0 and len(set(c)) == 1 for c in frames))  # no white replay


if __name__ == "__main__":
    unittest.main()
