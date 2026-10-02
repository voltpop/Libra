# hw_buttons.py - debounced push buttons wired to GND (internal pull-ups, pressed = low)

import lb_ticks

DEBOUNCE_MS = 20


def _default_pin(n):
    import machine
    return machine.Pin(n, machine.Pin.IN, machine.Pin.PULL_UP)


class Buttons:
    """pins: {"UP": gpio_number_or_None, ...}. A button reports a change only after the level
    has been stable for DEBOUNCE_MS; poll() every few milliseconds. on_event(name, down)."""

    def __init__(self, pins, ticks, on_event, make_pin=None, debounce_ms=DEBOUNCE_MS):
        make_pin = make_pin or _default_pin
        self._ticks = ticks
        self._on = on_event
        self._db = debounce_ms
        self._b = []  # [name, pin, raw, since, stable]
        now = ticks()
        for name, num in pins.items():
            if num is not None:
                self._b.append([name, make_pin(num), False, now, False])

    def poll(self):
        now = self._ticks()
        for b in self._b:
            level = b[1].value() == 0
            if level != b[2]:
                b[2] = level
                b[3] = now
            elif level != b[4] and lb_ticks.diff(now, b[3]) >= self._db:
                b[4] = level
                self._on(b[0], level)

    def count(self):
        return len(self._b)
