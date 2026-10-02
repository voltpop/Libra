# Host tests for the Pico hardware modules, against fakes (an HD44780 emulator, fake pins).
import sys
sys.path.insert(0, "..")
sys.path.insert(0, ".")
sys.path.insert(0, "../pico")
sys.path.insert(0, "pico")
import unittest
import ucompat  # noqa: F401  (adds assertions MicroPython's unittest lacks)
import hw_buttons
import hw_lcd
import hw_led
import pico_main
import lb_ticks


class Model:
    """An HD44780 controller: decodes latched (rs, nibble) pairs into commands and DDRAM."""

    def __init__(self):
        self.latched = []        # (rs, nibble)
        self.cmds = []           # commands after init
        self.ddram = {}
        self.cgram = {}          # custom characters: address -> row byte
        self.cg_mode = False
        self.cg_addr = 0
        self.cursor = 0

    def latch(self, rs, nib):
        self.latched.append((rs, nib))
        n = len(self.latched)
        if n <= 4 or (n - 4) % 2:
            return  # 3,3,3,2 wake-up handshake, or the first half of a byte
        (rs, hi), (_, lo) = self.latched[-2], self.latched[-1]
        v = (hi << 4) | lo
        if rs == 0:
            self.cmds.append(v)
            if v & 0x80:
                self.cg_mode = False
                self.cursor = v & 0x7F
            elif v & 0x40:
                self.cg_mode = True
                self.cg_addr = v & 0x3F
            elif v == 0x01:
                self.ddram = {}
                self.cursor = 0
        elif self.cg_mode:
            self.cgram[self.cg_addr] = v
            self.cg_addr += 1
        else:
            self.ddram[self.cursor] = chr(v)
            self.cursor += 1

    def row(self, r):
        base = (0x00, 0x40)[r]
        return "".join(self.ddram.get(base + i, " ") for i in range(16))


class Chip(Model):
    """A PCF8574 backpack with an HD44780 behind it: decodes the real I2C bytes."""

    def __init__(self, addr=0x27):
        Model.__init__(self)
        self.addr = addr
        self.writes = 0
        self.prev_en = 0
        self.bytes_seen = []
        self.rw_ever_set = False
        self.backlight_off_seen = False

    def writeto(self, addr, data):
        if addr != self.addr:
            raise OSError(19)
        self.writes += 1
        for b in data:
            self.bytes_seen.append(b)
            if b & 0x02:
                self.rw_ever_set = True
            if not b & 0x08:
                self.backlight_off_seen = True
            en = b & 0x04
            if self.prev_en and not en:
                self.latch(b & 1, b >> 4)
            self.prev_en = en


class ParallelChip(Model):
    """The module's pins wired straight to GPIOs. Records every pin change so electrical rules
    can be checked: data and RS must be stable while E is high."""

    NAMES = ("RS", "E", "D4", "D5", "D6", "D7")

    def __init__(self):
        Model.__init__(self)
        self.state = dict.fromkeys(self.NAMES, 0)
        self.changes = 0
        self.violations = []
        self.e_high_count = 0

    def pin(self, name):
        chip = self

        class P:
            def value(self, v=None):
                if v is None:
                    return chip.state[name]
                chip.set(name, 1 if v else 0)
        return P()

    def set(self, name, v):
        if self.state[name] == v:
            return
        self.changes += 1
        if name != "E" and self.state["E"]:
            self.violations.append("%s changed while E was high" % name)
        self.state[name] = v
        if name == "E":
            if v:
                self.e_high_count += 1
            else:
                nib = sum(self.state["D%d" % (4 + i)] << i for i in range(4))
                self.latch(self.state["RS"], nib)


class Sleeps:
    def __init__(self):
        self.us = 0
        self.ms = 0

    def sleep_us(self, n):
        self.us += n

    def sleep_ms(self, n):
        self.ms += n


def make_lcd(chip=None):
    chip = chip or Chip()
    s = Sleeps()
    return hw_lcd.LCD(chip, chip.addr, sleep_us=s.sleep_us, sleep_ms=s.sleep_ms), chip, s


