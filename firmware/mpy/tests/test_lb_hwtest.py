import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
sys.path.insert(0, "../pico")
sys.path.insert(0, "pico")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import lb_hwtest
from lb_hwtest import HwTest, ORDER
import pico_main

NAMES = ORDER


def sane(testcase, lines):
    for ln in lines:
        testcase.assertEqual(len(ln), 16, repr(ln))
        testcase.assertTrue(all(32 <= ord(c) < 127 for c in ln), repr(ln))


class State(unittest.TestCase):
    def test_start(self):
        t = HwTest()
        l1, l2 = t.lines(0)
        sane(self, (l1, l2))
        self.assertTrue(l1.startswith("Button test") and l1.rstrip().endswith("0/7"))
        self.assertEqual(l2.strip(), "Press a button")
        self.assertEqual(t.missing(), list(ORDER))
        self.assertFalse(t.complete())

    def test_pressed_shows_name_and_a_running_timer(self):
        t = HwTest()
        t.button("PTT", True, 1000)
        self.assertEqual(t.lines(1000)[1].strip(), "> PTT 0.0s")
        self.assertEqual(t.lines(1450)[1].strip(), "> PTT 0.4s")
        self.assertEqual(t.lines(2550)[1].strip(), "> PTT 1.5s")
        self.assertEqual(t.lines(12000)[1].strip(), "> PTT 11.0s")
        self.assertTrue(t.lines(1000)[0].rstrip().endswith("1/7"))

    def test_release_shows_the_last_button(self):
        t = HwTest()
        t.button("LEFT", True, 0)
        t.button("LEFT", False, 100)
        self.assertEqual(t.lines(200)[1].strip(), "last: LEFT")

    def test_two_buttons_at_once_show_both_without_a_timer(self):
        t = HwTest()
        t.button("UP", True, 0)
        t.button("SELECT", True, 50)
        self.assertEqual(t.lines(300)[1].strip(), "> UP SELECT")
        t.button("UP", False, 400)
        self.assertEqual(t.lines(500)[1].strip().split()[:2], [">", "SELECT"])
        self.assertIn("0.", t.lines(500)[1])

    def test_progress_counts_each_button_once(self):
        t = HwTest()
        for _ in range(3):
            t.button("UP", True, 0)
            t.button("UP", False, 10)
        self.assertEqual(t.seen(), ["UP"])
        self.assertTrue(t.lines(0)[0].rstrip().endswith("1/7"))

    def test_unknown_buttons_are_ignored(self):
        t = HwTest()
        t.button("POWER", True, 0)
        t.button("POWER", False, 5)
        self.assertEqual((t.seen(), t.lines(10)[1].strip()), ([], "Press a button"))

    def test_complete_and_finished_only_after_release_and_hold_time(self):
        t = HwTest(done_hold_ms=4000)
        now = 0
        for n in NAMES:
            t.button(n, True, now)
            self.assertFalse(t.finished(now + 99999), n)  # held: never finished
            t.button(n, False, now + 50)
            now += 100
        self.assertTrue(t.complete())
        self.assertEqual(t.missing(), [])
        l1, l2 = t.lines(now)
        self.assertTrue(l1.startswith("ALL 7 OK!"))
        self.assertEqual(l2.strip(), "Test complete")
        self.assertFalse(t.finished(now + 3000))
        self.assertTrue(t.finished(now + 4100))
        t.button("UP", True, now + 4200)  # touching a button again keeps the all-clear up
        self.assertFalse(t.finished(now + 99999))
        self.assertTrue(t.lines(now + 4300)[0].startswith("ALL 7 OK!"))

    def test_fewer_wired_buttons(self):
        t = HwTest(["UP", "PTT"])
        t.button("UP", True, 0)
        t.button("UP", False, 5)
        self.assertEqual(t.missing(), ["PTT"])
        self.assertTrue(t.lines(10)[0].rstrip().endswith("1/2"))
        t.button("PTT", True, 20)
        self.assertTrue(t.complete())
        self.assertTrue(t.lines(30)[0].startswith("ALL 2 OK!"))

    def test_lines_always_fit_the_display(self):
        t = HwTest()
        for i, n in enumerate(NAMES):
            t.button(n, True, i * 10)
            sane(self, t.lines(i * 10 + 5))
        sane(self, t.lines(10 ** 8))

    def test_timer_survives_tick_wraparound(self):
        import lb_ticks
        t = HwTest()
        t.button("PTT", True, lb_ticks.PERIOD - 300)
        self.assertEqual(t.lines(200)[1].strip(), "> PTT 0.5s")


class Pin:
    def __init__(self, n):
        self.n = n
        self.level = 1

    def value(self):
        return self.level


class Display:
    """Keeps only frames that differ from the last one (like a real LCD), and never builds one big
    string: a long join fails on a fragmented MicroPython heap."""

    def __init__(self):
        self.shown = []

    def show(self, a, b):
        if not self.shown or self.shown[-1] != (a, b):
            self.shown.append((a, b))

    def has(self, sub):
        for a, b in self.shown:
            if sub in a or sub in b or sub in a + "|" + b:
                return True
        return False


