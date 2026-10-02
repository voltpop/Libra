# pico_main.py - interim hardware UI test rig: real UI model + 16x2 LCD + buttons + console
#
# Copy every lb_*.py, ucompat.py and the files in pico/ to the board's root, then either run this
# file from Thonny (type console commands in its shell) or save it as main.py to start at power-up.
#
#   import pico_main; pico_main.run()        # the rig (run(3000) stops after 3 s)
#   import pico_main; pico_main.selftest()   # scripted check of the wiring, no LCD or buttons needed
#   import pico_main; pico_main.lcd_test()   # patterns on the display
#   import pico_main; pico_main.button_test()  # press each button; reports any it never saw (shell only)
#   import pico_main; pico_main.hwtest_all() # EVERYTHING: LCD, LED, buttons (add new stages to HW_STAGES)
#   import pico_main; pico_main.hwtest()      # interactive: the LCD shows each button as you press it
#   import pico_main; pico_main.led_test()    # off, red, green, blue, white: check the LED wiring
#   import pico_main; pico_main.led_demo()    # plays every LED state once, labelled
#
# Everything is simulated except the display, buttons and clock: the keystore, fingerprint and
# OATH store are RAM fakes with demo accounts. Do not put real secrets on this.

import sys

import lb_console
import lb_hwtest
import lb_lcd
import lb_led
import lb_sleep
import lb_ticks
from lb_rig import Rig

EPOCH_2000 = 946684800  # MicroPython on the Pico counts seconds from 2000-01-01


class PicoClock:
    """Same interface as lb_fakes.SimClock, on the Pico's real timers. Not trusted until the
    time is set (console: `time demo` or `time <unix>`), as the real device will behave."""

    def __init__(self, ticks_ms, time_s, epoch_offset=EPOCH_2000):
        self._ticks_ms = ticks_ms
        self._time_s = time_s
        self._off = epoch_offset
        self._warp = 0
        self._delta = 0
        self.trusted_flag = False

    def ticks(self):
        return (self._ticks_ms() + self._warp) % lb_ticks.PERIOD

    __call__ = ticks

    def advance(self, ms):
        self._warp += ms

    def trusted(self):
        return self.trusted_flag

    def now(self):
        return self._time_s() + self._off + self._delta + self._warp // 1000

    def set_unix(self, u):
        self._delta += u - self.now()


def _make_clock():
    import time
    return PicoClock(time.ticks_ms, time.time)


class LineReader:
    """Non-blocking line input from stdin (Thonny shell or mpremote)."""

    MAX = 160

    def __init__(self):
        import select
        self._poll = select.poll()
        self._poll.register(sys.stdin, select.POLLIN)
        self._buf = ""

    def read(self):
        while self._poll.poll(0):
            ch = sys.stdin.read(1)
            if not ch:
                return None
            if ch in "\r\n":
                line, self._buf = self._buf, ""
                if line:
                    return line
            elif len(self._buf) < self.MAX:
                self._buf += ch
        return None


def make_display(cfg, out=print, i2c=None, make_pin=None):
    """The display chosen by cfg.LCD_MODE. A parallel module cannot be detected (it is write-only),
    so only I2C reports what it found; any failure falls back to printing in the shell."""
    import hw_lcd
    mode = getattr(cfg, "LCD_MODE", "text")
    if mode == "parallel":
        try:
            lcd = hw_lcd.make_parallel(cfg.LCD_PINS, make_pin)
            out("LCD: parallel on GP%s" % ", GP".join(str(cfg.LCD_PINS[k]) for k in (
                "RS", "E", "D4", "D5", "D6", "D7")))
            return lcd
        except Exception as e:
            out("Parallel LCD failed (%s). Printing the two lines here instead." % (e,))
            return hw_lcd.TextDisplay(out)
    if mode == "i2c":
        try:
            if i2c is None:
                import machine
                i2c = machine.I2C(cfg.I2C_ID, sda=machine.Pin(cfg.SDA), scl=machine.Pin(cfg.SCL),
                                  freq=cfg.I2C_FREQ)
            found = i2c.scan()
        except OSError:
            found = []
        for addr in cfg.LCD_ADDRS:
            if addr in found:
                out("LCD at 0x%02X" % addr)
                return hw_lcd.LCD(i2c, addr)
        out("No LCD answered (I2C scan: %s). Printing the two lines here instead." % (
            [hex(a) for a in found],))
        return hw_lcd.TextDisplay(out)
    return hw_lcd.TextDisplay(out)