class LcdDriver(unittest.TestCase):
    def test_init_handshake_and_commands(self):
        lcd, chip, s = make_lcd()
        self.assertEqual(chip.latched[:4], [(0, 3), (0, 3), (0, 3), (0, 2)])
        self.assertEqual(chip.cmds, [0x28, 0x08, 0x01, 0x06, 0x0C, 0x40, 0x48, 0x50, 0x58, 0x60, 0x80])  # then the five glyphs
        self.assertGreaterEqual(s.ms, 50 + 5 + 5 + 1)  # datasheet power-up waits

    def test_the_custom_symbols_are_loaded_into_the_module(self):
        import lb_lcd
        lcd, chip, _ = make_lcd()
        for slot, rows in enumerate(lb_lcd.GLYPHS):
            self.assertEqual([chip.cgram[slot * 8 + i] for i in range(8)], list(rows), slot)

    def test_a_symbol_goes_out_as_its_custom_code(self):
        import lb_lcd
        lcd, chip, _ = make_lcd()
        lcd.show(lb_lcd.fit(lb_lcd.SYM_LIBRA + " " + lb_lcd.SYM_LOCK), lb_lcd.fit("x"))
        self.assertEqual(chip.row(0)[:3], "\x00 \x01")

    def test_text_lands_on_the_right_rows(self):
        lcd, chip, _ = make_lcd()
        lcd.show("Hello", "World 123")
        self.assertEqual(chip.row(0), "Hello" + " " * 11)
        self.assertEqual(chip.row(1), "World 123" + " " * 7)
        self.assertIn(0x80, chip.cmds)
        self.assertIn(0xC0, chip.cmds)

    def test_unchanged_lines_cost_no_i2c_traffic(self):
        lcd, chip, _ = make_lcd()
        lcd.show("Same", "Lines")
        n = chip.writes
        lcd.show("Same", "Lines")
        self.assertEqual(chip.writes, n)
        lcd.show("Same", "Changed")
        self.assertGreater(chip.writes, n)
        self.assertEqual(chip.row(0), "Same" + " " * 12)
        self.assertEqual(chip.row(1), "Changed" + " " * 9)
        c0 = chip.cmds.count(0x80)
        lcd.show("Same", "Again")
        self.assertEqual(chip.cmds.count(0x80), c0)  # row 0 was not rewritten

    def test_long_and_odd_text(self):
        lcd, chip, _ = make_lcd()
        lcd.show("x" * 40, "Jürgen\n")
        self.assertEqual(chip.row(0), "x" * 16)
        self.assertEqual(chip.row(1), "J?rgen?" + " " * 9)

    def test_electrical_rules(self):
        lcd, chip, _ = make_lcd()
        lcd.show("abc", "def")
        self.assertFalse(chip.rw_ever_set)          # R/W stays low: we only write
        self.assertFalse(chip.backlight_off_seen)   # backlight bit stays on

    def test_backlight_control(self):
        lcd, chip, _ = make_lcd()
        lcd.backlight(False)
        self.assertEqual(chip.bytes_seen[-1] & 0x08, 0)
        lcd.backlight(True)
        self.assertEqual(chip.bytes_seen[-1] & 0x08, 0x08)

    def test_wrong_address_raises_oserror(self):
        chip = Chip(0x27)
        with self.assertRaises(OSError):
            hw_lcd.LCD(chip, 0x3F, sleep_us=lambda n: None, sleep_ms=lambda n: None)

    def test_text_display_fallback_prints_on_change_only(self):
        out = []
        d = hw_lcd.TextDisplay(out.append)
        d.show("a", "b")
        d.show("a", "b")
        d.show("a", "c")
        self.assertEqual(out, ["[a]\n[b]", "[a]\n[c]"])


def make_parallel_lcd(chip=None):
    chip = chip or ParallelChip()
    s = Sleeps()
    pins = {"RS": 2, "E": 3, "D4": 4, "D5": 5, "D6": 6, "D7": 7}
    names = {2: "RS", 3: "E", 4: "D4", 5: "D5", 6: "D6", 7: "D7"}
    lcd = hw_lcd.make_parallel(pins, make_pin=lambda n: chip.pin(names[n]),
                               sleep_us=s.sleep_us, sleep_ms=s.sleep_ms)
    return lcd, chip, s


