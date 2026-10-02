# lb_oath.py - OATH TOTP/HOTP for Libra (MicroPython prototype, also runs on CPython)
#
# Spec: LIBRA.md "OATH support" (#oath). RFC 4226 (HOTP), RFC 6238 (TOTP).
#
# Rules enforced here:
#   - HOTP: the advanced counter is persisted BEFORE the code is returned.
#   - TOTP: refused when the clock is not trusted.
#   - add/delete/hold-to-reveal need approved=True (only `session` grants approval).
#   - The secret has no getter, is redacted in repr, and is zeroed on delete.
#   - All input (QR fields, Base32, text, stored records) is untrusted and validated.
#
# MicroPython notes: no hmac module and no base32 in core, so both are written here
# (HMAC over hashlib only; no hand-rolled hash). hashlib may lack sha512 on some ports;
# that raises UnsupportedAlgorithm unless a backend plugin supplies it (see plugins/).

import hashlib
import lb_text

TOTP = "TOTP"
HOTP = "HOTP"
SHA1 = "SHA1"
SHA256 = "SHA256"
SHA512 = "SHA512"

# alg -> (hashlib name, HMAC block size)
_ALGS = {SHA1: ("sha1", 64), SHA256: ("sha256", 64), SHA512: ("sha512", 128)}

MAX_ENTRIES = 64
MIN_SECRET = 10  # bytes; 80 bits, the smallest real-world services issue (RFC 4226 asks 128)
MAX_SECRET = 64
MAX_B32_CHARS = 160  # cap before any processing
MAX_TEXT = 64
MAX_COUNTER = (1 << 64) - 1

_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


class OathError(Exception):
    pass


class InvalidEntry(OathError):
    pass


class UnsupportedAlgorithm(OathError):
    pass


class ClockUntrusted(OathError):
    pass


class ApprovalRequired(OathError):
    pass


class NotFound(OathError):
    pass


class Duplicate(OathError):
    pass


class Full(OathError):
    pass


class StorageError(OathError):
    pass


class CounterExhausted(OathError):
    pass


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ---------------------------------------------------------------- Base32

def b32decode(s):
    """Strict RFC 4648 Base32 -> bytearray. Accepts lowercase, spaces, hyphens and
    '=' padding. Rejects other characters and impossible lengths. Non-zero trailing
    bits are tolerated (some issuers emit them)."""
    if not isinstance(s, str):
        raise InvalidEntry("secret must be text")
    if len(s) > MAX_B32_CHARS:
        raise InvalidEntry("secret too long")
    s = s.replace(" ", "").replace("-", "").upper().rstrip("=")
    if not s:
        raise InvalidEntry("empty secret")
    if len(s) % 8 in (1, 3, 6):
        raise InvalidEntry("bad base32 length")
    out = bytearray()
    acc = 0
    bits = 0
    for ch in s:
        v = _B32.find(ch)
        if v < 0:
            raise InvalidEntry("bad base32 character")
        acc = (acc << 5) | v
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
            acc &= (1 << bits) - 1
    return out


# ---------------------------------------------------------------- HMAC

def default_backends():
    """alg -> (constructor, block size) from hashlib; missing hashes are omitted."""
    out = {}
    for alg, (name, block) in _ALGS.items():
        ctor = getattr(hashlib, name, None)
        if ctor is not None:
            out[alg] = (ctor, block)
    return out


def _check_backends(backends):
    for alg, val in backends.items():
        if alg not in _ALGS:
            raise OathError("backend for unknown algorithm")
        try:
            ctor, block = val
        except (TypeError, ValueError):
            raise OathError("backend must be (constructor, block)")
        if not callable(ctor) or block != _ALGS[alg][1]:
            raise OathError("bad backend for " + alg)


def _hmac(backends, alg, key, msg):
    try:
        ctor, block = backends[alg]
    except KeyError:
        raise UnsupportedAlgorithm(alg)
    if len(key) > block:
        key = ctor(bytes(key)).digest()
    k = bytearray(block)
    k[:len(key)] = key
    ipad = bytearray([b ^ 0x36 for b in k])
    opad = bytearray([b ^ 0x5C for b in k])
    try:
        inner = ctor(bytes(ipad))
        inner.update(msg)
        outer = ctor(bytes(opad))
        outer.update(inner.digest())
        return outer.digest()
    finally:
        for buf in (k, ipad, opad):  # best effort; Python cannot guarantee erasure
            for i in range(len(buf)):
                buf[i] = 0


def _truncate(mac, digits):
    off = mac[-1] & 0x0F
    v = (((mac[off] & 0x7F) << 24) | (mac[off + 1] << 16)
         | (mac[off + 2] << 8) | mac[off + 3])
    s = str(v % (10 ** digits))
    return "0" * (digits - len(s)) + s


