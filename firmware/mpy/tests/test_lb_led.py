import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_led
import lb_ticks
from lb_led import LedEngine


def scr(sid="Idle", locked=False, seq=0, kind=None, hold=None, code=False):
    return {"id": sid, "status": {"locked": locked}, "haptic": {"seq": seq, "kind": kind},
            "hold": hold, "body": {"code": "123 456"} if code else {}}


def dominant(c):
    return "RGB"[c.index(max(c))] if max(c) else "-"


class Palette(unittest.TestCase):
    def test_unlocked_idle_is_a_dim_steady_blue(self):
        e = LedEngine()
        a = e.color(0, scr())
        self.assertEqual(dominant(a), "B")
        self.assertEqual(a[0], 0)
        self.assertEqual(e.color(1234, scr()), a)  # steady, not breathing
        self.assertLess(max(a), 80)  # dim

    def test_locked_is_blue_breathing(self):
        e = LedEngine()
        seen = [e.color(t, scr("Locked", locked=True)) for t in range(0, 3200, 100)]
        for c in seen:
            self.assertEqual(dominant(c), "B")
            self.assertEqual(c[0], 0)
        levels = [c[2] for c in seen]
        self.assertGreater(max(levels), 3 * min(levels))  # it really breathes
        self.assertEqual(seen[0], e.color(3200, scr("Locked", locked=True)))  # and it loops

    def test_the_breath_is_dimmer_than_the_maximum(self):
        e = LedEngine()
        for t in range(0, 3200, 50):
            self.assertLessEqual(max(e.color(t, scr("Locked", locked=True))), 255 * lb_led.BRIGHTNESS * 0.62)

    def test_wiped_is_solid_red(self):
        e = LedEngine()
        for t in (0, 777, 5000):
            c = e.color(t, scr("Wiped", locked=True))
            self.assertEqual((dominant(c), c[1], c[2]), ("R", 0, 0))

    def test_a_code_on_screen_is_steady_purple(self):
        e = LedEngine()
        c = e.color(0, scr("TOTPCode", code=True))
        self.assertTrue(c[0] > 0 and c[2] > 0 and c[1] == 0)
        self.assertEqual(e.color(999, scr("TOTPCode", code=True)), c)
        self.assertEqual(dominant(e.color(0, scr("TOTPCode", code=False))), "B")  # no code: just powered

    def test_waiting_for_ptt_sweeps_between_green_and_blue(self):
        e = LedEngine()
        for sid in lb_led.WAIT_SCREENS:
            seen = [e.color(t, scr(sid)) for t in range(0, lb_led.WAIT_PERIOD_MS, 20)]
            self.assertEqual({dominant(c) for c in seen}, {"G", "B"}, sid)  # runs green <-> blue
            self.assertTrue(all(c[0] == 0 for c in seen), sid)              # never red: red means error
            self.assertGreater(len(set(seen)), 50, sid)                          # keeps changing
            for a, b in zip(seen, seen[1:]):                                     # smoothly, no jumps
                self.assertLessEqual(max(abs(x - y) for x, y in zip(a, b)), 12, sid)
            self.assertEqual(e.color(lb_led.WAIT_PERIOD_MS, scr(sid)), seen[0])  # and it loops

    def test_waiting_is_capped_and_never_dark(self):
        e = LedEngine()
        for t in range(0, 2400, 7):
            c = e.color(t, scr("RevealPrompt"))
            self.assertLessEqual(max(c), 255 * lb_led.BRIGHTNESS)
            self.assertGreater(max(c), 100)

    def test_a_hold_and_a_cue_beat_waiting(self):
        e = LedEngine()
        e.color(0, scr("SetTime"))
        self.assertEqual(e.color(100, scr("SetTime", hold=1000)), e.color(100, scr("Idle", hold=1000)))
        self.assertEqual(dominant(e.color(200, scr("SetTime", seq=1, kind="error"))), "R")

    def test_other_screens_are_not_waiting(self):
        e = LedEngine()
        for sid in ("Idle", "Settings", "Accounts", "ComboApprove"):
            self.assertEqual(e.color(0, scr(sid)), e.color(777, scr(sid)), sid)

    def test_brightness_is_capped(self):
        e = LedEngine()
        limit = 160  # a hard ceiling (63%), not derived from the constant under test
        self.assertLessEqual(lb_led.BRIGHTNESS, 0.63)
        for kind in lb_led.CUES:
            e.reset()
            e.color(0, scr(seq=0))
            for t in range(0, lb_led.cue_length(kind), 10):
                c = e.color(10 + t, scr(seq=1, kind=kind))
                self.assertTrue(all(0 <= x <= limit for x in c), (kind, c))