class ParallelDriver(unittest.TestCase):
    def test_init_handshake_and_commands(self):
        lcd, chip, s = make_parallel_lcd()
        self.assertEqual(chip.latched[:4], [(0, 3), (0, 3), (0, 3), (0, 2)])
        self.assertEqual(chip.cmds, [0x28, 0x08, 0x01, 0x06, 0x0C, 0x40, 0x48, 0x50, 0x58, 0x60, 0x80])  # then the five glyphs
        self.assertGreaterEqual(s.ms, 50 + 5 + 5 + 1)

    def test_text_lands_on_the_right_rows(self):
        lcd, chip, _ = make_parallel_lcd()
        lcd.show("Hello", "World 123")
        self.assertEqual(chip.row(0), "Hello" + " " * 11)
        self.assertEqual(chip.row(1), "World 123" + " " * 7)
        self.assertIn(0x80, chip.cmds)
        self.assertIn(0xC0, chip.cmds)

    def test_all_bit_patterns_survive_the_wiring(self):
        lcd, chip, _ = make_parallel_lcd()
        text = "".join(chr(c) for c in range(32, 127))
        for i in range(0, len(text), 16):
            chunk = text[i:i + 16]
            rev = "".join(chunk[k] for k in range(len(chunk) - 1, -1, -1))  # no [::-1] on MicroPython
            lcd.show(chunk, rev)
            self.assertEqual(chip.row(0), lb_lcd_fit(chunk))
            self.assertEqual(chip.row(1), lb_lcd_fit(rev))

    def test_data_never_changes_while_e_is_high(self):
        lcd, chip, _ = make_parallel_lcd()
        lcd.show("Check the timing", "of every pulse!!")
        self.assertEqual(chip.violations, [])
        self.assertEqual(chip.e_high_count, len(chip.latched))  # exactly one E pulse per nibble
        self.assertGreater(len(chip.latched), 60)
        self.assertEqual(chip.state["E"], 0)  # E rests low

    def test_waits_for_setup_and_hold_times(self):
        lcd, chip, s = make_parallel_lcd()
        base_us, base_n = s.us, len(chip.latched)
        lcd.show("timing", "check")
        pulses = len(chip.latched) - base_n
        # each pulse: 2 us data setup + 2 us E width + 60 us for the controller to finish
        self.assertGreaterEqual(s.us - base_us, pulses * 64)

    def test_unchanged_lines_cost_no_pin_activity(self):
        lcd, chip, _ = make_parallel_lcd()
        lcd.show("Same", "Lines")
        n = chip.changes
        lcd.show("Same", "Lines")
        self.assertEqual(chip.changes, n)
        lcd.show("Same", "Changed")
        self.assertGreater(chip.changes, n)
        self.assertEqual(chip.row(1), "Changed" + " " * 9)

    def test_odd_text_and_backlight_noop(self):
        lcd, chip, _ = make_parallel_lcd()
        lcd.show("x" * 40, "J\u00fcrgen\n")
        self.assertEqual(chip.row(0), "x" * 16)
        self.assertEqual(chip.row(1), "J?rgen?" + " " * 9)
        lcd.backlight(False)  # the parallel wiring has the backlight hard-wired: must not raise

    def test_only_the_six_configured_pins_are_touched(self):
        made = []
        chip = ParallelChip()
        names = {2: "RS", 3: "E", 4: "D4", 5: "D5", 6: "D6", 7: "D7"}

        def mk(n):
            made.append(n)
            return chip.pin(names[n])
        hw_lcd.make_parallel({"RS": 2, "E": 3, "D4": 4, "D5": 5, "D6": 6, "D7": 7}, make_pin=mk,
                             sleep_us=lambda n: None, sleep_ms=lambda n: None)
        self.assertEqual(made, [2, 3, 4, 5, 6, 7])  # no D0..D3, no RW
        with self.assertRaises(KeyError):
            hw_lcd.make_parallel({"RS": 2}, make_pin=mk)


def lb_lcd_fit(s):
    return s[:16] + " " * (16 - len(s[:16]))


class Pin:
    def __init__(self, n):
        self.n = n
        self.level = 1  # pulled up

    def value(self):
        return self.level


class Rig:
    def __init__(self, pins):
        self.t = 0
        self.pins = {}
        self.events = []
        self.b = hw_buttons.Buttons(pins, lambda: self.t % lb_ticks.PERIOD,
                                    lambda n, d: self.events.append((n, d)),
                                    make_pin=lambda n: self.pins.setdefault(n, Pin(n)))

    def step(self, ms):
        for _ in range(ms):
            self.t += 1
            self.b.poll()


class ButtonTests(unittest.TestCase):
    def test_press_and_release_after_debounce(self):
        r = Rig({"PTT": 10})
        r.step(50)
        self.assertEqual(r.events, [])
        r.pins[10].level = 0
        r.step(19)
        self.assertEqual(r.events, [])
        r.step(3)
        self.assertEqual(r.events, [("PTT", True)])
        r.pins[10].level = 1
        r.step(30)
        self.assertEqual(r.events, [("PTT", True), ("PTT", False)])

    def test_contact_bounce_is_filtered(self):
        r = Rig({"UP": 11})
        for level in (0, 1, 0, 1, 0, 1, 0):  # chatter every 3 ms
            r.pins[11].level = level
            r.step(3)
        self.assertEqual(r.events, [])
        r.step(30)
        self.assertEqual(r.events, [("UP", True)])

    def test_short_glitch_never_reports(self):
        r = Rig({"UP": 11})
        r.pins[11].level = 0
        r.step(10)
        r.pins[11].level = 1
        r.step(60)
        self.assertEqual(r.events, [])

    def test_unused_pins_and_count(self):
        r = Rig({"UP": 11, "DOWN": None, "BACK": 16})
        self.assertEqual(r.b.count(), 2)
        self.assertEqual(sorted(r.pins), [11, 16])

    def test_independent_buttons(self):
        r = Rig({"UP": 11, "DOWN": 12})
        r.pins[11].level = 0
        r.step(30)
        r.pins[12].level = 0
        r.step(30)
        r.pins[11].level = 1
        r.step(30)
        self.assertEqual(r.events, [("UP", True), ("DOWN", True), ("UP", False)])

    def test_pressed_at_boot_reports_a_press(self):
        r = Rig({"PTT": 10})
        r.pins[10].level = 0
        r.step(40)
        self.assertEqual(r.events, [("PTT", True)])

    def test_survives_tick_wraparound(self):
        r = Rig({"UP": 11})
        r.t = lb_ticks.PERIOD - 10
        r.b = hw_buttons.Buttons({"UP": 11}, lambda: r.t % lb_ticks.PERIOD,
                                 lambda n, d: r.events.append((n, d)),
                                 make_pin=lambda n: r.pins.setdefault(n, Pin(n)))
        r.pins[11].level = 0
        r.step(40)
        self.assertEqual(r.events, [("UP", True)])


