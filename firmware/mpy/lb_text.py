# lb_text.py - display-safety rules for text shown on the trusted screen
#
# Anything a scanned QR code or a host request can put on the confirm screen goes through
# here: control characters, line breaks, zero-width and bidirectional-override characters
# (which can make "bob" + RLO + "evil" display as something else) are rejected, never
# silently removed. Only plain spaces are trimmed, after validation.

MAX_TEXT = 64
_BAD_CODEPOINTS = (0x2028, 0x2029, 0xFEFF)


class TextError(ValueError):
    pass


def clean(v, maxlen=MAX_TEXT, required=True):
    if not isinstance(v, str):
        raise TextError("must be text")
    if len(v) > maxlen + 16:  # bound the work before scanning
        raise TextError("too long")
    for ch in v:
        o = ord(ch)
        if (o < 0x20 or 0x7F <= o <= 0x9F or o in _BAD_CODEPOINTS
                or 0x200B <= o <= 0x200F or 0x202A <= o <= 0x202E
                or 0x2066 <= o <= 0x2069 or 0xD800 <= o <= 0xDFFF):
            raise TextError("has a forbidden character")
    v = v.strip(" ")
    if required and not v:
        raise TextError("is empty")
    if len(v) > maxlen:
        raise TextError("too long")
    return v