def make_led(cfg, out=print):
    """The RGB LED from cfg, or None if it is not configured or cannot be set up."""
    pins = getattr(cfg, "LED_PINS", None)
    if not pins:
        return None
    try:
        import hw_led
        return hw_led.RGBLed(pins, getattr(cfg, "LED_COMMON", "cathode"))
    except Exception as e:
        out("LED disabled: %s" % (e,))
        return None


def run(max_ms=None, unix=None):
    """The rig. max_ms stops it after that long (None runs forever). unix sets the clock at start
    (pico_main.run(unix=1790946000), from `date +%s` on your computer) so no typing is needed."""
    import time

    import hw_buttons
    import hw_lcd
    import pico_config as cfg

    display = make_display(cfg)
    led = make_led(cfg)
    clock = _make_clock()
    rig = Rig(clock=clock)
    if unix is not None:
        clock.set_unix(int(unix))
        clock.trusted_flag = True
    console = lb_console.Console(rig, notes_path=cfg.NOTES_PATH, direct=False)
    sleeper = lb_sleep.IdleSleep(getattr(cfg, "IDLE_SLEEP_MS", 0))

    def on_button(n, d):
        if sleeper.button(n, d, clock.ticks()):
            rig.ui.button(n, d)
        elif d:
            rig.session.activity()  # the waking press counts, so the idle lock does not fire right behind it
    buttons = hw_buttons.Buttons(cfg.BUTTONS, clock.ticks, on_button)
    view = lb_lcd.LcdView(marquee=not isinstance(display, hw_lcd.TextDisplay))
    reader = LineReader()
    print("Libra interim UI rig. %d buttons configured. Combo: U D L R U D L R U D." % buttons.count())
    print("Clock: %s" % ("set to %s UTC" % lb_console.utc_text(clock.now()) if unix is not None
                         else "NOT set. Type `time demo` or `time <unix>` here, or restart with run(unix=...)"))
    print("Type commands in this shell while it runs, for example `status` or `help`.")
    _run_loop(rig, clock, display, led, buttons, reader, console, view, cfg, max_ms, time.sleep_ms,
              sleeper=sleeper, usb_sense=make_usb_sense(cfg))


def make_usb_sense(cfg, make_pin=None, out=print):
    """A callable that says whether USB is plugged in, from the board's VBUS sense pin, or None.
    On a Pico / Pico 2 that is GP24; on a Pico W / Pico 2 W it is the radio chip's "WL_GPIO2"
    (a string). USB_SENSE_PIN may be either, or None to turn it off."""
    pin = getattr(cfg, "USB_SENSE_PIN", None)
    if pin is None:
        return None
    try:
        if make_pin is None:
            import machine

            def make_pin(n):
                return machine.Pin(n, machine.Pin.IN)
        return make_pin(pin).value
    except Exception as e:
        out("USB sense disabled: %s" % (e,))
        return None


def _run_loop(rig, clock, display, led, buttons, reader, console, view, cfg, max_ms, sleep_ms,
              out=print, sleeper=None, usb_sense=None):
    """The rig's main loop, with every part passed in so it can be tested without hardware."""
    started = last_draw = last_led = clock.ticks()
    errors = 0
    dark = False
    try:
        while max_ms is None or lb_ticks.diff(clock.ticks(), started) < max_ms:
            if getattr(rig, "stop_requested", False):  # a held `libra dev stop`: end the program
                display.show(lb_lcd.fit("Stopped"), lb_lcd.fit("libra dev start"))
                out("stopped by request (hold PTT on `libra dev stop`)")
                break
            try:
                buttons.poll()
                line = reader.read()
                if line:
                    if sleeper is not None:
                        sleeper.activity(clock.ticks())
                    console.handle(line)
                console.tick()
                if usb_sense is not None:
                    rig.usb = bool(usb_sense())
                rig.ui.tick()
                now = clock.ticks()
                if sleeper is not None:
                    asleep = sleeper.update(now, rig.ui.screen())
                    if asleep != dark:  # going dark or waking: switch the display and LED once
                        dark = asleep
                        if dark:
                            display.show(lb_lcd.fit(""), lb_lcd.fit(""))
                            if led is not None:
                                led.off()
                        last_draw = last_led = now - 10000  # redraw everything on waking
                        if hasattr(display, "sleep"):
                            display.sleep(dark)
                if not dark:
                    if lb_ticks.diff(now, last_led) >= getattr(cfg, "LED_REFRESH_MS", 25):
                        last_led = now
                        if led is not None:
                            led.set(*rig.led.color(now, rig.ui.screen()))
                    if lb_ticks.diff(now, last_draw) >= cfg.LCD_REFRESH_MS:
                        last_draw = now
                        display.show(*view.lines(rig.ui.screen(), now))
                errors = 0
            except KeyboardInterrupt:
                display.show(lb_lcd.fit("Stopped"), lb_lcd.fit(""))
                out("stopped")
                break
            except Exception as e:  # report, stay alive; give up if it keeps failing
                errors += 1
                if hasattr(sys, "print_exception"):
                    sys.print_exception(e)
                else:
                    out("error: %r" % (e,))
                if errors > 20:
                    raise
                sleep_ms(500)
            sleep_ms(5)
    finally:
        if led is not None:
            led.off()  # never leave it lit when the rig stops