class ClockTests(unittest.TestCase):
    def make(self):
        self.ms = 5000
        self.s = 700000000  # seconds since 2000
        return pico_main.PicoClock(lambda: self.ms, lambda: self.s)

    def test_untrusted_until_set_then_unix_time(self):
        c = self.make()
        self.assertFalse(c.trusted())
        self.assertEqual(c.now(), 700000000 + pico_main.EPOCH_2000)
        c.set_unix(1700000000)
        self.assertEqual(c.now(), 1700000000)
        self.s += 5
        self.assertEqual(c.now(), 1700000005)

    def test_warp_moves_both_clocks(self):
        c = self.make()
        t0, n0 = c.ticks(), c.now()
        c.advance(61000)
        self.assertEqual(lb_ticks.diff(c.ticks(), t0), 61000)
        self.assertEqual(c.now() - n0, 61)

    def test_ticks_wrap_like_the_hardware(self):
        c = self.make()
        self.ms = lb_ticks.PERIOD - 5
        a = c.ticks()
        self.ms = 5
        self.assertEqual(lb_ticks.diff(c.ticks(), a), 10)

    def test_callable(self):
        c = self.make()
        self.assertEqual(c(), c.ticks())


class DisplaySelection(unittest.TestCase):
    class I2C(Chip):
        def __init__(self, found, addr=0x27):
            Chip.__init__(self, addr)
            self.found = found

        def scan(self):
            if self.found is None:
                raise OSError(5)
            return self.found

    class Cfg:
        LCD_MODE = "i2c"
        LCD_ADDRS = (0x27, 0x3F)
        LCD_PINS = {"RS": 2, "E": 3, "D4": 4, "D5": 5, "D6": 6, "D7": 7}

    def pick(self, mode, found=None, addr=0x27, make_pin=None):
        out = []
        cfg = type("C", (self.Cfg,), {"LCD_MODE": mode})
        orig = hw_lcd._default_sleeps
        hw_lcd._default_sleeps = lambda: ((lambda n: None), (lambda n: None))
        try:
            d = pico_main.make_display(cfg, out.append, i2c=self.I2C(found, addr), make_pin=make_pin)
        finally:
            hw_lcd._default_sleeps = orig
        return d, out

    def test_i2c_finds_either_common_address(self):
        d, out = self.pick("i2c", [0x27])
        self.assertIsInstance(d, hw_lcd.LCD)
        d, out = self.pick("i2c", [0x3F], 0x3F)
        self.assertIsInstance(d, hw_lcd.LCD)
        self.assertIn("0x3F", out[0])

    def test_i2c_falls_back_to_the_shell_display(self):
        for found in ([], [0x50], None):
            d, out = self.pick("i2c", found)
            self.assertIsInstance(d, hw_lcd.TextDisplay)
            self.assertIn("No LCD", out[0])

    def test_parallel_mode(self):
        chip = ParallelChip()
        names = {2: "RS", 3: "E", 4: "D4", 5: "D5", 6: "D6", 7: "D7"}
        d, out = self.pick("parallel", make_pin=lambda n: chip.pin(names[n]))
        self.assertIsInstance(d, hw_lcd.ParallelLCD)
        self.assertIn("GP2, GP3, GP4, GP5, GP6, GP7", out[0])
        d.show("hi", "there")
        self.assertEqual(chip.row(1), "there" + " " * 11)

    def test_parallel_failure_falls_back_instead_of_crashing(self):
        def broken(n):
            raise OSError("pin busy")
        d, out = self.pick("parallel", make_pin=broken)
        self.assertIsInstance(d, hw_lcd.TextDisplay)
        self.assertIn("failed", out[0])

    def test_text_and_unknown_modes(self):
        for mode in ("text", "bogus", None):
            d, out = self.pick(mode)
            self.assertIsInstance(d, hw_lcd.TextDisplay)


