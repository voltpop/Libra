# lb_lcd.py - renders a UI screen description onto a 16x2 character display
#
# Pure logic (no I/O): turns lb_ui.UI.screen() into two 16-character ASCII lines. Long text
# scrolls. It exists for interim UI testing on a 1602 LCD; the real panel is 240x320, so this
# shows the flow, timing and wording, not the layout (no ring, no QR, no bar graphics).
#
# Rules: ASCII only, plus the two custom symbols below (HD44780 ROMs lack accents; anything else
# shows as '?'), every line is
# exactly 16 characters, a toast replaces line 2, and a hold in progress replaces line 1 with
# "Hold ####......" so the request text on line 2 stays visible while you hold.

import lb_ticks

COLS = 16
GAP = 3          # blanks between the end and the restart of a scrolling line
PAUSE_MS = 900   # a scrolling line rests at its start this long
STEP_MS = 330    # then moves one character per step


# The 1602's ROM has none of these, so they are drawn into the module's 8 custom character slots
# (hw_lcd loads GLYPHS at start-up) and travel through the text as the control codes \x00..\x04.
SYM_LIBRA = chr(0x264E)    # the zodiac sign, shown in place of the name
SYM_LOCK = chr(0x1F512)    # closed padlock: the Locked screen
SYM_LINK = chr(0x1F517)    # a chain link: connected over USB
SYM_BT = chr(0x16D2)       # the Bluetooth rune: BLE is active
SYM_UNLOCK = chr(0x1F513)  # open padlock: unlocked
GLYPHS = (
    (0b01110, 0b10001, 0b10001, 0b10001, 0b01010, 0b11011, 0b00000, 0b11111),  # 0: libra (omega over a bar)
    (0b01110, 0b10001, 0b10001, 0b11111, 0b11011, 0b11011, 0b11111, 0b00000),  # 1: closed padlock
    (0b00011, 0b00101, 0b01011, 0b00100, 0b11010, 0b10100, 0b11000, 0b00000),  # 2: chain link, diagonal, 180-degree symmetric
    (0b00100, 0b00110, 0b10101, 0b01110, 0b01110, 0b10101, 0b00110, 0b00100),  # 3: bluetooth
    (0b01110, 0b10001, 0b10000, 0b11111, 0b11011, 0b11011, 0b11111, 0b00000),  # 4: open padlock
)
_SYMBOLS = (SYM_LIBRA, SYM_LOCK, SYM_LINK, SYM_BT, SYM_UNLOCK)  # symbol i is drawn as custom code i
_CUSTOM = {sym: chr(i) for i, sym in enumerate(_SYMBOLS)}
_CODES = "".join(chr(i) for i in range(len(_SYMBOLS)))


def ascii_only(s):
    return "".join(c if 32 <= ord(c) < 127 or c in _CODES else _CUSTOM.get(c, "?") for c in s)


def printable(s):
    """The custom codes turned back into the real symbols, for a display that is just text."""
    return "".join(_SYMBOLS[ord(c)] if c in _CODES else c for c in s)


def fit(s, width=COLS):
    s = ascii_only(s)
    return s[:width] if len(s) >= width else s + " " * (width - len(s))


def two(left, right, width=COLS):
    """left text and right-aligned text on one line; the left side gives way."""
    left = ascii_only(left)
    right = ascii_only(right)
    room = width - len(right) - (1 if right else 0)
    left = left[:max(0, room)]
    return left + " " * (width - len(left) - len(right)) + right


