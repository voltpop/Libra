# lb_qrparse.py - strict allow-list parser for scanned QR payloads (otpauth only)
#
# Spec: LIBRA.md software map `qrparse` ("strict, allow-list payload parser; the main
# attack surface"). Peer-key and recovery payloads are deferred and rejected here.
# Pure function: no I/O, no recursion, work bounded by MAX_PAYLOAD.
#
# Accepts the Key URI Format (otpauth://TYPE/LABEL?PARAMS) and rejects, rather than
# repairs, anything unexpected: unknown or repeated parameters, a label that disagrees
# with the issuer parameter, params that do not belong to the type, bad percent-encoding,
# invalid UTF-8, control characters, fragments, extra path segments, oversize input.
#
# The result is NOT display-safe by itself (it may hold look-alike text). Build an
# lb_oath.Entry from it (lb_oath.from_qr); Entry applies the display-safety rules.
# MicroPython cannot wipe an immutable str, so msg.fields["secret"] lives until collected.

OTPAUTH = "OTPAUTH"

MAX_PAYLOAD = 512
MAX_LABEL = 128  # decoded characters
MAX_PARAMS = 8
MAX_SECRET_CHARS = 160
MAX_NUMBER_CHARS = 20

_PARAMS = ("secret", "issuer", "algorithm", "digits", "period", "counter")
_ALGS = ("SHA1", "SHA256", "SHA512")
_B32_OK = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz234567"
_DIGITS = "0123456789"
_MAX_COUNTER = (1 << 64) - 1


class ParseError(Exception):
    pass


def limits():
    return {"max_payload": MAX_PAYLOAD, "max_label": MAX_LABEL, "max_params": MAX_PARAMS,
            "max_secret_chars": MAX_SECRET_CHARS}


class Msg:
    __slots__ = ("type", "fields")

    def __init__(self, type, fields):
        self.type = type
        self.fields = fields

    def __repr__(self):  # never print the secret
        f = self.fields
        return "<Msg %s %s %s/%s>" % (self.type, f.get("type"), f.get("issuer"), f.get("account"))


def _utf8_valid(b):
    """Strict UTF-8 (RFC 3629): no overlongs, no surrogates, nothing above U+10FFFF."""
    i = 0
    n = len(b)
    while i < n:
        c = b[i]
        if c < 0x80:
            i += 1
            continue
        if 0xC2 <= c <= 0xDF:
            need, lo, hi = 1, 0x80, 0xBF
        elif c == 0xE0:
            need, lo, hi = 2, 0xA0, 0xBF
        elif c == 0xED:
            need, lo, hi = 2, 0x80, 0x9F
        elif 0xE1 <= c <= 0xEF:
            need, lo, hi = 2, 0x80, 0xBF
        elif c == 0xF0:
            need, lo, hi = 3, 0x90, 0xBF
        elif c == 0xF4:
            need, lo, hi = 3, 0x80, 0x8F
        elif 0xF1 <= c <= 0xF3:
            need, lo, hi = 3, 0x80, 0xBF
        else:
            return False
        if i + need >= n:
            return False
        if not lo <= b[i + 1] <= hi:
            return False
        for k in range(2, need + 1):
            if not 0x80 <= b[i + k] <= 0xBF:
                return False
        i += need + 1
    return True


def _hexval(c):
    if 0x30 <= c <= 0x39:
        return c - 0x30
    if 0x41 <= c <= 0x46:
        return c - 0x41 + 10
    if 0x61 <= c <= 0x66:
        return c - 0x61 + 10
    raise ParseError("bad percent-encoding")


def _decode(raw, plus_space):
    """Percent-decode, validate UTF-8, reject control characters. '+' means space in
    query values only; it is literal in the label."""
    out = bytearray()
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if c == 0x25:
            if i + 2 >= n:
                raise ParseError("truncated percent-encoding")
            out.append((_hexval(raw[i + 1]) << 4) | _hexval(raw[i + 2]))
            i += 3
        elif c == 0x2B and plus_space:
            out.append(0x20)
            i += 1
        else:
            out.append(c)
            i += 1
    if not _utf8_valid(out):
        raise ParseError("invalid UTF-8")
    s = bytes(out).decode("utf-8")
    for ch in s:
        o = ord(ch)
        if o < 0x20 or o == 0x7F:
            raise ParseError("control character")
    return s