class FakeLed:
    def __init__(self):
        self.calls = []
        self.t = [0]

    def set(self, r, g, b):
        self.calls.append((self.t[0], (r, g, b)))

    def off(self):
        self.calls.append((self.t[0], "off"))


class Loop(unittest.TestCase):
    """pico_main._run_loop with a real rig and fakes for everything physical."""

    class Cfg:
        LCD_REFRESH_MS = 120
        LED_REFRESH_MS = 25

    class Buttons:
        def __init__(self):
            self.polls = 0

        def poll(self):
            self.polls += 1

    class Reader:
        def __init__(self, script=()):
            self.script = list(script)
            self.n = 0

        def read(self):
            self.n += 1
            for step in list(self.script):
                if step[0] == self.n:
                    self.script.remove(step)
                    if isinstance(step[1], BaseException):
                        raise step[1]
                    return step[1]
            return None

    class Display:
        def __init__(self):
            self.frames = []

        def show(self, a, b):
            self.frames.append((a, b))

    def build(self, reader_script=(), led=True, fail_ui_after=None):
        import lb_console
        import lb_lcd
        from lb_rig import Rig
        self.rig = Rig(push_to_show=False)
        self.led = FakeLed() if led else None
        if self.led:
            self.led.t = [0]
        self.display = self.Display()
        self.buttons = self.Buttons()
        self.out = []
        self.console = lb_console.Console(self.rig, out=self.out.append)
        self.reader = self.Reader(reader_script)
        self.view = lb_lcd.LcdView(marquee=False)
        self.naps = []
        if fail_ui_after is not None:
            real = self.rig.ui.tick
            count = [0]

            def flaky():
                count[0] += 1
                if count[0] > fail_ui_after[0] and (fail_ui_after[1] is None or count[0] <= fail_ui_after[1]):
                    raise RuntimeError("boom")
                real()
            self.rig.ui.tick = flaky

    def go(self, max_ms):
        def sleep(n):
            self.naps.append(n)
            self.rig.clock.advance(n)
        if self.led:
            self.led.t = [0]
        pico_main._run_loop(self.rig, self.rig.clock, self.display, self.led, self.buttons, self.reader,
                            self.console, self.view, self.Cfg, max_ms, sleep, self.out.append)

    def test_runs_for_the_requested_time_and_feeds_everything(self):
        self.build(reader_script=[(5, "status")])
        self.go(1000)
        self.assertGreater(self.buttons.polls, 50)
        self.assertTrue(any("screen " in o for o in self.out))  # the console line was handled
        self.assertTrue(8 <= len(self.display.frames) <= 12 or len(self.display.frames) > 0)
        self.assertTrue(self.display.frames[0][0].startswith("\x01 Locked"))  # closed padlock first
        self.assertGreater(len(self.led.calls), 5)

    def test_the_led_is_off_when_the_loop_ends(self):
        self.build()
        self.go(500)
        self.assertEqual(self.led.calls[-1][1], "off")

    def test_the_led_follows_the_screen_while_running(self):
        self.build()
        self.go(600)
        colours = [c for _, c in self.led.calls if c != "off"]
        self.assertTrue(colours and all(c[2] >= c[0] for c in colours))  # locked: only blue

    def test_stop_button_shows_stopped_and_turns_the_led_off(self):
        self.build(reader_script=[(30, KeyboardInterrupt())])
        self.go(60000)  # would run a minute: Stop ends it early
        self.assertEqual(self.display.frames[-1][0].strip(), "Stopped")
        self.assertIn("stopped", self.out)
        self.assertEqual(self.led.calls[-1][1], "off")
        self.assertLess(self.rig.clock.ticks() - 1000, 5000)

    def test_a_few_errors_do_not_stop_it_and_it_recovers(self):
        self.build(fail_ui_after=(10, 15))  # calls 11 to 15 fail (five in a row), then it is fine
        self.go(4000)  # each failure backs off 500 ms, so five of them need more than 2 s
        self.assertEqual(sum(1 for o in self.out if o.startswith("error:")), 5)
        self.assertIn(500, self.naps)  # it backed off
        self.assertEqual(self.led.calls[-1][1], "off")

    def test_endless_errors_raise_and_still_turn_the_led_off(self):
        self.build(fail_ui_after=(5, None))
        with self.assertRaises(RuntimeError):
            self.go(600000)
        self.assertEqual(self.led.calls[-1][1], "off")

    def test_works_without_an_led(self):
        self.build(led=False)
        self.go(300)
        self.assertTrue(self.display.frames)