def bar(permille, width):
    k = max(0, min(width, permille * width // 1000))
    return "#" * k + "." * (width - k)


class Marquee:
    """Scrolls one line of text that is longer than the display."""

    def __init__(self):
        self._text = None
        self._t0 = 0

    def view(self, text, now):
        text = ascii_only(text)
        if len(text) <= COLS:
            self._text = None
            return fit(text)
        if text != self._text:
            self._text = text
            self._t0 = now
        cycle = len(text) + GAP
        period = PAUSE_MS + cycle * STEP_MS
        e = lb_ticks.diff(now, self._t0) % period
        off = 0 if e < PAUSE_MS else (e - PAUSE_MS) // STEP_MS
        s = text + " " * GAP
        return (s + s)[off:off + COLS]


def _wrap2(msg):
    """Two lines out of a message: break at a space inside the first 16 characters."""
    msg = ascii_only(msg)
    if len(msg) <= COLS:
        return "Notice", msg
    cut = msg.rfind(" ", 0, COLS + 1)
    if cut <= 0:
        cut = COLS
    return msg[:cut].rstrip(), msg[cut:].lstrip()


def raw_lines(sc):
    """(line1, line2) before fitting or scrolling. sc is lb_ui.UI.screen()."""
    sid = sc["id"]
    b = sc["body"]
    ln = sc["lines"]
    st = sc["status"]
    t = st["time"]
    hold = sc.get("hold")
    if sid == "Locked":
        l1 = two(SYM_LOCK + " Locked", t)
        l2 = "*" * min(b["dots"], COLS) if b["dots"] else " - ".join(ln)
    elif sid == "Idle":
        icons = [SYM_LIBRA, SYM_UNLOCK] + ([SYM_LINK] if st.get("usb") else []) + ([SYM_BT] if st.get("ble") else [])
        l1 = two(" ".join(icons), st["level"] + " " + t)
        l2 = "D-pad: accounts"
    elif sid == "Accounts":
        total = b["total"]
        if not total:
            l1, l2 = "Accounts", "None: scan a QR"
        else:
            r = b["rows"][b["cursor"]]
            l1 = two("Accounts", "%d/%d" % (b["index"] + 1, total))
            l2 = ">" + r["text"] + (" [hold]" if r["hold"] else "")
    elif sid == "TOTPCode":
        rem = b["remaining"]
        l1 = two(b["code"], ("%ds" % rem) if rem is not None else "HOTP")
        l2 = b["account"]
    elif sid == "ConfirmOTP":
        l1, l2 = "Add account?", (ln[0] + " " + ln[1]).strip()
    elif sid == "RevealPrompt":
        l1, l2 = "Reveal code?", (ln[0] + " " + ln[1]).strip()
    elif sid == "HostRequest":
        l1 = two("Approve?", ln[1] if len(ln) > 1 else "")
        l2 = ln[2] if len(ln) > 2 else ""
    elif sid == "ComboApprove":
        l1 = "FP failed: combo"
        l2 = "*" * min(b["dots"], COLS) if b["dots"] else "Enter combo"
    elif sid == "ShowQR":
        l1, l2 = "My QR (sim)", (ln[2] + " " + ln[3]) if len(ln) > 3 else ""
    elif sid == "ShowText":
        l1, l2 = "Unknown QR", ln[1] if len(ln) > 1 else ""
    elif sid == "Notice":
        l1, l2 = _wrap2(ln[0] if ln else "")
    elif sid == "Wiped":
        l1, l2 = "WIPED", "Restore backup"
    elif sid == "Settings":
        r = b["rows"][b["cursor"]]
        l1 = two("Settings", "%d/%d" % (b["cursor"] + 1, len(b["rows"])))
        name = "Zone" if r["text"] == "Time zone" else r["text"]  # keeps ">Zone UTC+05:30" in 16
        l2 = ">" + name + ((" " + r["value"]) if r["value"] else "")
    elif sid == "SetTime":
        f = b["fields"][b["index"]]
        tx = b["text"]  # "YYYY-MM-DD HH:MM:SS"
        l1 = tx[:16]  # everything but the seconds fits exactly
        l2 = two("%s <%s>" % (f["label"], f["text"]), ":" + tx[17:19])
    elif sid == "TimeZone":
        l1 = "Time zone"
        l2 = two(b["text"], b["local"])
    elif sid == "ConfirmSetting":
        l1, l2 = "Turn off?", ln[0]
    elif sid == "Reorder":
        r = b["rows"][b["cursor"]]
        l1 = two("Reorder", "%d/%d" % (b["index"] + 1, b["total"]))
        l2 = ("*" if b["grabbed"] else ">") + r["text"]
    else:
        l1, l2 = sid, " ".join(ln)
    if hold:  # a hold is in progress: show progress, keep the request text below
        l1 = "Hold " + bar(hold, COLS - 5)
    if sc.get("toast"):
        l2 = sc["toast"]
    return l1, l2


class LcdView:
    """Screen description in, two display-ready 16-character lines out."""

    def __init__(self, marquee=True):
        self._marquee = marquee
        self._m = [Marquee(), Marquee()]

    def lines(self, sc, now):
        l1, l2 = raw_lines(sc)
        if not self._marquee:
            return fit(l1), fit(l2)
        return self._m[0].view(l1, now), self._m[1].view(l2, now)
