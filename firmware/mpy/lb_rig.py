# lb_rig.py - the real session/oath/hold/UI modules wired to the simulated drivers
#
# One place that assembles the host build, shared by the scenario tests and the browser
# simulator. boot() is a simulated power cycle: new RAM objects over the same persistent
# stores (attempt counter, OATH records), so lockout delays and accounts carry over.

import lb_fakes
import lb_hold
import lb_led
import lb_oath
import lb_session
import lb_settings
import lb_ui

DEMO_ACCOUNTS = (
    dict(issuer="GitHub", account="alice", secret="JBSWY3DPEHPK3PXP"),
    dict(issuer="Example Bank", account="alice@example.com", secret="GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
         alg=lb_oath.SHA256, digits=8, period=60),
    dict(issuer="VPN", account="alice", secret="OZYG4LLEMVWW6LLTMVRXEZLUFUYDAMBR", type=lb_oath.HOTP),
    dict(issuer="Work Vault", account="alice", secret="JBSWY3DPEHPK3PXP", reveal_requires_hold=True),
)


class Rig:
    def __init__(self, real_clock=False, seed=True, durations=None, clock=None, push_to_show=True):
        self.stop_requested = False  # developer stop: set by a held proposal, read by the board's loop
        self.clock = clock if clock is not None else lb_fakes.SimClock(real=real_clock)
        self.ks = lb_fakes.MemKeystore()
        self.store = lb_fakes.MemOathStore()
        self.settings_store = lb_fakes.MemSettingsStore()
        self.fp = lb_fakes.FakeFP("match")
        self.haptic = lb_fakes.Haptic()
        self.led = lb_led.LedEngine()
        self._durations = durations
        self.boot()
        if not push_to_show:  # tests of other features turn it off; the device default is ON
            self.settings.set("push_to_show", False, approved=True)
            self.oath.set_reveal_all(False)
        if seed:
            self._seed()

    def _request_stop(self):
        self.stop_requested = True  # the loop that drives the rig watches this

    def _set_console_rw(self, on):
        self.console_rw = bool(on)

    def _set_time(self, unix):
        self.clock.set_unix(unix)
        self.clock.trusted_flag = True

    def _seed(self):
        for a in DEMO_ACCOUNTS:
            self.oath.add(lb_oath.Entry(**a), approved=True)

    def reset(self):
        """Factory reset: empty stores, fresh counters, demo accounts again."""
        self.ks = lb_fakes.MemKeystore()
        self.store = lb_fakes.MemOathStore()
        self.settings_store = lb_fakes.MemSettingsStore()
        self.boot()
        self._seed()

    def boot(self):
        self.ble = getattr(self, "ble", False)  # BLE on? nothing drives it yet; the console fakes it
        self.usb = getattr(self, "usb", False)  # plugged in? the real board reads VBUS; the console fakes it
        self.console_rw = False  # the console is read-only again after any restart or reset
        self.session = lb_session.Session(self.ks, self.clock.ticks, fp=self.fp)
        self.oath = lb_oath.Oath(self.store, self.clock)
        self.engine = lb_hold.HoldEngine(self._durations)
        self.settings = lb_settings.Settings(self.settings_store)
        self.led.reset()
        self.ui = lb_ui.UI(self.session, self.oath, self.engine, self.clock.ticks, self.clock,
                           haptic=self.haptic, settings=self.settings, set_time=self._set_time,
                           factory_reset=self.reset, restart=self.boot, console_rw=self._set_console_rw, stop=self._request_stop,
                           usb_present=lambda: self.usb, ble_active=lambda: self.ble)

    # ---- driving the model (manual clock: each call moves time forward)

    def run(self, ms, step=20):
        n = max(1, ms // step)
        for _ in range(n):
            self.clock.advance(step)
            self.ui.tick()
            self.led_color()  # the real loop samples the LED every few ms, so events are seen as they happen

    def down(self, name):
        self.ui.button(name, True)

    def up(self, name):
        self.ui.button(name, False)

    def press(self, name, ms=60):
        self.down(name)
        self.run(ms)
        self.up(name)
        self.run(20)

    def hold(self, name, ms):
        self.down(name)
        self.run(ms)
        self.up(name)
        self.run(20)

    def combo(self, seq):
        names = ("UP", "DOWN", "LEFT", "RIGHT")
        for c in seq:
            self.press(names[c], 40)

    def unlock(self):
        self.combo(lb_fakes.DEMO_COMBO)
        self.press("SELECT")

    def led_color(self):
        """What the status LED shows right now, as (r, g, b)."""
        return self.led.color(self.clock.ticks(), self.ui.screen())

    @property
    def id(self):
        return self.ui.screen()["id"]
