import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
sys.path.insert(0, "pico")
sys.path.insert(0, "tests")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import pico_main
from lb_sleep import IdleSleep


def scr(sid="Idle", seq=0):
    return {"id": sid, "haptic": {"seq": seq, "kind": None}}


class Logic(unittest.TestCase):
    def test_sleeps_after_the_timeout_and_not_before(self):
        s = IdleSleep(30000)
        self.assertFalse(s.update(0, scr()))
        self.assertFalse(s.update(29999, scr()))
        self.assertTrue(s.update(30000, scr()))

    def test_activity_restarts_the_clock(self):
        s = IdleSleep(30000)
        s.update(0, scr())
        s.button("UP", True, 20000)
        s.button("UP", False, 20100)
        self.assertFalse(s.update(40000, scr()))
        self.assertTrue(s.update(50200, scr()))

    def test_a_press_wakes_and_is_swallowed_with_its_release(self):
        s = IdleSleep(1000)
        s.update(0, scr())
        self.assertTrue(s.update(1000, scr()))
        self.assertFalse(s.button("SELECT", True, 1500))   # the waking press does nothing
        self.assertFalse(s.update(1500, scr()))
        self.assertFalse(s.button("SELECT", False, 1600))  # nor does its release
        self.assertTrue(s.button("SELECT", True, 1700))    # the next one does
        self.assertTrue(s.button("SELECT", False, 1800))

    def test_a_release_of_a_button_held_before_sleep_still_passes(self):
        s = IdleSleep(1000)
        s.button("PTT", True, 0)
        self.assertTrue(s.button("PTT", False, 100))

    def test_things_that_need_you_wake_it(self):
        for sid in ("RevealPrompt", "SetTime", "HostRequest", "ConfirmOTP", "ConfirmSetting", "Wiped"):
            s = IdleSleep(1000)
            s.update(0, scr())
            self.assertTrue(s.update(1000, scr()))
            self.assertFalse(s.update(1100, scr(sid)), sid)
            self.assertFalse(s.update(1900, scr(sid)), sid)      # and it stays awake while it waits
            self.assertTrue(s.update(3000, scr()), sid)           # then sleeps again once it is over

    def test_a_new_haptic_cue_wakes_it(self):
        s = IdleSleep(1000)
        s.update(0, scr(seq=0))
        self.assertTrue(s.update(1000, scr(seq=0)))
        self.assertFalse(s.update(1100, scr(seq=1)))

    def test_zero_never_sleeps(self):
        s = IdleSleep(0)
        self.assertFalse(s.update(0, scr()))
        self.assertFalse(s.update(10 ** 7, scr()))

    def test_tick_wraparound(self):
        import lb_ticks
        s = IdleSleep(1000)
        start = lb_ticks.PERIOD - 500
        s.update(start, scr())
        self.assertFalse(s.update(lb_ticks.add(start, 900), scr()))
        self.assertTrue(s.update(lb_ticks.add(start, 1000), scr()))


class Loop(unittest.TestCase):
    """The rig loop with a sleeper: the display and LED really go dark, and wake."""

    def setUp(self):
        import test_pico_hw
        self.t = test_pico_hw
        self.L = test_pico_hw.Loop("test_runs_for_the_requested_time_and_feeds_everything")
        self.L.build()

    def run_loop(self, ms, sleeper, display=None):
        L = self.L
        if display is not None:
            L.display = display

        def sleep(n):
            L.rig.clock.advance(n)
        L.led.t = [0]
        pico_main._run_loop(L.rig, L.rig.clock, L.display, L.led, L.buttons, L.reader, L.console,
                            L.view, L.Cfg, ms, sleep, L.out.append, sleeper=sleeper)

    def test_goes_dark_after_idle_and_stays_dark(self):
        class D(self.L.Display):
            def __init__(self):
                super().__init__()
                self.states = []

            def sleep(self, asleep):
                self.states.append(asleep)
        d = D()
        self.run_loop(3000, IdleSleep(1000), d)
        self.assertEqual(d.states, [True])
        self.assertEqual(d.frames[-1], (" " * 16, " " * 16))
        self.assertEqual(self.L.led.calls[-1][1], "off")
        n = len(d.frames)
        self.run_loop(500, IdleSleep(1), d)  # a fresh sleeper, already past its timeout: no more drawing
        self.assertLessEqual(len(d.frames) - n, 3)

    def test_without_a_sleeper_nothing_changes(self):
        self.run_loop(1500, None)
        self.assertGreater(len(self.L.display.frames), 5)


if __name__ == "__main__":
    unittest.main()