def lcd_test(hold_s=6, out=print, sleep_ms=None, display=None):
    """Put patterns on the display so you can check wiring and contrast by eye."""
    import time

    import pico_config as cfg
    sleep_ms = sleep_ms or time.sleep_ms  # this MicroPython has no time.sleep
    d = display if display is not None else make_display(cfg, out)
    screens = (
        ("Libra LCD test", "0123456789ABCDEF"),
        ("abcdefghijklmnop", "!\"#$%&'()*+,-./:"),
        ("################", "................"),
        ("Row 1 is here   ", "Row 2 is here   "),
    )
    for l1, l2 in screens:
        d.show(l1, l2)
        out("showing: [%s] / [%s]" % (l1, l2))
        sleep_ms(int(hold_s * 1000))
    d.show("LCD test done", "")
    out("done")


def button_test(seconds=20, out=print, make_pin=None, ticks=None, sleep_ms=None):
    """Press each button during the window; prints what it sees and what it never saw."""
    import time

    import hw_buttons
    import pico_config as cfg
    ticks = ticks or time.ticks_ms
    sleep_ms = sleep_ms or time.sleep_ms
    seen = {}

    def on(name, down):
        if down:
            seen[name] = seen.get(name, 0) + 1
        out("%-6s %s  (GP%d)" % (name, "DOWN" if down else "up  ", cfg.BUTTONS[name]))

    b = hw_buttons.Buttons(cfg.BUTTONS, ticks, on, make_pin)
    out("Press every button once in the next %d s..." % seconds)
    t0 = ticks()
    while lb_ticks.diff(ticks(), t0) < seconds * 1000:
        b.poll()
        sleep_ms(2)
    wired = [n for n, p in cfg.BUTTONS.items() if p is not None]
    missing = [n for n in wired if n not in seen]
    out("seen: %s" % (sorted(seen) or "nothing"))
    out("never pressed: %s" % (missing or "none: all %d buttons work" % len(wired)))
    return not missing


def hwtest(timeout_s=180, out=print, make_pin=None, ticks=None, sleep_ms=None, display=None):
    """Interactive hardware test. The LCD shows each button as you press it (and how long you hold
    it), with progress n/7. Ends when all buttons have been seen, on timeout, or on Ctrl-C.
    Returns True if every wired button was seen."""
    import time

    import hw_buttons
    import pico_config as cfg
    ticks = ticks or time.ticks_ms
    sleep_ms = sleep_ms or time.sleep_ms
    names = [n for n in lb_hwtest.ORDER if cfg.BUTTONS.get(n) is not None]
    test = lb_hwtest.HwTest(names)
    display = display or make_display(cfg, out)

    def on(name, down):
        test.button(name, down, ticks())
        out("%-6s %s  (GP%d)" % (name, "DOWN" if down else "up  ", cfg.BUTTONS[name]))

    b = hw_buttons.Buttons(cfg.BUTTONS, ticks, on, make_pin)
    out("Button test: press each of %d buttons. Ctrl-C to stop." % len(names))
    t0 = last = ticks()
    display.show(*test.lines(t0))
    stopped = False
    try:
        while lb_ticks.diff(ticks(), t0) < timeout_s * 1000 and not test.finished(ticks()):
            b.poll()
            now = ticks()
            if lb_ticks.diff(now, last) >= 60:
                last = now
                display.show(*test.lines(now))
            sleep_ms(2)
    except KeyboardInterrupt:  # Thonny's Stop button
        stopped = True
        out("stopped")
    missing = test.missing()
    if stopped:
        display.show(lb_lcd.fit("Stopped"), lb_lcd.fit("seen %d/%d" % (len(test.seen()), len(names))))
        if missing:
            out("never pressed: %s" % " ".join(missing))
    elif missing:
        out("never pressed: %s" % " ".join(missing))
        marquee = lb_lcd.Marquee()
        end = ticks()
        while lb_ticks.diff(ticks(), end) < 6000:  # let the missing list scroll on the display
            display.show(lb_lcd.fit("Missing %d/%d" % (len(missing), len(names))),
                         marquee.view(" ".join(missing), ticks()))
            sleep_ms(60)
    else:
        out("all %d buttons work" % len(names))
        display.show(lb_lcd.fit("ALL %d OK!" % len(names)), lb_lcd.fit("Test complete"))
    return not missing


