# hw_lcd.py - HD44780 16x2 character LCD behind a PCF8574 I2C backpack (4-bit mode)
#
# Backpack wiring (the common one): P0=RS, P1=RW (held low), P2=EN, P3=backlight, P4..P7=D4..D7.
# Address is usually 0x27 (PCF8574) or 0x3F (PCF8574A). Written from the HD44780 datasheet's
# 4-bit initialisation; no third-party driver.
#
# Power note: the backpack's I2C pull-ups may go to its supply. From 5 V they would pull SDA/SCL
# to 5 V, which the Pico's 3.3 V pins do not tolerate. Check before connecting.

import lb_lcd

_RS = 0x01
_EN = 0x04
_BL = 0x08
_ROW_ADDR = (0x00, 0x40, 0x14, 0x54)


def _default_sleeps():
    import time
    return time.sleep_us, time.sleep_ms


class HD44780:
    """The controller's command set and 4-bit start-up, shared by both wirings. A subclass
    provides _latch(nibble, rs) (put one nibble on the bus and pulse E) and _prepare()."""

    def __init__(self, cols=16, rows=2, sleep_us=None, sleep_ms=None):
        if sleep_us is None:
            sleep_us, sleep_ms = _default_sleeps()
        self._us = sleep_us
        self._ms = sleep_ms
        self._cols = cols
        self._rows = rows
        self._shadow = [None] * rows
        self._init()

    def _byte(self, v, rs):
        self._latch(v >> 4, rs)
        self._latch(v & 0x0F, rs)

    def _command(self, c):
        self._byte(c, 0)
        if c in (0x01, 0x02):
            self._ms(3)  # clear and home are slow

    def _init(self):
        self._ms(50)
        self._prepare()
        for wait in (5, 5, 1):
            self._latch(0x03, 0)  # wake-up handshake, 8-bit mode three times
            self._ms(wait)
        self._latch(0x02, 0)  # then switch to 4-bit
        self._us(150)
        self._command(0x28)  # 4-bit, two lines, 5x8 font
        self._command(0x08)  # display off
        self._command(0x01)  # clear
        self._command(0x06)  # cursor moves right, no shift
        self._command(0x0C)  # display on, cursor off, no blink
        self._load_glyphs()

    def _load_glyphs(self):
        """Draw lb_lcd.GLYPHS into the module's custom character slots 0, 1, ..."""
        for slot, rows in enumerate(lb_lcd.GLYPHS):
            self._command(0x40 | (slot << 3))  # CGRAM address
            for r in rows:
                self._byte(r, _RS)
        self._command(0x80)  # back to the display

    def write_line(self, row, text):
        text = lb_lcd.fit(text, self._cols)
        if self._shadow[row] == text:
            return  # unchanged: skip the slow bus traffic
        self._command(0x80 | _ROW_ADDR[row])
        for ch in text:
            self._byte(ord(ch), _RS)
        self._shadow[row] = text

    def show(self, line1, line2):
        self.write_line(0, line1)
        self.write_line(1, line2)

    def backlight(self, on):
        pass

    def sleep(self, asleep):
        """Blank (or restore) the characters. The text stays in the module's memory, so waking
        needs no redraw. An I2C backpack also switches its backlight; a bare parallel module's
        backlight is wired to power, so only the characters go dark."""
        self._command(0x08 if asleep else 0x0C)
        self.backlight(not asleep)


class LCD(HD44780):
    """Through a PCF8574 I2C backpack."""

    def __init__(self, i2c, addr, cols=16, rows=2, sleep_us=None, sleep_ms=None):
        self._i2c = i2c
        self._addr = addr
        self._bl = _BL
        HD44780.__init__(self, cols, rows, sleep_us, sleep_ms)

    def _prepare(self):
        self._i2c.writeto(self._addr, bytes([self._bl]))

    def _latch(self, nib, rs):
        d = ((nib & 0x0F) << 4) | rs | self._bl
        self._i2c.writeto(self._addr, bytes([d | _EN, d]))  # EN high then low: data latches
        self._us(60)

    def backlight(self, on):
        self._bl = _BL if on else 0
        self._i2c.writeto(self._addr, bytes([self._bl]))


class ParallelLCD(HD44780):
    """Straight to the module's pins in 4-bit mode: RS, E and D4..D7 on six GPIOs.
    RW (module pin 5) must be tied to GND: this driver only ever writes, so the module never
    drives its (possibly 5 V) outputs back into the Pico. D0..D3 stay unconnected."""

    def __init__(self, rs, e, d4, d5, d6, d7, cols=16, rows=2, sleep_us=None, sleep_ms=None):
        self._rs = rs
        self._e = e
        self._d = (d4, d5, d6, d7)
        HD44780.__init__(self, cols, rows, sleep_us, sleep_ms)

    def _prepare(self):
        self._e.value(0)
        self._rs.value(0)
        for p in self._d:
            p.value(0)

    def _latch(self, nib, rs):
        self._rs.value(rs)
        for i, p in enumerate(self._d):
            p.value((nib >> i) & 1)
        self._us(2)       # data and RS settle before E rises
        self._e.value(1)
        self._us(2)       # E high at least 450 ns
        self._e.value(0)  # data is latched on this falling edge
        self._us(60)      # most commands take under 40 us


def make_parallel(pins, make_pin=None, **kw):
    """pins: {"RS": gpio, "E": gpio, "D4": gpio, "D5": gpio, "D6": gpio, "D7": gpio}."""
    if make_pin is None:
        import machine

        def make_pin(n):
            return machine.Pin(n, machine.Pin.OUT, value=0)
    p = [make_pin(pins[k]) for k in ("RS", "E", "D4", "D5", "D6", "D7")]
    return ParallelLCD(*p, **kw)


class TextDisplay:
    """Fallback when no LCD answers: print the two lines in the shell when they change."""

    def __init__(self, out=print):
        self._out = out
        self._last = None

    def show(self, line1, line2):
        if (line1, line2) != self._last:
            self._last = (line1, line2)
            self._out("[%s]\n[%s]" % (lb_lcd.printable(line1), lb_lcd.printable(line2)))
