# lb_session.py - the two gates: unlock (the combo) and approval (hold + fingerprint)
#
# Spec: LIBRA.md "Session and unlock policy" (#session-policy) and "Two gates". Only this
# module grants approval. Pure logic: the keystore, the fingerprint matcher and the clock
# are injected, so it runs against fakes on the host.
#
#   keystore: attempts() -> int; set_attempts(n) (durable on return, raises on failure);
#             verify(combo) -> bool (KDF and constant-time compare live there);
#             wipe(); zeroize() (drop keys from RAM on lock)
#   fp:       matched() -> bool, a match seen during the hold (optional; None = absent)
#   clock:    callable returning wrap-around milliseconds (time.ticks_ms)
#
# Rules enforced here (each has a test):
#   - The attempt counter is written BEFORE the combo is checked; if the write fails the
#     combo is not checked at all. A power cut therefore never gives a free retry.
#   - Delays after failures: 0, 0, 0, 5 s, 30 s, 5 min, 15 min, 30 min, 1 h; the 10th
#     failure wipes. A reboot restarts the pending delay (it cannot be skipped by
#     power-cycling), and a counter already at the limit at boot wipes.
#   - The fingerprint is a convenience factor: it can only approve while UNLOCKED, and is
#     never consulted while locked. The combo fallback for approval uses the same counted
#     check and the same wipe.
#   - One request is pending at a time; a new one cancels the old. An approval is bound to
#     the request id, so a stale id can never approve a newer request.
#   - Request text is validated for display safety (lb_text) before it can be shown.
#
# Known limit (spec: "honest limit at L1"): this is firmware policy. An attacker who can
# dump the flash can guess offline; only L2/L3 hardware bounds that.

import lb_text
import lb_ticks

LOCKED = "LOCKED"
UNLOCKED = "UNLOCKED"

# Combo symbols: one D-pad direction per press (2 bits each).
UP, DOWN, LEFT, RIGHT = 0, 1, 2, 3

# Unlock outcomes
OK = "OK"
BAD = "BAD"
DELAYED = "DELAYED"
WIPED = "WIPED"
INVALID = "INVALID"  # malformed combo; nothing was checked and no attempt was used

# Request decisions
APPROVED = "APPROVED"
CANCELLED = "CANCELLED"
EXPIRED = "EXPIRED"
LOCKED_TIMEOUT = "LOCKED_TIMEOUT"  # still locked when the wait ran out: answer "locked"

# hold_complete results (APPROVED is shared)
NEED_COMBO = "NEED_COMBO"
DENIED = "DENIED"  # a fingerprint-only request whose fingerprint did not match
STALE = "STALE"
NEEDS_UNLOCK = "NEEDS_UNLOCK"

# Events passed to the listener as (event, data)
EVT_LOCK_CHANGED = "LOCK_CHANGED"
EVT_REQUEST_PENDING = "REQUEST_PENDING"
EVT_UNLOCK_NEEDED = "UNLOCK_NEEDED"
EVT_REQUEST_DONE = "REQUEST_DONE"

REQ_KINDS = ("SIGN", "DECRYPT", "AUTH", "OATH_REVEAL", "OATH_ADD", "SET_TIME", "SETTING", "VAULT",
             "STICK", "XCH_SIGN", "BACKUP", "RESTORE", "RESET", "MODE", "RESTART", "CONSOLE_RW", "STOP")
REQ_ORIGINS = ("USB", "UI")
FP_ONLY = ("CONSOLE_RW",)  # approvable by fingerprint alone: the combo fallback is never offered
MAX_SUMMARY = 96
REQUEST_TIMEOUT_MS = 30000     # a host is waiting (CCID time extension / CTAP keep-alive)
UI_REQUEST_TIMEOUT_MS = 120000  # started on the device: nobody is waiting on a wire
_KEEP_DECISIONS = 4

# Delay before the next attempt after the Nth consecutive failure (index N-1).
DELAYS_MS = (0, 0, 0, 5000, 30000, 300000, 900000, 1800000, 3600000)


class SessionError(Exception):
    pass


class InvalidPolicy(SessionError):
    pass


class InvalidRequest(SessionError):
    pass


class NoSuchRequest(SessionError):
    pass


class StorageError(SessionError):
    pass


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


class Policy:
    __slots__ = ("combo_min", "combo_max", "bad_limit", "idle_ms")

    def __init__(self, combo_min=8, combo_max=16, bad_limit=10, idle_ms=60000):
        for v in (combo_min, combo_max, bad_limit, idle_ms):
            if not _is_int(v):
                raise InvalidPolicy("policy values must be integers")
        if not 8 <= combo_min <= 16:
            raise InvalidPolicy("combo_min must be 8..16")  # 8 presses = 16 bits is the floor
        if not combo_min <= combo_max <= 16:
            raise InvalidPolicy("combo_max must be combo_min..16")
        if not 3 <= bad_limit <= len(DELAYS_MS) + 1:
            raise InvalidPolicy("bad_limit must be 3..10")
        if not 15000 <= idle_ms <= 600000:
            raise InvalidPolicy("idle_ms must be 15 s .. 10 min")
        self.combo_min = combo_min
        self.combo_max = combo_max
        self.bad_limit = bad_limit
        self.idle_ms = idle_ms