class LedRoutines(unittest.TestCase):
    def clock(self, led):
        def sleep(n):
            led.t[0] += n
        return (lambda: led.t[0]), sleep

    def test_led_test_shows_off_red_green_blue_white_then_off(self):
        led = FakeLed()
        out, naps = [], []
        ticks, sleep = self.clock(led)
        ok = pico_main.led_test(1.5, out.append, sleep_ms=lambda n: (naps.append(n), sleep(n)), led=led)
        self.assertTrue(ok)
        colours = [c for _, c in led.calls]
        self.assertEqual(colours[:5], [(0, 0, 0), (200, 0, 0), (0, 200, 0), (0, 0, 200), (200, 200, 200)])
        self.assertEqual(colours[-1], "off")
        self.assertEqual(naps, [1500] * 5)
        self.assertIn("RED", " ".join(out))
        self.assertIn("LED_COMMON", out[0])  # the first step tells you what a wrong 'common' looks like
        self.assertIn("LED_COMMON", out[-1])

    def test_led_test_turns_it_off_even_if_interrupted(self):
        led = FakeLed()

        def boom(n):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            pico_main.led_test(1, lambda s: None, sleep_ms=boom, led=led)
        self.assertEqual(led.calls[-1][1], "off")

    def test_no_led_configured_says_so(self):
        import pico_config as cfg
        saved = cfg.LED_PINS
        cfg.LED_PINS = None
        try:
            out = []
            self.assertFalse(pico_main.led_test(1, out.append, sleep_ms=lambda n: None))
            self.assertFalse(pico_main.led_demo(out.append, sleep_ms=lambda n: None))
        finally:
            cfg.LED_PINS = saved
        self.assertTrue(all("no LED configured" in o for o in out))

    def test_make_led_is_none_when_unconfigured_or_broken(self):
        import pico_config as cfg
        out = []

        class C:
            LED_PINS = None
        self.assertIsNone(pico_main.make_led(C, out.append))

        class Broken:
            LED_PINS = {"R": 1, "G": 2, "B": 3}
            LED_COMMON = "sideways"
        self.assertIsNone(pico_main.make_led(Broken, out.append))
        self.assertIn("LED disabled", out[-1])

    def test_led_demo_plays_the_whole_palette_and_ends_dark(self):
        led = FakeLed()
        ticks, sleep = self.clock(led)
        out = []
        self.assertTrue(pico_main.led_demo(out.append, sleep_ms=sleep, ticks=ticks, led=led))
        labels = " | ".join(out)
        for word in ("powered", "locked", "filling", "cue: commit", "cue: success", "cue: error",
                     "cue: tap", "cue: abort", "cue: notify", "purple", "wiped", "done"):
            self.assertIn(word, labels)
        cols = [c for _, c in led.calls if c != "off"]
        self.assertTrue(any(c[2] > c[0] and c[2] > c[1] for c in cols))      # blue
        self.assertTrue(any(c[1] > 0 and c[0] == 0 and c[2] == 0 for c in cols))  # green
        self.assertTrue(any(c[0] > 0 and c[1] == 0 and c[2] == 0 for c in cols))  # red
        self.assertTrue(any(c[0] > 0 and c[2] > 0 and c[1] == 0 for c in cols))   # purple
        self.assertTrue(any(c[0] > 0 and c[0] == c[1] == c[2] for c in cols))     # white (the tap)
        self.assertEqual(led.calls[-1][1], "off")
        self.assertGreater(led.t[0], 18000)  # about nineteen seconds of demo
        self.assertLess(led.t[0], 22000)

    def test_led_demo_turns_it_off_when_stopped(self):
        led = FakeLed()
        n = [0]

        def sleep(ms):
            n[0] += 1
            led.t[0] += ms
            if n[0] > 30:
                raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            pico_main.led_demo(lambda s: None, sleep_ms=sleep, ticks=lambda: led.t[0], led=led)
        self.assertEqual(led.calls[-1][1], "off")


