# hw_led.py - a 4-pin RGB LED on three PWM pins (one resistor per colour leg, common pin shared)
#
# common="cathode": the long leg goes to GND, so a higher duty is brighter.
# common="anode":   the long leg goes to 3V3, so the duty is inverted (a low pin lights the colour).
# If red shows as cyan (colours inverted) or the LED is bright when it should be dark, the setting
# is the other one. Each colour leg needs a series resistor (about 220 to 330 ohm at 3.3 V).

NAMES = ("R", "G", "B")
FULL = 65535
GAMMA = 2.2  # the eye is not linear: this makes the fades and the breathing look even


def _default_pwm(gpio, duty):
    import machine
    return machine.PWM(machine.Pin(gpio), freq=1000, duty_u16=duty)


class RGBLed:
    def __init__(self, pins, common="cathode", make_pwm=None):
        if common not in ("cathode", "anode"):
            raise ValueError("common must be 'cathode' or 'anode'")
        self._inv = common == "anode"
        self._table = [int(((i / 255) ** GAMMA) * FULL + 0.5) for i in range(256)]
        make = make_pwm or _default_pwm
        dark = FULL if self._inv else 0  # created already dark, so it never flashes on at start-up
        self._pwm = [make(pins[n], dark) for n in NAMES]
        self._last = None

    def _duty(self, v):
        d = self._table[max(0, min(255, int(v)))]
        return FULL - d if self._inv else d

    def set(self, r, g, b):
        rgb = (int(r), int(g), int(b))
        if rgb == self._last:
            return  # nothing changed: skip the PWM writes
        self._last = rgb
        for pwm, v in zip(self._pwm, rgb):
            pwm.duty_u16(self._duty(v))

    def off(self):
        self.set(0, 0, 0)

    def deinit(self):
        self.off()
        for pwm in self._pwm:
            try:
                pwm.deinit()
            except Exception:
                pass