# ---------------------------------------------------------------- validation

def _clean_text(v, name, required):
    try:
        return lb_text.clean(v, MAX_TEXT, required)
    except lb_text.TextError as e:
        raise InvalidEntry(name + " " + str(e))


class Entry:
    """One validated OATH account. Constructing it stores nothing."""

    __slots__ = ("id", "issuer", "account", "type", "alg", "digits", "period",
                 "counter", "reveal_requires_hold", "_secret")

    def __init__(self, account, secret, issuer="", type=TOTP, alg=SHA1, digits=6,
                 period=30, counter=0, reveal_requires_hold=False, id=None):
        self.id = id
        self.issuer = _clean_text(issuer, "issuer", False)
        self.account = _clean_text(account, "account", True)
        if type not in (TOTP, HOTP):
            raise InvalidEntry("type must be TOTP or HOTP")
        if alg not in _ALGS:
            raise InvalidEntry("unsupported algorithm")
        if not _is_int(digits) or digits not in (6, 8):
            raise InvalidEntry("digits must be 6 or 8")
        if not _is_int(period) or period not in (30, 60):
            raise InvalidEntry("period must be 30 or 60")
        if not _is_int(counter) or not 0 <= counter <= MAX_COUNTER:
            raise InvalidEntry("bad counter")
        if not isinstance(reveal_requires_hold, bool):
            raise InvalidEntry("reveal flag must be a bool")
        if isinstance(secret, str):
            secret = b32decode(secret)
        elif isinstance(secret, (bytes, bytearray)):
            secret = bytearray(secret)
        else:
            raise InvalidEntry("secret must be Base32 text or bytes")
        if not MIN_SECRET <= len(secret) <= MAX_SECRET:
            raise InvalidEntry("secret length out of range")
        self.type = type
        self.alg = alg
        self.digits = digits
        self.period = period
        self.counter = counter
        self.reveal_requires_hold = reveal_requires_hold
        self._secret = secret

    def __repr__(self):
        return "<Entry id=%s %s %s/%s %s>" % (self.id, self.type, self.issuer,
                                              self.account, self.alg)

    def summary(self):
        """Everything except the secret."""
        return {"id": self.id, "issuer": self.issuer, "account": self.account,
                "type": self.type, "alg": self.alg, "digits": self.digits,
                "period": self.period, "reveal_requires_hold": self.reveal_requires_hold}

    def _record(self):
        # For the keystore only; the one place the secret leaves this object.
        return {"id": self.id, "issuer": self.issuer, "account": self.account,
                "type": self.type, "alg": self.alg, "digits": self.digits,
                "period": self.period, "counter": self.counter,
                "reveal": self.reveal_requires_hold, "secret": bytes(self._secret)}

    def _wipe(self):
        for i in range(len(self._secret)):
            self._secret[i] = 0


def from_qr(msg):
    """Validated Entry from an lb_qrparse.Msg, for the ConfirmOTP screen. Stores nothing."""
    if getattr(msg, "type", None) != "OTPAUTH":
        raise InvalidEntry("not an otpauth message")
    f = msg.fields
    return Entry(f["account"], f["secret"], issuer=f["issuer"], type=f["type"],
                 alg=f["alg"], digits=f["digits"], period=f["period"],
                 counter=f["counter"])


class Code:
    __slots__ = ("digits", "remaining_s")

    def __init__(self, digits, remaining_s):
        self.digits = digits
        self.remaining_s = remaining_s  # None for HOTP

    def __repr__(self):
        return "<Code remaining_s=%s>" % (self.remaining_s,)  # never print the digits


# ---------------------------------------------------------------- service