class GuidedTests(unittest.TestCase):
    """lcd_test and button_test, driven with fakes."""

    def test_button_test_reports_seen_and_missing(self):
        import pico_config as cfg
        clock = [0]
        pins = {}

        def ticks():
            return clock[0]

        def sleep(n):
            clock[0] += n
            # press UP between 100 and 300 ms and SELECT between 500 and 700 ms
            for name, lo, hi in (("UP", 100, 300), ("SELECT", 500, 700)):
                if cfg.BUTTONS[name] in pins:
                    pins[cfg.BUTTONS[name]].level = 0 if lo <= clock[0] < hi else 1
        out = []
        ok = pico_main.button_test(1, out.append, make_pin=lambda n: pins.setdefault(n, Pin(n)),
                                   ticks=ticks, sleep_ms=sleep)
        text = "\n".join(out)
        self.assertFalse(ok)
        self.assertIn("UP", text)
        self.assertIn("SELECT", text)
        self.assertIn("(GP%d)" % cfg.BUTTONS["UP"], text)
        last = out[-1]
        self.assertIn("never pressed", last)
        for name in ("DOWN", "LEFT", "RIGHT", "BACK", "PTT"):
            self.assertIn(name, last)
        self.assertNotIn("UP", last.replace("never pressed", ""))

    def test_button_test_passes_when_everything_is_pressed(self):
        import pico_config as cfg
        clock = [0]
        pins = {}
        order = list(cfg.BUTTONS)

        def sleep(n):
            clock[0] += n
            slot = clock[0] // 100
            for i, name in enumerate(order):
                p = pins.get(cfg.BUTTONS[name])
                if p:
                    p.level = 0 if slot == 2 * i + 1 else 1
        out = []
        ok = pico_main.button_test(2, out.append, make_pin=lambda n: pins.setdefault(n, Pin(n)),
                                   ticks=lambda: clock[0], sleep_ms=sleep)
        self.assertTrue(ok)
        self.assertIn("all 7 buttons work", out[-1])

    def test_lcd_test_runs_every_screen(self):
        shown, said, naps = [], [], []
        real_make = pico_main.make_display

        class D:
            def show(self, a, b):
                shown.append((a, b))
        pico_main.make_display = lambda c, out=print, **k: D()
        try:
            pico_main.lcd_test(2, said.append, sleep_ms=naps.append)
        finally:
            pico_main.make_display = real_make
        self.assertEqual(len(shown), 5)
        for a, b in shown[:4]:
            self.assertLessEqual(len(a), 16)  # the driver pads short lines; long ones would be cut
            self.assertLessEqual(len(b), 16)
        self.assertEqual(shown[4][0].strip(), "LCD test done")
        self.assertEqual(naps, [2000] * 4)  # whole milliseconds, one pause per screen
        self.assertEqual(said[-1], "done")

    def test_lcd_test_screens_cover_every_printable_group(self):
        shown = []
        real_make = pico_main.make_display

        class D:
            def show(self, a, b):
                shown.append(a + b)
        pico_main.make_display = lambda c, out=print, **k: D()
        try:
            pico_main.lcd_test(0, lambda s: None, sleep_ms=lambda n: None)
        finally:
            pico_main.make_display = real_make
        text = "".join(shown)
        for ch in "0123456789ABCDEFabcdefghijklmnop!#$%&()*+,-./:":
            self.assertIn(ch, text)


class FakePWM:
    def __init__(self, gpio, duty):
        self.gpio = gpio
        self.created_with = duty
        self.duty = duty
        self.writes = 0
        self.deinited = False

    def duty_u16(self, d):
        self.duty = d
        self.writes += 1

    def deinit(self):
        self.deinited = True


PINS = {"R": 13, "G": 14, "B": 15}


def make_led(common="cathode"):
    made = []

    def mk(gpio, duty):
        p = FakePWM(gpio, duty)
        made.append(p)
        return p
    return hw_led.RGBLed(PINS, common, make_pwm=mk), made


