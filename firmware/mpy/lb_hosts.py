# lb_hosts.py - paired computers and the trust level of the connection (pure logic, no I/O)
#
# TRUST LEVEL describes the computer on this connection, never a command (see apps/cli/libra_policy.py):
#   masked   the default: any computer
#   session  the device is unlocked with fingerprint AND PIN and the user approved "trust this
#            computer" with a PTT hold. Ends on lock, USB loss or TRUST_IDLE_MS of silence.
#   paired   the computer proved a key the user paired earlier (pairing is a PTT hold plus a
#            6-digit code the user compares on both screens). Same endings as session.
# UNLOCK STRENGTH describes how the device was unlocked: none < pin < pin+fp.
#
# PROTOTYPE LIMIT, read this: MicroPython on the Pico has no public-key signatures, so a paired
# computer and the device share a secret and prove it with HMAC-SHA256 over a fresh challenge.
# The secret crosses the USB link once, at pairing, so someone sniffing that cable could learn it.
# The real firmware stores only a public key (Ed25519). `scheme` below is the one place to swap.
# Nothing here is persistent either: the store is a RAM fake until the sealed storage exists.

import hashlib
import os

import binascii
import lb_ticks

MASKED, SESSION, PAIRED = "masked", "session", "paired"
LEVELS = (MASKED, SESSION, PAIRED)
NONE, PIN, PIN_FP = "none", "pin", "pin+fp"
STRENGTHS = (NONE, PIN, PIN_FP)

SCHEME = "hmac-sha256-proto"
MAX_HOSTS = 8
NAME_MAX = 16
KEY_BYTES = 32
CHALLENGE_BYTES = 16
CHALLENGE_MS = 30000
TRUST_IDLE_MS = 120000  # a trusted connection silent this long is masked again

_NAME_OK = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."


class HostError(Exception):
    pass


def rank(order, value):
    return order.index(value) if value in order else -1


# ---- the scheme (swap these for Ed25519 on real firmware)

def hmac_sha256(key, msg):
    if len(key) > 64:
        key = hashlib.sha256(key).digest()
    key = key + bytes(64 - len(key))
    inner = hashlib.sha256(bytes([b ^ 0x36 for b in key]) + msg).digest()
    return hashlib.sha256(bytes([b ^ 0x5C for b in key]) + inner).digest()


def fingerprint(key):
    """A short public name for a key (16 hex characters); safe to say out loud or put on a screen."""
    return binascii.hexlify(hashlib.sha256(b"libra-host-id" + key).digest())[:16].decode()


def pairing_code(key):
    """The 6 digits both screens show during pairing so the user can compare them."""
    d = hashlib.sha256(b"libra-pair-code" + key).digest()
    n = ((d[0] << 24) | (d[1] << 16) | (d[2] << 8) | d[3]) % 1000000
    return "%06d" % n


def pairing_code_text(key):
    c = pairing_code(key)
    return c[:3] + " " + c[3:]


def response(key, challenge):
    return hmac_sha256(key, b"libra-auth" + challenge)


def same(a, b):
    """Constant-time equality for two byte strings."""
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= x ^ y
    return diff == 0


def clean_name(name):
    if not isinstance(name, str) or not 1 <= len(name) <= NAME_MAX or any(c not in _NAME_OK for c in name):
        raise HostError("name must be 1 to %d of letters, digits, - _ ." % NAME_MAX)
    return name


def clean_key(key):
    if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_BYTES:
        raise HostError("key must be %d bytes" % KEY_BYTES)
    return bytes(key)


# ---- the paired list