class Oath:
    """OATH service.

    store: load_all() -> iterable of record dicts; put(id, record); delete(id);
           set_counter(id, n). put/delete/set_counter must be durable on return and
           raise on failure.
    clock: trusted() -> bool; now() -> int unix seconds.
    backends: optional {alg: (hash constructor, block size)} that REPLACES the hashlib
           default for those algorithms (plugin seam; see plugins/README.md). A backend
           sees the secret, so only trusted boot code may pass one.
    """

    def __init__(self, store, clock, backends=None, max_entries=MAX_ENTRIES):
        self._store = store
        self._clock = clock
        self._max = max_entries
        self._backends = default_backends()
        if backends:
            _check_backends(backends)
            self._backends.update(backends)
        self._entries = {}
        self._order = []  # ids in display order
        self._reveal_all = False
        self.rejected = 0  # stored records that failed validation and were skipped
        self._next_id = 1
        self._load()

    def _load(self):
        try:
            records = list(self._store.load_all())
        except Exception:
            raise StorageError("load failed")
        for r in records:
            try:
                e = Entry(r["account"], r["secret"], issuer=r["issuer"], type=r["type"],
                          alg=r["alg"], digits=r["digits"], period=r["period"],
                          counter=r["counter"], reveal_requires_hold=r["reveal"],
                          id=r["id"])
                if not _is_int(e.id) or e.id < 1 or e.id in self._entries:
                    raise InvalidEntry("bad id")
            except (OathError, KeyError, TypeError):
                self.rejected += 1
                continue
            self._entries[e.id] = e
            if e.id >= self._next_id:
                self._next_id = e.id + 1
        self._load_order()

    def _load_order(self):
        """Saved display order if the store has one; anything unknown is ignored and any account
        missing from it goes at the end (by id), so a bad order can never hide an account."""
        saved = None
        try:
            saved = self._store.load_order()
        except Exception:
            pass
        order = []
        if isinstance(saved, (list, tuple)):
            for i in saved:
                if _is_int(i) and i in self._entries and i not in order:
                    order.append(i)
        for i in sorted(self._entries):
            if i not in order:
                order.append(i)
        self._order = order

    def _save_order(self, order):
        try:
            self._store.save_order(list(order))
        except Exception:
            raise StorageError("order not saved")

    def supported_algs(self):
        return sorted(self._backends)

    def _get(self, id):
        try:
            return self._entries[id]
        except (KeyError, TypeError):
            raise NotFound(id)

    def _persist(self, fn, *args):
        try:
            fn(*args)
        except Exception:
            raise StorageError("store failed")

    def add(self, entry, approved=False):
        if not approved:
            raise ApprovalRequired("add")
        if not isinstance(entry, Entry) or entry.id is not None:
            raise InvalidEntry("expected a new Entry")
        if entry.alg not in self._backends:
            raise UnsupportedAlgorithm(entry.alg)
        if len(self._entries) >= self._max:
            raise Full("no free slots")
        for e in self._entries.values():
            if e.issuer == entry.issuer and e.account == entry.account:
                raise Duplicate(entry.account)
        entry.id = self._next_id
        try:
            self._persist(self._store.put, entry.id, entry._record())
        except OathError:
            entry.id = None
            raise
        self._next_id += 1
        self._entries[entry.id] = entry
        self._order.append(entry.id)
        try:
            self._save_order(self._order)
        except StorageError:
            pass  # a missing order entry only means "last", which is where it already is
        return entry.id

    def list(self):
        return [self._entries[i].summary() for i in self._order]

    def order(self):
        return list(self._order)

    def move(self, id, index):
        """Put an account at a new position (0 = first). Durable before it takes effect."""
        self._get(id)
        if not _is_int(index) or not 0 <= index < len(self._order):
            raise InvalidEntry("position out of range")
        order = [i for i in self._order if i != id]
        order.insert(index, id)
        self._save_order(order)
        self._order = order

    def set_reveal_all(self, flag):
        """Global push-to-show: every code needs approval, whatever each account says."""
        self._reveal_all = bool(flag)

    def reveal_required(self, id):
        return self._get(id).reveal_requires_hold or self._reveal_all

    def rename(self, id, account):
        e = self._get(id)
        new = _clean_text(account, "account", True)
        for o in self._entries.values():
            if o is not e and o.issuer == e.issuer and o.account == new:
                raise Duplicate(new)
        old = e.account
        e.account = new
        try:
            self._persist(self._store.put, id, e._record())
        except OathError:
            e.account = old
            raise

    def delete(self, id, approved=False):
        if not approved:
            raise ApprovalRequired("delete")
        e = self._get(id)
        self._persist(self._store.delete, id)
        del self._entries[id]
        self._order = [i for i in self._order if i != id]
        try:
            self._save_order(self._order)
        except StorageError:
            pass  # a stale id in the saved order is ignored on load
        e._wipe()

    def code(self, id, approved=False):
        e = self._get(id)
        if (e.reveal_requires_hold or self._reveal_all) and not approved:
            raise ApprovalRequired("reveal")  # checked before any counter is spent
        if e.alg not in self._backends:
            raise UnsupportedAlgorithm(e.alg)
        if e.type == TOTP:
            if not self._clock.trusted():
                raise ClockUntrusted("set the clock")
            now = self._clock.now()
            if not _is_int(now) or now < 0:
                raise ClockUntrusted("bad time")
            msg = (now // e.period).to_bytes(8, "big")
            digits = _truncate(_hmac(self._backends, e.alg, e._secret, msg), e.digits)
            return Code(digits, e.period - (now % e.period))
        # HOTP: persist the advanced counter first. If this fails, no code is shown.
        c = e.counter
        if c >= MAX_COUNTER:
            raise CounterExhausted(id)
        self._persist(self._store.set_counter, id, c + 1)
        e.counter = c + 1
        digits = _truncate(_hmac(self._backends, e.alg, e._secret, c.to_bytes(8, "big")),
                           e.digits)
        return Code(digits, None)