class Wrapper(unittest.TestCase):
    """pico_main.hwtest driven by fake pins, a fake clock and a fake display."""

    def setUp(self):
        import pico_config as cfg
        self.cfg = cfg
        self.t = 0
        self.pins = {}
        self.out = []
        self.disp = Display()
        self.script = lambda t: {}  # time -> {gpio: level}

    def sleep(self, n):
        self.t += n
        for name, level in self.script(self.t).items():
            gpio = self.cfg.BUTTONS[name]
            if gpio in self.pins:
                self.pins[gpio].level = level

    def go(self, timeout_s=60):
        return pico_main.hwtest(timeout_s, self.out.append, make_pin=lambda n: self.pins.setdefault(n, Pin(n)),
                                ticks=lambda: self.t, sleep_ms=self.sleep, display=self.disp)

    def test_pressing_everything_passes_and_the_lcd_follows(self):
        order = list(NAMES)

        def script(t):
            slot, phase = divmod(t, 400)
            lv = {n: 1 for n in order}
            if slot < len(order) and 100 <= phase < 300:
                lv[order[slot]] = 0
            return lv
        self.script = script
        self.assertTrue(self.go())
        for n in NAMES:
            self.assertTrue(self.disp.has("> %s 0." % n), n)
        self.assertTrue(self.disp.has("ALL 7 OK!"))
        self.assertIn("all 7 buttons work", self.out[-1])
        self.assertTrue(any("(GP22)" in o and "PTT" in o for o in self.out))
        for a, b in self.disp.shown:
            sane(self, (a, b))

    def test_a_dead_button_is_reported_and_listed_on_the_lcd(self):
        def script(t):
            lv = {n: 1 for n in NAMES}
            if t < 5000:
                slot = t // 500
                if slot < 6 and (t % 500) >= 100 and (t % 500) < 300:
                    lv[NAMES[slot]] = 0  # everything but PTT
            return lv
        self.script = script
        self.assertFalse(self.go(timeout_s=8))
        self.assertIn("never pressed: PTT", "\n".join(self.out))
        self.assertTrue(self.disp.has("Missing 1/7"))
        last_l2 = [b for a, b in self.disp.shown if a.startswith("Missing")][-1]
        self.assertEqual(last_l2.strip(), "PTT")

    def test_timeout_with_no_presses_lists_everything(self):
        self.assertFalse(self.go(timeout_s=1))
        self.assertTrue(self.disp.has("Missing 7/7"))
        self.assertIn("never pressed: " + " ".join(NAMES), "\n".join(self.out))

    def test_stop_button_ends_immediately_without_the_scroll(self):
        calls = [0]

        def sleep(n):
            calls[0] += 1
            self.t += n
            if calls[0] > 50:
                raise KeyboardInterrupt
        r = pico_main.hwtest(60, self.out.append, make_pin=lambda n: self.pins.setdefault(n, Pin(n)),
                             ticks=lambda: self.t, sleep_ms=sleep, display=self.disp)
        self.assertFalse(r)
        self.assertIn("stopped", self.out)
        self.assertTrue(self.disp.has("Stopped"))
        self.assertFalse(self.disp.has("Missing"))
        self.assertLess(self.t, 1000)  # no 6 s scroll after Stop

    def test_only_wired_buttons_are_tested(self):
        import pico_config as cfg
        saved = dict(cfg.BUTTONS)
        cfg.BUTTONS["LEFT"] = None
        cfg.BUTTONS["RIGHT"] = None
        try:
            self.assertFalse(self.go(timeout_s=1))
        finally:
            cfg.BUTTONS.update(saved)
        self.assertTrue(self.disp.has("0/5"))
        self.assertNotIn("LEFT", self.out[-1])   # unwired buttons are not expected...
        self.assertNotIn("RIGHT", self.out[-1])  # ...so they are not reported missing
        self.assertIn("UP DOWN SELECT BACK PTT", self.out[-1])


class FakeLed:
    def __init__(self):
        self.calls = []

    def set(self, r, g, b):
        self.calls.append((r, g, b))

    def off(self):
        self.calls.append("off")


class All(Wrapper):
    """pico_main.hwtest_all: LCD, LED and buttons in one run."""

    def go_all(self, stages=None, led=None):
        self.led = led or FakeLed()
        return pico_main.hwtest_all(stages, 1, self.out.append, make_pin=lambda n: self.pins.setdefault(n, Pin(n)),
                                    ticks=lambda: self.t, sleep_ms=self.sleep, display=self.disp, led=self.led)

    def test_runs_every_stage_and_reports_each(self):
        self.assertFalse(self.go_all())  # nobody presses buttons, so that stage fails
        text = "\n".join(self.out)
        for name in ("lcd", "led", "buttons"):
            self.assertIn("== %s ==" % name, text)
        self.assertIn("lcd      look", text)
        self.assertIn("led      PASS", text)
        self.assertIn("buttons  FAIL", text)
        self.assertIn((200, 0, 0), self.led.calls)
        self.assertEqual(self.led.calls[-1], "off")
        self.assertTrue(self.disp.has("Libra LCD test"))
        self.assertTrue(self.disp.has("HW test FAILED"))

    def test_stages_can_be_picked(self):
        self.assertTrue(self.go_all(["lcd", "led"]))
        self.assertNotIn("== buttons ==", "\n".join(self.out))

    def test_a_crashing_stage_fails_but_the_rest_still_run(self):
        class Boom(FakeLed):
            def set(self, r, g, b):
                raise OSError("pwm")
        self.assertFalse(self.go_all(["led", "lcd"], led=Boom()))
        text = "\n".join(self.out)
        self.assertIn("led stage crashed", text)
        self.assertIn("lcd      look", text)


if __name__ == "__main__":
    unittest.main()