class Hosts:
    """store: load() -> {id: {"name": str, "key": hex}} or None; save(dict) durable on return."""

    def __init__(self, store=None, rand=None):
        self._rand = rand or os.urandom
        self._store = store
        self._rec = {}
        if store is not None:
            try:
                saved = store.load()
            except Exception:
                saved = None
            if isinstance(saved, dict):
                for hid, r in saved.items():
                    try:
                        key = binascii.unhexlify(r["key"])
                        if clean_key(key) and fingerprint(key) == hid:
                            self._rec[hid] = {"name": clean_name(r["name"]), "key": r["key"]}
                    except Exception:
                        pass  # anything corrupt or tampered with is ignored, never trusted

    def _save(self):
        if self._store is not None:
            try:
                self._store.save({k: dict(v) for k, v in self._rec.items()})
            except Exception:
                raise HostError("could not save the paired list")

    def list(self):
        return [{"id": k, "name": v["name"]} for k, v in self._rec.items()]

    def count(self):
        return len(self._rec)

    def name(self, hid):
        r = self._rec.get(hid)
        return None if r is None else r["name"]

    def check(self, name, key):
        """Raises HostError if (name, key) could not be added: bad shape, full, duplicate."""
        clean_name(name)
        key = clean_key(key)
        if len(self._rec) >= MAX_HOSTS and fingerprint(key) not in self._rec:
            raise HostError("the paired list is full (%d)" % MAX_HOSTS)
        for hid, r in self._rec.items():
            if r["name"] == name and hid != fingerprint(key):
                raise HostError("that name is already used")

    def add(self, name, key):
        self.check(name, key)
        key = bytes(key)
        hid = fingerprint(key)
        old = self._rec.get(hid)
        self._rec[hid] = {"name": name, "key": binascii.hexlify(key).decode()}
        try:
            self._save()
        except HostError:
            if old is None:
                del self._rec[hid]
            else:
                self._rec[hid] = old
            raise
        return hid

    def remove(self, hid):
        if hid not in self._rec:
            raise HostError("no such computer")
        old = self._rec.pop(hid)
        try:
            self._save()
        except HostError:
            self._rec[hid] = old
            raise

    def challenge(self):
        return self._rand(CHALLENGE_BYTES)

    def verify(self, hid, challenge, resp):
        r = self._rec.get(hid)
        if r is None:
            return False
        return same(response(binascii.unhexlify(r["key"]), challenge), resp)


# ---- the trust level of the connection

class Trust:
    def __init__(self, hosts, session, ticks, idle_ms=TRUST_IDLE_MS):
        self._hosts = hosts
        self._s = session
        self._ticks = ticks
        self._idle = idle_ms
        self.reset()

    def reset(self):
        self._peer = None      # id of the paired computer that proved itself
        self._epoch = None     # the unlock it belongs to: any lock ends it
        self._granted = False  # "trust this computer" approved with a hold
        self._pending = None   # (id, challenge, ticks) waiting for a proof
        self._last = self._ticks()

    def touch(self):
        self._last = self._ticks()

    def strength(self):
        return self._s.unlock_strength()

    def _alive(self):
        if self._s.state() != "UNLOCKED" or self._epoch != self._s.unlock_epoch():
            return False
        return lb_ticks.diff(self._ticks(), self._last) < self._idle

    def level(self):
        if not self._alive():
            if self._peer is not None or self._granted:
                self.reset()
            return MASKED
        if self._peer is not None:
            return PAIRED
        return SESSION if self._granted else MASKED

    def peer_name(self):
        return self._hosts.name(self._peer) if self.level() == PAIRED else None

    def allows(self, level, strength):
        """True if this connection is at least `level` and the device was unlocked at least `strength`."""
        return rank(LEVELS, self.level()) >= rank(LEVELS, level) and rank(STRENGTHS, self.strength()) >= rank(STRENGTHS, strength)

    def grant_session(self):
        """The user approved "trust this computer". Needs a strong unlock; returns False otherwise."""
        if self._s.state() != "UNLOCKED" or self.strength() != PIN_FP:
            return False
        self._granted = True
        self._epoch = self._s.unlock_epoch()
        self.touch()
        return True

    def hello(self, fp):
        """A computer says which key it holds. Returns a fresh challenge, or None if it is not paired."""
        if fp not in [h["id"] for h in self._hosts.list()]:
            self._pending = None
            return None
        ch = self._hosts.challenge()
        self._pending = (fp, ch, self._ticks())
        return ch

    def prove(self, resp):
        """The computer's answer to the last challenge. Single use. Needs the device unlocked."""
        p, self._pending = self._pending, None
        if p is None or self._s.state() != "UNLOCKED":
            return False
        hid, ch, t = p
        if lb_ticks.diff(self._ticks(), t) >= CHALLENGE_MS or not self._hosts.verify(hid, ch, resp):
            return False
        self._peer = hid
        self._epoch = self._s.unlock_epoch()
        self.touch()
        return True

    def become_paired(self, hid):
        """The computer that was just paired is now the paired peer of this connection."""
        self._peer = hid
        self._epoch = self._s.unlock_epoch()
        self.touch()

    def forget(self, hid):
        if self._peer == hid:
            self._peer = None
