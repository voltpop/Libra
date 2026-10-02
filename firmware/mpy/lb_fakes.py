# lb_fakes.py - simulated drivers for host-side development (LIBRA.md "Host-side development")
#
# In-memory stand-ins behind the same duck-typed interfaces the real keystore, RTC, fingerprint
# sensor and haptic driver will provide. Nothing here is secure or persistent: development only.

import time
import lb_ticks

DEMO_COMBO = (0, 1, 2, 3, 0, 1, 2, 3, 0, 1)  # U D L R U D L R U D


class SimClock:
    """One clock for everything. ticks() is the wrap-around millisecond counter the session
    and hold engine use; trusted()/now() is the RTC the oath module uses. real=False gives a
    fully manual clock for tests; real=True follows wall time. advance() works in both (in
    real mode it warps forward), so QA can skip past idle timeouts and lockout delays."""

    def __init__(self, real=False, epoch=1700000000):
        self._real = real
        self._ms = 1000
        self._warp = 0
        self._t0 = time.monotonic() if real else 0.0
        self._epoch = int(time.time()) if real else epoch
        self.trusted_flag = True
        self._delta = 0

    def _abs_ms(self):
        if self._real:
            return int((time.monotonic() - self._t0) * 1000) + 1000 + self._warp
        return self._ms + self._warp

    def ticks(self):
        return self._abs_ms() % lb_ticks.PERIOD

    __call__ = ticks

    def advance(self, ms):
        if self._real:
            self._warp += ms
        else:
            self._ms += ms

    def trusted(self):
        return self.trusted_flag

    def now(self):
        return self._epoch + self._abs_ms() // 1000 + self._delta

    def set_unix(self, u):
        self._delta += u - self.now()


class MemKeystore:
    """Attempt counter, combo verifier, wipe and zeroize, all in RAM. Survives a simulated
    power cycle because the simulator keeps the same object."""

    def __init__(self, combo=DEMO_COMBO):
        self._combo = list(combo)
        self._n = 0
        self.wipes = 0
        self.zeroizes = 0

    def attempts(self):
        return self._n

    def set_attempts(self, n):
        self._n = n

    def verify(self, combo):
        return list(combo) == self._combo

    def wipe(self):
        self.wipes += 1

    def zeroize(self):
        self.zeroizes += 1

    def factory_reset(self):
        self._n = 0


class MemOathStore:
    def __init__(self):
        self.rec = {}
        self.order = None
        self.fail_order = False

    def load_order(self):
        return None if self.order is None else list(self.order)

    def save_order(self, ids):
        if self.fail_order:
            raise OSError("order write failed")
        self.order = list(ids)

    def load_all(self):
        return [dict(r) for r in self.rec.values()]

    def put(self, id, record):
        self.rec[id] = dict(record)

    def delete(self, id):
        del self.rec[id]

    def set_counter(self, id, n):
        self.rec[id]["counter"] = n


class MemSettingsStore:
    def __init__(self):
        self.data = None
        self.fail = False

    def load(self):
        return None if self.data is None else dict(self.data)

    def save(self, d):
        if self.fail:
            raise OSError("settings write failed")
        self.data = dict(d)


class FakeFP:
    """mode: 'match', 'nomatch', 'error'. 'nomatch' also stands for wet/gloved fingers."""

    def __init__(self, mode="match"):
        self.mode = mode

    def matched(self):
        if self.mode == "error":
            raise OSError("sensor fault")
        return self.mode == "match"


class Haptic:
    def __init__(self):
        self.seq = 0
        self.last = None

    def pulse(self, kind):
        self.seq += 1
        self.last = kind