def _number(s, name):
    if not s or len(s) > MAX_NUMBER_CHARS:
        raise ParseError(name + " is not a number")
    for ch in s:
        if ch not in _DIGITS:  # ASCII digits only, no sign, no Unicode digits
            raise ParseError(name + " is not a number")
    return int(s)


def parse(payload):
    """bytes -> Msg, or raise ParseError. Only otpauth is accepted."""
    if not isinstance(payload, (bytes, bytearray)):
        raise ParseError("payload must be bytes")
    n = len(payload)
    if n == 0 or n > MAX_PAYLOAD:
        raise ParseError("bad payload size")
    for c in payload:
        if c < 0x20 or c > 0x7E:  # the URI is ASCII; non-ASCII must be percent-encoded
            raise ParseError("non-printable or non-ASCII byte")
    data = bytes(payload)
    if data[:10].lower() != b"otpauth://":
        raise ParseError("not an otpauth payload")
    if b"#" in data:
        raise ParseError("fragment not allowed")
    rest = data[10:]

    slash = rest.find(b"/")
    if slash < 0:
        raise ParseError("no label")
    kind = rest[:slash].lower()
    if kind == b"totp":
        typ = "TOTP"
    elif kind == b"hotp":
        typ = "HOTP"
    else:
        raise ParseError("unsupported otpauth type")
    rest = rest[slash + 1:]
    q = rest.find(b"?")
    if q < 0:
        raise ParseError("no parameters")
    raw_label = rest[:q]
    raw_query = rest[q + 1:]
    if b"/" in raw_label or b"?" in raw_query:
        raise ParseError("unexpected separator")

    label = _decode(raw_label, False)
    if not label or len(label) > MAX_LABEL:
        raise ParseError("bad label")
    colon = label.find(":")
    if colon >= 0:
        label_issuer = label[:colon].strip(" ")
        account = label[colon + 1:].strip(" ")
    else:
        label_issuer = ""
        account = label.strip(" ")
    if not account or ":" in account:
        raise ParseError("bad account")

    parts = raw_query.split(b"&")
    if len(parts) > MAX_PARAMS:
        raise ParseError("too many parameters")
    params = {}
    for p in parts:
        eq = p.find(b"=")
        if eq <= 0 or eq == len(p) - 1:
            raise ParseError("malformed parameter")
        key = p[:eq].decode()  # ASCII already verified
        if key not in _PARAMS:
            raise ParseError("unknown parameter")
        if key in params:
            raise ParseError("repeated parameter")
        params[key] = _decode(p[eq + 1:], True)

    secret = params.get("secret")
    if secret is None or len(secret) > MAX_SECRET_CHARS:
        raise ParseError("missing or oversize secret")
    body = secret.rstrip("=")
    if not body:
        raise ParseError("empty secret")
    for ch in body:
        if ch not in _B32_OK:
            raise ParseError("secret is not Base32")

    param_issuer = params.get("issuer", "").strip(" ")
    if label_issuer and param_issuer and label_issuer != param_issuer:
        raise ParseError("issuer disagrees with label")
    issuer = param_issuer or label_issuer

    alg = params.get("algorithm", "SHA1").upper()
    if alg not in _ALGS:
        raise ParseError("unsupported algorithm")
    digits = _number(params["digits"], "digits") if "digits" in params else 6
    if digits not in (6, 8):
        raise ParseError("digits must be 6 or 8")

    period = 30
    counter = 0
    if typ == "TOTP":
        if "counter" in params:
            raise ParseError("counter on a TOTP code")
        if "period" in params:
            period = _number(params["period"], "period")
            if period not in (30, 60):
                raise ParseError("period must be 30 or 60")
    else:
        if "period" in params:
            raise ParseError("period on an HOTP code")
        if "counter" not in params:
            raise ParseError("HOTP needs a counter")
        counter = _number(params["counter"], "counter")
        if counter > _MAX_COUNTER:
            raise ParseError("counter out of range")

    return Msg(OTPAUTH, {"type": typ, "issuer": issuer, "account": account,
                         "secret": secret, "alg": alg, "digits": digits,
                         "period": period, "counter": counter})