class Hold(unittest.TestCase):
    def test_a_hold_blends_the_powered_blue_into_green(self):
        e = LedEngine()
        prev = None
        for p in (1, 100, 300, 500, 700, 900, 1000):
            c = e.color(0, scr(hold=p))
            if prev is not None:
                self.assertLessEqual(c[2], prev[2])  # blue fades
                self.assertGreaterEqual(c[1], prev[1])  # green rises
            self.assertEqual(c[0], 0)  # never red: red is for errors
            prev = c
        start = e.color(0, scr(hold=1))
        self.assertEqual(start, e.color(0, scr()))  # starts from the powered blue, so no jump on press
        end = e.color(0, scr(hold=1000))
        self.assertEqual((end[0], end[2]), (0, 0))
        self.assertGreater(end[1], 100)

    def test_the_hold_beats_the_background_but_not_a_cue(self):
        e = LedEngine()
        e.color(0, scr())
        self.assertEqual(dominant(e.color(5, scr("Locked", locked=True, hold=600))), "G")
        c = e.color(10, scr(seq=1, kind="error", hold=600))
        self.assertEqual(dominant(c), "R")  # a cue wins

    def test_zero_or_missing_progress_means_no_hold(self):
        e = LedEngine()
        a = e.color(0, scr())
        self.assertEqual(e.color(0, scr(hold=0)), a)
        self.assertEqual(e.color(0, scr(hold=None)), a)

    def test_progress_is_clamped(self):
        e = LedEngine()
        self.assertEqual(e.color(0, scr(hold=5000)), e.color(0, scr(hold=1000)))


class Cues(unittest.TestCase):
    def play(self, kind, step=10):
        e = LedEngine()
        e.color(0, scr(seq=0))
        out = []
        t = 5
        while t < lb_led.cue_length(kind) + 60:
            out.append((t, e.color(t, scr(seq=1, kind=kind))))
            t += step
        return out

    def colours(self, kind):
        return set(dominant(c) for _, c in self.play(kind))

    def test_each_cue_uses_its_meaning_colour(self):
        self.assertEqual(self.colours("error") - {"B", "-"}, {"R"})
        self.assertEqual(self.colours("success") - {"B", "-"}, {"G"})
        self.assertEqual(self.colours("commit") - {"B", "-"}, {"G"})
        white = [c for _, c in self.play("tap") if min(c) > 0]
        self.assertTrue(white and all(len(set(c)) == 1 for c in white))  # equal R, G and B
        notify = [c for _, c in self.play("notify") if c[1] > 0 and c[2] > 0 and c[0] == 0]
        self.assertTrue(notify)  # cyan

    def test_error_is_three_blinks(self):
        frames = [dominant(c) == "R" for _, c in self.play("error", 5)]
        blinks = sum(1 for a, b in zip([False] + frames, frames) if b and not a)
        self.assertEqual(blinks, 3)

    def test_success_is_two_green_blinks(self):
        frames = [dominant(c) == "G" for _, c in self.play("success", 5)]
        blinks = sum(1 for a, b in zip([False] + frames, frames) if b and not a)
        self.assertEqual(blinks, 2)

    def test_commit_is_one_steady_flash(self):
        frames = self.play("commit", 5)
        on = [t for t, c in frames if dominant(c) == "G"]
        self.assertTrue(on and on[-1] - on[0] >= 400)

    def test_cue_ends_and_the_background_returns(self):
        for kind in lb_led.CUES:
            frames = self.play(kind)
            self.assertEqual(frames[-1][1], LedEngine().color(0, scr()), kind)

    def test_cue_length(self):
        self.assertEqual(lb_led.cue_length("commit"), 450)
        self.assertEqual(lb_led.cue_length("tap"), 90)

    def test_a_new_event_restarts_the_cue(self):
        e = LedEngine()
        e.color(0, scr(seq=0))
        e.color(10, scr(seq=1, kind="error"))
        e.color(300, scr(seq=1, kind="error"))  # the error is over by now
        c = e.color(310, scr(seq=2, kind="commit"))
        self.assertEqual(dominant(c), "G")
        self.assertEqual(e.color(400, scr(seq=2, kind="commit")), c)

    def test_an_event_during_a_cue_replaces_it(self):
        e = LedEngine()
        e.color(0, scr(seq=0))
        e.color(10, scr(seq=1, kind="error"))
        self.assertEqual(dominant(e.color(30, scr(seq=2, kind="success"))), "G")

    def test_the_first_frame_never_replays_an_old_event(self):
        e = LedEngine()
        c = e.color(0, scr(seq=41, kind="error"))  # the counter is already at 41 when we start
        self.assertEqual(c, LedEngine().color(0, scr()))

    def test_unknown_kinds_and_missing_haptic_are_ignored(self):
        e = LedEngine()
        e.color(0, scr(seq=0))
        self.assertEqual(e.color(5, scr(seq=1, kind="mystery")), LedEngine().color(0, scr()))
        e.color(10, {"id": "Idle", "status": {}, "hold": None, "body": {}})  # no haptic key at all
        e.color(20, {})

    def test_tick_wraparound_inside_a_cue(self):
        e = LedEngine()
        start = lb_ticks.PERIOD - 100
        e.color(start - 5, scr(seq=0))
        e.color(start, scr(seq=1, kind="commit"))
        self.assertEqual(dominant(e.color((start + 300) % lb_ticks.PERIOD, scr(seq=1, kind="commit"))), "G")
        self.assertEqual(e.color((start + 500) % lb_ticks.PERIOD, scr(seq=1, kind="commit")),
                         LedEngine().color(0, scr()))

    def test_colours_are_always_three_small_ints(self):
        e = LedEngine()
        for t in range(0, 4000, 37):
            for sc in (scr(), scr("Locked", True), scr(hold=t % 1000), scr("Wiped", True),
                       scr("TOTPCode", code=True), scr(seq=t // 500, kind="error")):
                c = e.color(t, sc)
                self.assertEqual(len(c), 3)
                for x in c:
                    self.assertTrue(isinstance(x, int) and 0 <= x <= 255, (t, c))


if __name__ == "__main__":
    unittest.main()