class LedDriver(unittest.TestCase):
    def test_uses_the_three_configured_pins_in_rgb_order(self):
        led, pwm = make_led()
        self.assertEqual([p.gpio for p in pwm], [13, 14, 15])

    def test_created_dark_so_it_never_flashes_on_at_start(self):
        led, pwm = make_led("cathode")
        self.assertEqual([p.created_with for p in pwm], [0, 0, 0])
        led, pwm = make_led("anode")
        self.assertEqual([p.created_with for p in pwm], [65535, 65535, 65535])  # inverted: high is dark

    def test_cathode_duty_follows_brightness(self):
        led, pwm = make_led()
        led.set(255, 0, 128)
        self.assertEqual(pwm[0].duty, 65535)
        self.assertEqual(pwm[1].duty, 0)
        self.assertTrue(0 < pwm[2].duty < 65535 // 2)  # gamma: half brightness is well under half duty
        led.off()
        self.assertEqual([p.duty for p in pwm], [0, 0, 0])

    def test_anode_duty_is_inverted(self):
        led, pwm = make_led("anode")
        led.set(255, 0, 0)
        self.assertEqual([p.duty for p in pwm], [0, 65535, 65535])  # red pin low = red on
        led.off()
        self.assertEqual([p.duty for p in pwm], [65535, 65535, 65535])

    def test_gamma_table_is_monotonic_and_spans_the_range(self):
        led, pwm = make_led()
        duties = []
        for v in range(256):
            led._last = None
            led.set(v, 0, 0)
            duties.append(pwm[0].duty)
        self.assertEqual((duties[0], duties[255]), (0, 65535))
        self.assertEqual(duties, sorted(duties))
        self.assertGreater(len(set(duties)), 200)

    def test_unchanged_colours_cost_no_writes(self):
        led, pwm = make_led()
        led.set(10, 20, 30)
        n = [p.writes for p in pwm]
        led.set(10, 20, 30)
        self.assertEqual([p.writes for p in pwm], n)
        led.set(10, 20, 31)
        self.assertGreater(pwm[2].writes, n[2])

    def test_out_of_range_and_float_values_are_clamped(self):
        led, pwm = make_led()
        led.set(-5, 999, 12.7)
        self.assertEqual(pwm[0].duty, 0)
        self.assertEqual(pwm[1].duty, 65535)
        self.assertTrue(0 < pwm[2].duty < 65535)

    def test_bad_common_setting_is_refused(self):
        for bad in ("cathod", "", None, "ANODE", 1):
            with self.assertRaises(ValueError, msg=repr(bad)):
                hw_led.RGBLed(PINS, bad, make_pwm=lambda g, d: FakePWM(g, d))

    def test_missing_pin_is_an_error(self):
        with self.assertRaises(KeyError):
            hw_led.RGBLed({"R": 13, "G": 14}, make_pwm=lambda g, d: FakePWM(g, d))

    def test_deinit_turns_it_off_and_releases_the_pins(self):
        led, pwm = make_led()
        led.set(255, 255, 255)
        led.deinit()
        self.assertEqual([p.duty for p in pwm], [0, 0, 0])
        self.assertTrue(all(p.deinited for p in pwm))


class UsbSense(unittest.TestCase):
    """The plugged-in symbol: where the board says whether USB is connected."""

    class Cfg:
        USB_SENSE_PIN = "WL_GPIO2"

    def test_a_string_pin_is_passed_straight_through_for_the_w_boards(self):
        seen = []

        class Pin:
            def __init__(self, n):
                seen.append(n)

            def value(self):
                return 1
        sense = pico_main.make_usb_sense(self.Cfg, make_pin=Pin)
        self.assertEqual(seen, ["WL_GPIO2"])
        self.assertEqual(sense(), 1)

    def test_a_number_pin_works_for_the_plain_boards(self):
        class Cfg:
            USB_SENSE_PIN = 24
        seen = []

        class Pin:
            def __init__(self, n):
                seen.append(n)

            def value(self):
                return 0
        self.assertEqual(pico_main.make_usb_sense(Cfg, make_pin=Pin)(), 0)
        self.assertEqual(seen, [24])

    def test_none_or_missing_turns_it_off(self):
        class NoPin:
            USB_SENSE_PIN = None
        class Unset:
            pass
        self.assertIsNone(pico_main.make_usb_sense(NoPin))
        self.assertIsNone(pico_main.make_usb_sense(Unset))

    def test_a_pin_that_cannot_be_made_disables_it_and_says_so(self):
        said = []

        def boom(n):
            raise ValueError("no such pin")
        self.assertIsNone(pico_main.make_usb_sense(self.Cfg, make_pin=boom, out=said.append))
        self.assertTrue(any("USB sense disabled" in s for s in said))

    def test_the_config_names_a_pin_the_pico_2_w_has(self):
        import pico_config
        self.assertEqual(pico_config.USB_SENSE_PIN, "WL_GPIO2")

    def test_the_loop_follows_the_pin_into_the_status(self):
        L = Loop("test_runs_for_the_requested_time_and_feeds_everything")
        L.build()
        level = [0]

        def go(ms):
            def sleep(n):
                L.rig.clock.advance(n)
            L.led.t = [0]
            pico_main._run_loop(L.rig, L.rig.clock, L.display, L.led, L.buttons, L.reader, L.console,
                                L.view, L.Cfg, ms, sleep, L.out.append, usb_sense=lambda: level[0])
        go(300)
        self.assertFalse(L.rig.ui.screen()["status"]["usb"])
        level[0] = 1
        go(300)
        self.assertTrue(L.rig.ui.screen()["status"]["usb"])
        level[0] = 0
        go(300)
        self.assertFalse(L.rig.ui.screen()["status"]["usb"])


class DevStopLoop(unittest.TestCase):
    def test_the_loop_ends_shows_stopped_and_leaves_the_led_off(self):
        L = Loop("test_runs_for_the_requested_time_and_feeds_everything")
        L.build()
        ticks = [0]

        def sleep(n):
            ticks[0] += n
            L.rig.clock.advance(n)
            if ticks[0] >= 500:
                L.rig.stop_requested = True  # what a held `libra dev stop` does
        L.led.t = [0]
        pico_main._run_loop(L.rig, L.rig.clock, L.display, L.led, L.buttons, L.reader, L.console, L.view, L.Cfg,
                            60000, sleep, L.out.append)  # would run a minute if it were not stopped
        self.assertLess(ticks[0], 2000)
        self.assertEqual(L.display.frames[-1][0].strip(), "Stopped")
        self.assertIn("libra dev start", L.display.frames[-1][1])
        self.assertEqual(L.led.calls[-1][1], "off")
        self.assertTrue(any("stopped by request" in o for o in L.out))


if __name__ == "__main__":
    unittest.main()
