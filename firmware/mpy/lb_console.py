# lb_console.py - text commands for interim hardware UI testing (pure logic)
#
# The LCD and a few buttons cannot do everything the browser simulator's panel does, so this
# is the same panel as text: type a line, get a result. It drives lb_rig.Rig, so it works on
# the host (tests) and on the Pico (stdin from Thonny's shell or mpremote).
#
# Commands never raise; a bad line prints "error: ..." and the device keeps running.

import lb_fakes
import lb_samples
import lb_ticks

_ALIASES = {"u": "UP", "d": "DOWN", "l": "LEFT", "r": "RIGHT", "s": "SELECT", "b": "BACK",
            "p": "PTT", "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
            "select": "SELECT", "back": "BACK", "ptt": "PTT"}
_NAMES = ("UP", "DOWN", "LEFT", "RIGHT", "SELECT", "BACK", "PTT")
MAX_NOTE = 400
DEFAULT_PRESS_MS = 80
MAX_PRESS_MS = 10000
MAX_WARP_MS = 3600000
DEMO_UNIX = 1700000000

def utc_text(u):
    """Unix seconds -> 'YYYY-MM-DD HH:MM:SS' (UTC), pure arithmetic."""
    days, rem = divmod(u, 86400)
    z = days + 719468  # days since 0000-03-01
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    if m <= 2:
        y += 1
    return "%04d-%02d-%02d %02d:%02d:%02d" % (y, m, d, rem // 3600, (rem // 60) % 60, rem % 60)


HELP = (
    "press NAME [ms]   tap or hold a button (u d l r s b p or full names; default 80 ms)",
    "down NAME / up NAME   press and release separately",
    "unlock            type the demo combo and press Select",
    "host KIND         computer request: AUTH SIGN DECRYPT;  swap [KIND] replaces it",
    "scan N            camera scans sample N;  samples lists them",
    "fp match|nomatch|error      fingerprint behaviour",
    "clock trusted|untrusted     break or fix the clock;  time UNIX|demo sets it",
    "settime UNIX[.ms] [ZONE_MIN]  propose a time (and zone); one PTT hold sets both",
    "set NAME VALUE      propose push_to_show on|off or utc_offset_min MINUTES (PTT hold)",
    "factoryreset        the computer proposes erasing everything; a PTT hold on the device does it",
    "stayunlocked on|off  the computer proposes test mode (no idle lock); unlock first, PTT hold",
    "rw | ro             make the console read-write (fingerprint on the device only) / read-only",
    "ble on|off          pretend BLE is active (shows the Bluetooth symbol)",
    "usb on|off          pretend USB is plugged in or out (the board reads VBUS itself)",
    "stop                (dev) propose ending the rig program on the board; a PTT hold does it",
    "restart             propose a real reboot of the board (comes back locked); PTT hold",
    "result              how the last proposal ended: APPROVED, CANCELLED (Back), EXPIRED or DENIED",
    "cancel              withdraw the proposal that is waiting on the device",
    "mode                what the device treats this computer as (trust=masked until pairing exists)",
    "settings            show the current settings",
    "warp MS           skip time forward (idle lock, lockout delays)",
    "reboot            power cycle (keeps accounts and lockout);  reset = factory reset",
    "status | trail | note TEXT | help     (type these while the rig is running)",
)


# Commands that act without a PTT hold: they stand in for the buttons or poke the model directly.
# A real device must not take them from the computer, so `direct=False` turns them off. Only the
# proposals (settime, set, factoryreset, restart, stayunlocked) and the read-only commands remain.
# `rw` asks to turn them on again, and only a FINGERPRINT on the device can approve that; the
# rig's console_rw flag then lasts until the next lock or restart. `ro` turns them off at once.
DIRECT = ("usb", "ble", "press", "down", "up", "unlock", "host", "swap", "scan", "fp", "clock", "time", "warp",
          "reboot", "reset")


class Console:
    def __init__(self, rig, out=print, notes_path=None, direct=True):
        try:
            import os
            self._boot = "%02x%02x%02x" % tuple(os.urandom(3))
        except Exception:
            self._boot = "000000"  # a new id per start: lets a host see that a restart really happened
        self._direct_base = direct
        self._rig = rig
        self._out = out
        self._notes_path = notes_path
        self._timers = []  # (due_ticks, button) releases

    @property
    def direct(self):
        return self._direct_base or bool(getattr(self._rig, "console_rw", False))

    # ---- timers (scheduled releases) and input

    def tick(self):
        now = self._rig.clock.ticks()
        keep = []
        for due, name in self._timers:
            if lb_ticks.diff(now, due) >= 0:
                self._rig.ui.button(name, False)
            else:
                keep.append((due, name))
        self._timers = keep

    def handle(self, line):
        try:
            self._dispatch(line.strip())
        except IndexError:
            self._out("error: missing argument (try help)")
        except Exception as e:  # keep the device alive whatever was typed
            self._out("error: %s" % (e,))

    # ---- commands

    def _button(self, word):
        name = _ALIASES.get(word.lower())
        if name is None:
            raise ValueError("unknown button %r (use u d l r s b p)" % (word,))
        return name

    def _int(self, word, lo, hi, what):
        try:
            v = int(word)
        except ValueError:
            raise ValueError("%s must be a whole number" % what)
        if not lo <= v <= hi:
            raise ValueError("%s must be %d..%d" % (what, lo, hi))
        return v

    def _dispatch(self, line):
        if not line:
            return
        parts = line.split()
        cmd = parts[0].lower()
        args = parts[1:]
        r = self._rig
        if cmd in DIRECT and not self.direct:
            raise ValueError("%s is off on the device: use the buttons (the computer may only propose)" % cmd)
        if cmd == "help":
            for h in HELP:
                self._out(h)
        elif cmd == "press":
            name = self._button(args[0])
            ms = self._int(args[1], 1, MAX_PRESS_MS, "ms") if len(args) > 1 else DEFAULT_PRESS_MS
            r.ui.button(name, True)
            self._timers.append((lb_ticks.add(r.clock.ticks(), ms), name))
        elif cmd in ("down", "up"):
            r.ui.button(self._button(args[0]), cmd == "down")
        elif cmd == "unlock":
            for c in lb_fakes.DEMO_COMBO:
                n = ("UP", "DOWN", "LEFT", "RIGHT")[c]
                r.ui.button(n, True)
                r.ui.button(n, False)
            r.ui.button("SELECT", True)
            r.ui.button("SELECT", False)
        elif cmd == "host":
            kind = args[0].upper()
            if kind not in lb_samples.HOST_REQUESTS:
                raise ValueError("kind must be one of " + " ".join(lb_samples.HOST_REQUESTS))
            r.session.request(kind, "USB", lb_samples.HOST_REQUESTS[kind])
            self._out("request sent: %s" % kind)
        elif cmd == "swap":
            p = r.session.pending()
            kind = args[0].upper() if args else (p["kind"] if p else "SIGN")
            if kind not in lb_samples.REPLACEMENT:
                raise ValueError("kind must be one of " + " ".join(lb_samples.REPLACEMENT))
            r.session.request(kind, "USB", lb_samples.REPLACEMENT[kind])
            self._out("request replaced: %s" % kind)
        elif cmd == "samples":
            for i, (n, _) in enumerate(lb_samples.SAMPLES):
                self._out("%d  %s" % (i, n))
        elif cmd == "scan":
            i = self._int(args[0], 0, len(lb_samples.SAMPLES) - 1, "sample")
            ok = r.ui.scan(lb_samples.SAMPLES[i][1])
            self._out("scanned" if ok else "ignored (locked or busy)")
        elif cmd == "fp":
            if args[0] not in ("match", "nomatch", "error"):
                raise ValueError("fp match|nomatch|error")
            r.fp.mode = args[0]
            self._out("fingerprint: %s" % args[0])
        elif cmd == "clock":
            if args[0] not in ("trusted", "untrusted"):
                raise ValueError("clock trusted|untrusted")
            r.clock.trusted_flag = args[0] == "trusted"
            self._out("clock is now %s" % ("trusted" if r.clock.trusted_flag else "NOT trusted"))
        elif cmd == "time":
            if args[0] == "demo":
                r.clock.set_unix(DEMO_UNIX)
            else:
                r.clock.set_unix(self._int(args[0], 1, 4102444800, "unix time"))
            r.clock.trusted_flag = True
            self._out("clock set to %s UTC, trusted" % utc_text(r.clock.now()))
        elif cmd == "settime":
            whole, _, frac = args[0].partition(".")
            ms = self._int(whole, 1, 4102444800, "unix time") * 1000 + \
                (self._int((frac + "000")[:3], 0, 999, "fraction") if frac else 0)
            offset = self._int(args[1], -720, 840, "zone minutes") if len(args) > 1 else None
            if r.ui.host_set_time(ms, offset) is None:
                raise ValueError("refused (wiped, the time is out of range, or the zone is not a 15-minute step)")
            self._out("time proposed: hold PTT on the device to approve")
        elif cmd == "factoryreset":
            if r.ui.host_factory_reset() is None:
                raise ValueError("refused (wiped, or no reset available)")
            self._out("reset proposed: hold PTT on the device to ERASE EVERYTHING, Back to refuse")
        elif cmd == "stayunlocked":
            if args[0] not in ("on", "off"):
                raise ValueError("stayunlocked on|off")
            if r.ui.host_keep_unlocked(args[0] == "on") is None:
                raise ValueError("refused (unlock first, or it is already that way)")
            self._out("mode change proposed: hold PTT on the device to approve")
        elif cmd == "ble":
            if args[0] not in ("on", "off"):
                raise ValueError("ble on|off")
            r.ble = args[0] == "on"
            self._out("ble is now %s" % ("active" if r.ble else "off"))
        elif cmd == "usb":
            if args[0] not in ("on", "off"):
                raise ValueError("usb on|off")
            r.usb = args[0] == "on"
            self._out("usb is now %s" % ("plugged in" if r.usb else "unplugged"))
        elif cmd == "rw":
            if self.direct:
                self._out("console is already read-write")
            elif r.ui.host_console_rw() is None:
                raise ValueError("refused (unlock the device first)")
            else:
                self._out("read-write requested: only a fingerprint on the device approves it")
        elif cmd == "ro":
            r.console_rw = False
            self._out("console is read-only" if not self._direct_base else "console is read-write (set at start-up)")
        elif cmd == "stop":
            if r.ui.host_stop() is None:
                raise ValueError("refused (wiped, or no stop available)")
            self._out("stop proposed: hold PTT on the device to approve, Back to refuse")
        elif cmd == "restart":
            if r.ui.host_restart() is None:
                raise ValueError("refused (wiped, or no restart available)")
            self._out("restart proposed: hold PTT on the device to approve, Back to refuse")
        elif cmd == "result":
            last = r.session.last_decision()
            self._out("result none" if last is None else "result %d %s" % last)
        elif cmd == "cancel":
            p = r.session.pending()
            if p is None:
                self._out("nothing is waiting")
            else:
                r.session.cancel(p["id"])
                self._out("withdrawn")
        elif cmd == "mode":
            sc = r.ui.screen()["status"]
            # unlock strength: none (locked), pin (the combo); pin+fp needs a real fingerprint sensor
            self._out("trust=masked build=dev boot=%s unlock=%s console=%s level=%s usb=%s ble=%s stay_unlocked=%s" % (
                self._boot, "none" if sc["locked"] else "pin", "rw" if self.direct else "ro", sc["level"],
                sc["usb"], sc["ble"], r.session.keep_unlocked()))
        elif cmd == "settings":
            self._out(" ".join("%s=%s" % kv for kv in sorted(r.settings.all().items())))
            self._out("stay_unlocked=%s console=%s" % (r.session.keep_unlocked(),
                                                      "rw" if self.direct else "ro"))
        elif cmd == "set":
            name = args[0]
            raw = args[1]
            if name == "push_to_show":
                if raw not in ("on", "off"):
                    raise ValueError("push_to_show on|off")
                value = raw == "on"
            else:
                value = self._int(raw, -100000, 100000, name)
            if r.ui.host_set_setting(name, value) is None:
                raise ValueError("refused (wiped, unknown, out of range, or already that value)")
            self._out("change proposed: hold PTT on the device to approve")
        elif cmd == "warp":
            ms = self._int(args[0], 1, MAX_WARP_MS, "ms")
            r.clock.advance(ms)
            self._out("skipped %d ms" % ms)
        elif cmd == "reboot":
            self._timers = []
            r.boot()
            self._out("rebooted (locked; accounts and lockout kept)")
        elif cmd == "reset":
            self._timers = []
            r.reset()
            self._out("factory reset")
        elif cmd == "status":
            self._status()
        elif cmd == "trail":
            now = r.clock.ticks()
            for t, k, x in r.ui.trail[-15:]:
                self._out("%+6d ms  %s  %s" % (lb_ticks.diff(t, now), k, x))
        elif cmd == "note":
            self._note(line[4:].strip())
        else:
            raise ValueError("unknown command %r (try help)" % (cmd,))

    def _status(self):
        r = self._rig
        sc = r.ui.screen()
        p = r.session.pending()
        self._out("screen %s | session %s%s | attempts %d | accounts %d" % (
            sc["id"], r.session.state(), " (wiped)" if r.session.wiped() else "",
            r.ks.attempts(), len(r.oath.list())))
        self._out("pending %s | fp %s | clock %s %s" % (
            ("%s: %s" % (p["kind"], p["summary"])) if p else "none", r.fp.mode,
            "trusted" if r.clock.trusted_flag else "NOT trusted", sc["status"]["time"]))

    def _note(self, text):
        if not text:
            raise ValueError("note TEXT")
        r = self._rig
        sc = r.ui.screen()
        now = r.clock.ticks()
        trail = ";".join("%d %s %s" % (lb_ticks.diff(t, now), k, x) for t, k, x in r.ui.trail[-15:])
        rec = "NOTE | %s | screen=%s | lines=%s | toast=%s | trail=%s" % (
            text[:MAX_NOTE], sc["id"], "/".join(sc["lines"]), sc["toast"], trail)
        rec = rec.replace("\n", " ")
        if self._notes_path:
            with open(self._notes_path, "a") as f:
                f.write(rec + "\n")
        self._out("saved: " + text[:60])