def _stage_lcd(ctx):
    lcd_test(hold_s=2, out=ctx["out"], sleep_ms=ctx["sleep_ms"], display=ctx["display"])
    return None  # judged by eye


def _stage_led(ctx):
    d, out = ctx["display"], ctx["out"]

    def say(msg):
        out(msg)
        d.show(lb_lcd.fit("LED test"), lb_lcd.fit(msg.split(":")[0]))
    return led_test(hold_s=1.5, out=say, sleep_ms=ctx["sleep_ms"], led=ctx["led"]) or False


def _stage_buttons(ctx):
    return hwtest(ctx["timeout_s"], ctx["out"], ctx["make_pin"], ctx["ticks"], ctx["sleep_ms"],
                  ctx["display"])


# Add new hardware checks here: (name, function(ctx) -> True pass / False fail / None "judge by eye").
HW_STAGES = (("lcd", _stage_lcd), ("led", _stage_led), ("buttons", _stage_buttons))


def hwtest_all(stages=None, timeout_s=180, out=print, make_pin=None, ticks=None, sleep_ms=None,
               display=None, led=None):
    """Every hardware check in turn: LCD patterns, the RGB LED, then the buttons (press each one).
    `stages` is an optional list of names from HW_STAGES to run just those. Prints a summary and
    returns True if no stage failed; stages judged by eye count as "look" rather than pass/fail."""
    import time

    import pico_config as cfg
    ctx = {"out": out, "timeout_s": timeout_s, "make_pin": make_pin,
           "ticks": ticks or time.ticks_ms, "sleep_ms": sleep_ms or time.sleep_ms}
    ctx["display"] = display or make_display(cfg, out)
    ctx["led"] = led if led is not None else make_led(cfg, out)
    results = []
    for name, fn in HW_STAGES:
        if stages is not None and name not in stages:
            continue
        out("== %s ==" % name)
        try:
            r = fn(ctx)
        except KeyboardInterrupt:
            out("stopped")
            results.append((name, False))
            break
        except Exception as e:
            out("%s stage crashed: %r" % (name, e))
            r = False
        results.append((name, r))
    if ctx["led"] is not None:
        ctx["led"].off()
    out("== summary ==")
    for name, r in results:
        out("%-8s %s" % (name, "look" if r is None else "PASS" if r else "FAIL"))
    ok = all(r is not False for _, r in results)
    ctx["display"].show(lb_lcd.fit("HW test " + ("done" if ok else "FAILED")), lb_lcd.fit(""))
    return ok


def led_test(hold_s=1.5, out=print, sleep_ms=None, led=None):
    """Show off, red, green, blue and white in turn so you can check the wiring by eye."""
    import time

    import pico_config as cfg
    sleep_ms = sleep_ms or time.sleep_ms
    led = led if led is not None else make_led(cfg, out)
    if led is None:
        out("no LED configured (set LED_PINS in pico_config.py)")
        return False
    steps = (("OFF: it should be dark. If it is lit, set LED_COMMON to the other value", 0, 0, 0),
             ("RED", 200, 0, 0), ("GREEN", 0, 200, 0), ("BLUE", 0, 0, 200), ("WHITE", 200, 200, 200))
    try:
        for label, r, g, b in steps:
            out(label)
            led.set(r, g, b)
            sleep_ms(int(hold_s * 1000))
    finally:
        led.off()
    out("done. Wrong order? swap the pins in LED_PINS. Colours inverted? flip LED_COMMON.")
    return True