class UnlockResult:
    __slots__ = ("outcome", "delay_ms", "attempts_left")

    def __init__(self, outcome, delay_ms=0, attempts_left=0):
        self.outcome = outcome
        self.delay_ms = delay_ms
        self.attempts_left = attempts_left

    def __repr__(self):
        return "<UnlockResult %s delay=%d left=%d>" % (self.outcome, self.delay_ms,
                                                       self.attempts_left)


class _Pending:
    __slots__ = ("id", "kind", "origin", "summary", "deadline", "needs_combo")


class Session:
    def __init__(self, keystore, clock, fp=None, policy=None, listener=None):
        self._ks = keystore
        self._clock = clock
        self._fp = fp
        self._policy = policy or Policy()
        self._listener = listener
        self._state = LOCKED  # always start locked
        self._wiped = False
        self._keep_unlocked = False  # test mode, RAM only: no idle lock (see set_keep_unlocked)
        self._pending = None
        self._next_id = 1
        self._decisions = {}
        self._order = []
        now = clock()
        self._last_activity = now
        self._not_before = None
        try:
            self._attempts = keystore.attempts()
        except Exception:
            raise StorageError("cannot read the attempt counter")
        if not _is_int(self._attempts) or self._attempts < 0:
            raise StorageError("corrupt attempt counter")
        if self._attempts >= self._policy.bad_limit:
            self._wipe_now()  # a power cut during the last attempt counts as a failure
        elif self._attempts:
            self._not_before = lb_ticks.add(now, self._delay_for(self._attempts))

    # ------------------------------------------------------------ queries

    def state(self):
        return self._state

    def wiped(self):
        return self._wiped

    def policy(self):
        return self._policy

    def set_listener(self, fn):
        self._listener = fn

    def pending(self):
        """What the UI needs to draw the prompt, or None."""
        p = self._pending
        if p is None:
            return None
        return {"id": p.id, "kind": p.kind, "origin": p.origin, "summary": p.summary,
                "needs_combo": p.needs_combo, "locked": self._state == LOCKED}

    def last_decision(self):
        """(request id, decision) of the most recently finished request, or None."""
        if not self._order:
            return None
        rid = self._order[-1]
        return rid, self._decisions[rid]

    def decision(self, req_id):
        """None while pending, else the final decision string."""
        if self._pending is not None and self._pending.id == req_id:
            return None
        try:
            return self._decisions[req_id]
        except (KeyError, TypeError):
            raise NoSuchRequest(req_id)

    # ------------------------------------------------------------ policy

    def set_policy(self, policy):
        if not isinstance(policy, Policy):
            raise InvalidPolicy("expected a Policy")
        if self._state != UNLOCKED:
            raise SessionError("unlock before changing the policy")
        self._policy = Policy(policy.combo_min, policy.combo_max, policy.bad_limit,
                              policy.idle_ms)  # re-validated copy

    # ------------------------------------------------------------ unlock gate

    def unlock(self, combo):
        if self._state == UNLOCKED:
            return UnlockResult(OK)
        res = self._check_combo(combo)
        if res.outcome == OK:
            self._state = UNLOCKED
            self._last_activity = self._clock()
            self._emit(EVT_LOCK_CHANGED, UNLOCKED)
            if self._pending is not None:
                self._emit(EVT_REQUEST_PENDING, self._pending.id)
        return res

    def keep_unlocked(self):
        return self._keep_unlocked

    def set_keep_unlocked(self, on):
        """Test mode: stay unlocked while in use instead of idle-locking. The combo is still
        needed to unlock first (the keys come from it), and ANY lock, manual, wipe or reboot, ends
        the mode. Never stored."""
        if self._state != UNLOCKED:
            raise SessionError("unlock first")
        self._keep_unlocked = bool(on)

    def lock(self, reason="MANUAL"):
        was = self._state
        self._keep_unlocked = False
        self._state = LOCKED
        try:
            self._ks.zeroize()
        except Exception:
            pass  # still locked; the next boot clears RAM anyway
        if was != LOCKED:
            self._emit(EVT_LOCK_CHANGED, reason)

    def activity(self):
        self._last_activity = self._clock()

    def tick(self):
        """Call about once a second: idle lock and request expiry."""
        now = self._clock()
        if self._state == UNLOCKED and not self._keep_unlocked and \
                lb_ticks.diff(now, self._last_activity) >= self._policy.idle_ms:
            self.lock("IDLE")
        p = self._pending
        if p is not None and lb_ticks.diff(now, p.deadline) >= 0:
            self._finish(p, LOCKED_TIMEOUT if self._state == LOCKED else EXPIRED)

    def _valid_combo(self, combo):
        if not isinstance(combo, (list, tuple, bytes, bytearray)):
            return False
        if not self._policy.combo_min <= len(combo) <= self._policy.combo_max:
            return False
        for c in combo:
            if not _is_int(c) or not 0 <= c <= 3:
                return False
        return True

    @staticmethod
    def _delay_for(failures):
        return DELAYS_MS[min(failures, len(DELAYS_MS)) - 1]

    def _check_combo(self, combo):
        """The one counted combo check, shared by unlock and the approval fallback."""
        if self._wiped:
            return UnlockResult(WIPED)
        limit = self._policy.bad_limit
        left = limit - self._attempts
        if not self._valid_combo(combo):
            return UnlockResult(INVALID, 0, left)
        now = self._clock()
        if self._not_before is not None:
            wait = lb_ticks.diff(self._not_before, now)
            if wait > 0:
                return UnlockResult(DELAYED, wait, left)
        n = self._attempts + 1
        try:
            self._ks.set_attempts(n)  # BEFORE the check
        except Exception:
            raise StorageError("attempt counter not written; combo not checked")
        self._attempts = n
        try:
            ok = bool(self._ks.verify(combo))
        except Exception:
            ok = False
        if ok:
            self._attempts = 0
            self._not_before = None
            try:
                self._ks.set_attempts(0)
            except Exception:
                pass  # a stale counter only makes the next boot stricter
            return UnlockResult(OK, 0, limit)
        if n >= limit:
            self._wipe_now()
            return UnlockResult(WIPED)
        delay = self._delay_for(n)
        self._not_before = lb_ticks.add(now, delay)
        return UnlockResult(BAD, delay, limit - n)

    def _wipe_now(self):
        self._wiped = True
        try:
            self._ks.wipe()
        except Exception:
            pass  # still marked wiped; the counter at the limit retries at next boot
        self.lock("WIPED")
        if self._pending is not None:
            self._finish(self._pending, CANCELLED)

    # ------------------------------------------------------------ approval gate

    def request(self, kind, origin, summary):
        if kind not in REQ_KINDS or origin not in REQ_ORIGINS:
            raise InvalidRequest("unknown kind or origin")
        try:
            text = lb_text.clean(summary, MAX_SUMMARY, True)
        except lb_text.TextError as e:
            raise InvalidRequest("summary " + str(e))
        if self._pending is not None:
            self._finish(self._pending, CANCELLED)  # a new request replaces the old one
        p = _Pending()
        p.id = self._next_id
        self._next_id += 1
        p.kind = kind
        p.origin = origin
        p.summary = text
        p.deadline = lb_ticks.add(self._clock(), REQUEST_TIMEOUT_MS if origin == "USB"
                                  else UI_REQUEST_TIMEOUT_MS)
        p.needs_combo = False
        self._pending = p
        self._emit(EVT_UNLOCK_NEEDED if self._state == LOCKED else EVT_REQUEST_PENDING, p.id)
        return p.id

    def cancel(self, req_id):
        p = self._pending
        if p is not None and p.id == req_id:
            self._finish(p, CANCELLED)

    def hold_complete(self, req_id):
        """The UI reports the hold finished on the request screen."""
        p = self._pending
        if p is None or p.id != req_id:
            return STALE
        if lb_ticks.diff(self._clock(), p.deadline) >= 0:
            self._finish(p, LOCKED_TIMEOUT if self._state == LOCKED else EXPIRED)
            return STALE
        if self._state != UNLOCKED:
            return NEEDS_UNLOCK  # the fingerprint is never consulted while locked
        ok = False
        if self._fp is not None:
            try:
                ok = bool(self._fp.matched())
            except Exception:
                ok = False
        if ok:
            self._finish(p, APPROVED)
            return APPROVED
        if p.kind in FP_ONLY:  # no combo fallback: a fingerprint that will not match just fails
            self._finish(p, DENIED)
            return DENIED
        p.needs_combo = True
        return NEED_COMBO

    def approve_with_combo(self, req_id, combo):
        """The fallback when the fingerprint will not match. Returns an UnlockResult;
        on OK the request is approved."""
        p = self._pending
        if p is None or p.id != req_id or not p.needs_combo or self._state != UNLOCKED:
            raise NoSuchRequest(req_id)
        res = self._check_combo(combo)
        if res.outcome == OK and self._pending is p:
            self._finish(p, APPROVED)
        return res

    def _finish(self, p, decision):
        if self._pending is p:
            self._pending = None
        self._decisions[p.id] = decision
        self._order.append(p.id)
        while len(self._order) > _KEEP_DECISIONS:
            self._decisions.pop(self._order.pop(0), None)
        self._emit(EVT_REQUEST_DONE, (p.id, decision))

    def _emit(self, evt, data):
        if self._listener is None:
            return
        try:
            self._listener(evt, data)
        except Exception:
            pass  # a broken UI callback must not break the gates