def led_demo(out=print, sleep_ms=None, ticks=None, led=None):
    """Play every LED state once, with a label, so you can learn the palette."""
    import time

    import pico_config as cfg
    led = led if led is not None else make_led(cfg, out)
    if led is None:
        out("no LED configured (set LED_PINS in pico_config.py)")
        return False
    sleep_ms = sleep_ms or time.sleep_ms
    ticks = ticks or time.ticks_ms
    eng = lb_led.LedEngine()
    state = {"seq": 0, "kind": None}

    def screen(sid="Idle", locked=False, hold=None, code=False):
        return {"id": sid, "status": {"locked": locked}, "hold": hold,
                "haptic": {"seq": state["seq"], "kind": state["kind"]},
                "body": {"code": "123 456"} if code else {}}

    def show(label, ms, make):
        out(label)
        t0 = ticks()
        while lb_ticks.diff(ticks(), t0) < ms:
            now = ticks()
            led.set(*eng.color(now, make(lb_ticks.diff(now, t0))))
            sleep_ms(20)

    def cue(kind):
        state["seq"] += 1
        state["kind"] = kind
        show("cue: " + kind, lb_led.cue_length(kind) + 700, lambda e: screen())

    try:
        eng.color(ticks(), screen())
        show("powered, unlocked: dim steady blue", 2000, lambda e: screen())
        show("locked: blue breathing", 4000, lambda e: screen("Locked", locked=True))
        show("waiting for PTT: sweeps green and blue", 3000, lambda e: screen("SetTime"))
        show("PTT hold filling: blue turns to green", 2000, lambda e: screen(hold=max(1, e // 2)))
        for k in ("commit", "success", "error", "tap", "abort", "notify"):
            cue(k)
        show("a code on screen: steady purple", 2000, lambda e: screen("TOTPCode", code=True))
        show("wiped: solid red", 2000, lambda e: screen("Wiped", locked=True))
    finally:
        led.off()
    out("done")
    return True


def selftest(out=print):
    """Drive the real UI with the real clock and no hardware. Returns True when all checks pass."""
    import time
    clock = _make_clock()
    rig = Rig(clock=clock)
    con = lb_console.Console(rig, out=lambda s: None)
    results = []

    def run_for(ms):
        end = time.ticks_add(time.ticks_ms(), ms)
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            con.tick()
            rig.ui.tick()
            time.sleep_ms(5)

    def check(name, cond):
        results.append(bool(cond))
        out("%s  %s" % ("PASS" if cond else "FAIL", name))

    def screen():
        return rig.ui.screen()

    check("boots Locked", screen()["id"] == "Locked")
    con.handle("unlock")
    run_for(50)
    check("combo unlocks to Idle", screen()["id"] == "Idle")
    con.handle("press d 60")
    run_for(150)
    con.handle("press s 60")
    run_for(150)
    check("push to show: a code needs a hold first", screen()["id"] == "RevealPrompt")
    con.handle("down p")
    run_for(700)
    con.handle("up p")
    run_for(150)
    check("clock not set: TOTP refused with a notice", screen()["lines"] == ["Set the clock first"])
    con.handle("time demo")
    con.handle("press b 60")
    run_for(150)
    con.handle("press s 60")
    run_for(150)
    con.handle("down p")
    run_for(700)
    check("holding PTT shows a code", screen()["id"] == "TOTPCode")
    check("code is 6 digits plus a space", len(screen()["body"]["code"]) == 7)
    con.handle("up p")
    run_for(150)
    check("releasing PTT hides it again", screen()["id"] == "RevealPrompt")
    con.handle("host sign")
    run_for(100)
    check("host request screen appears", screen()["id"] == "HostRequest")
    con.handle("press p 600")
    run_for(900)
    check("0.6 s hold does not approve a signature", rig.session.pending() is not None)
    con.handle("press p 1800")
    run_for(2200)
    check("1.8 s hold approves it", rig.session.pending() is None and screen()["lines"] == ["Approved"])
    con.handle("warp 61000")
    run_for(1300)
    check("idle timeout locks", screen()["id"] == "Locked")
    check("lcd lines are 16 wide", all(len(x) == 16 for x in lb_lcd.LcdView().lines(screen(), clock.ticks())))
    ok = all(results)
    out("selftest %s (%d/%d)" % ("PASSED" if ok else "FAILED", sum(results), len(results)))
    return ok
