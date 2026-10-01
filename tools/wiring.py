"""Schematic-style wiring diagrams (inline SVG) for the Libra report.

Layout rule: every point-to-point connection is a straight horizontal wire
between pins that share a row, so wires never cross or overlap. Pull-ups,
capacitors, switches and grounds hang off wires as vertical stubs using
standard symbols. Buses are routed so that no two nets cross.
"""
from html import escape

STUB = 26


class D:
    _n = 0

    def __init__(self, w, h, title):
        D._n += 1
        self.id = f"w{D._n}"
        self.w, self.h, self.title = w, h, title
        self.p = []

    # ---- primitives -------------------------------------------------
    def a(self, s):
        self.p.append(s)

    def line(self, pts, cls="w", arrow=None):
        d = " ".join(f"{x},{y}" for x, y in pts)
        m = {"end": ' marker-end="url(#a%s)"', "start": ' marker-start="url(#a%s)"',
             "both": ' marker-start="url(#a%s)" marker-end="url(#a%s)"'}.get(arrow, "")
        m = m.replace("%s", self.id)
        self.a(f'<polyline class="{cls}" points="{d}"{m}/>')

    def text(self, x, y, s, cls="t", anchor="start"):
        self.a(f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}">{escape(s)}</text>')

    def rect(self, x, y, w, h, cls="box"):
        self.a(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>')

    def dot(self, x, y):
        self.a(f'<circle class="dot" cx="{x}" cy="{y}" r="3"/>')

    # ---- symbols ----------------------------------------------------
    def vcc(self, x, y, label="3V3"):
        self.line([(x, y), (x, y - 10)], "pw")
        self.line([(x - 8, y - 10), (x + 8, y - 10)], "pw")
        self.text(x, y - 14, label, "tp", "middle")

    def gnd(self, x, y):
        self.line([(x, y), (x, y + 6)], "w")
        for i, hw in enumerate((8, 5, 2)):
            self.line([(x - hw, y + 6 + i * 4), (x + hw, y + 6 + i * 4)], "w")

    def res_h(self, x, y, label, cx=None, x1=None, x2=None):
        """Resistor drawn inline on a horizontal wire already spanning x1..x2."""
        cx = cx if cx is not None else x
        self.a(f'<rect class="sym" x="{cx-14}" y="{y-5}" width="28" height="10"/>')
        self.text(cx, y - 9, label, "ts", "middle")

    def pullup(self, x, y, label="10k", rail="3V3"):
        """Vertical resistor from a node on a wire up to a power symbol."""
        self.dot(x, y)
        self.line([(x, y), (x, y - 8)])
        self.a(f'<rect class="sym" x="{x-5}" y="{y-30}" width="10" height="22"/>')
        self.line([(x, y - 30), (x, y - 36)])
        self.text(x + 9, y - 15, label, "ts")
        self.vcc(x, y - 36, rail)

    def pulldown(self, x, y, label="100k"):
        self.dot(x, y)
        self.line([(x, y), (x, y + 8)])
        self.a(f'<rect class="sym" x="{x-5}" y="{y+8}" width="10" height="22"/>')
        self.line([(x, y + 30), (x, y + 36)])
        self.text(x + 9, y + 23, label, "ts")
        self.gnd(x, y + 36)

    def cap_down(self, x, y, label="100 nF", side="right"):
        self.dot(x, y)
        self.line([(x, y), (x, y + 10)])
        self.line([(x - 8, y + 10), (x + 8, y + 10)])
        self.line([(x - 8, y + 15), (x + 8, y + 15)])
        self.line([(x, y + 15), (x, y + 21)])
        if side == "right":
            self.text(x + 11, y + 17, label, "ts")
        else:
            self.text(x - 11, y + 17, label, "ts", "end")
        self.gnd(x, y + 21)

    def switch_h(self, x, y, label=None):
        """SPST switch on a horizontal wire; contacts at x and x+28."""
        self.dot(x, y)
        self.line([(x, y), (x + 26, y - 10)])
        self.dot(x + 28, y)
        if label:
            self.text(x + 14, y - 14, label, "ts", "middle")

    def switch_v(self, x, y, label=None):
        """SPST switch on a vertical wire; contacts at y and y+28."""
        self.dot(x, y)
        self.line([(x, y), (x - 10, y + 26)])
        self.dot(x, y + 28)
        if label:
            self.text(x + 14, y + 18, label, "ts")

    def flag(self, x, y, label, side="left"):
        """Off-sheet net flag whose tip touches (x, y)."""
        wd = 7 * len(label) + 14
        if side == "left":
            pts = [(x, y), (x - 10, y - 8), (x - 10 - wd, y - 8), (x - 10 - wd, y + 8), (x - 10, y + 8)]
            tx = x - 10 - wd / 2
        else:
            pts = [(x, y), (x + 10, y - 8), (x + 10 + wd, y - 8), (x + 10 + wd, y + 8), (x + 10, y + 8)]
            tx = x + 10 + wd / 2
        self.a('<polygon class="flag" points="%s"/>' % " ".join(f"{px},{py}" for px, py in pts))
        self.text(tx, y + 4, label, "tf", "middle")

    # ---- boxes with pin rows ---------------------------------------
    def block(self, x, w, title, sub, left=(), right=(), ys=None, dashed=False, top=None, bottom=None):
        rows = [y for y, _ in list(left) + list(right)]
        t = (min(rows) - 44) if top is None else top
        b = (max(rows) + 22) if bottom is None else bottom
        self.rect(x, t, w, b - t, "boxopt" if dashed else "box")
        self.text(x + 8, t + 16, title, "tt")
        if sub:
            self.text(x + 8, t + 30, sub, "ts")
        for y, name in left:
            self.line([(x - STUB, y), (x, y)])
            self.text(x + 7, y + 4, name, "pn")
        for y, name in right:
            self.line([(x + w, y), (x + w + STUB, y)])
            self.text(x + w - 7, y + 4, name, "pn", "end")
        return t, b

    def wire(self, x1, x2, y, label=None, arrow=None, bundle=False):
        self.line([(x1, y), (x2, y)], "wb" if bundle else "w", arrow)
        if label:
            self.text((x1 + x2) / 2, y - 6, label, "ts", "middle")

    def circle(self, cx, cy, r, cls="sym"):
        self.a(f'<circle class="{cls}" cx="{cx}" cy="{cy}" r="{r}"/>')

    def rrect(self, x, y, w, h, rx=6, cls="box"):
        self.a(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"/>')

    def dim_h(self, x1, x2, y, label):
        self.line([(x1, y - 5), (x1, y + 5)], "dimw")
        self.line([(x2, y - 5), (x2, y + 5)], "dimw")
        self.line([(x1, y), (x2, y)], "dimw", "both")
        self.text((x1 + x2) / 2, y - 7, label, "tdim", "middle")

    def dim_v(self, y1, y2, x, label, side="left"):
        self.line([(x - 5, y1), (x + 5, y1)], "dimw")
        self.line([(x - 5, y2), (x + 5, y2)], "dimw")
        self.line([(x, y1), (x, y2)], "dimw", "both")
        if not label:
            return
        cy = (y1 + y2) / 2
        tx = x - 8 if side == "left" else x + 8
        self.a(f'<text class="tdim" x="{tx}" y="{cy}" text-anchor="middle" transform="rotate(-90 {tx} {cy})">{escape(label)}</text>')

    def svg(self):
        defs = (f'<defs><marker id="a{self.id}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" '
                f'markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrow"/>'
                f'</marker></defs>')
        return (f'<svg class="wiring-svg" viewBox="0 0 {self.w} {self.h}" role="img" '
                f'aria-label="{escape(self.title)}" xmlns="http://www.w3.org/2000/svg">'
                + defs + "".join(self.p) + "</svg>")


MCU_X, MCU_W = 20, 130
XR = MCU_X + MCU_W + STUB  # where MCU wires start (176)


def mcu(d, rows, title="ESP32-S3"):
    return d.block(MCU_X, MCU_W, title, "module", right=rows)


# ======================================================================
def overview():
    d = D(820, 640, "Interconnect overview: ESP32-S3 to each subsystem")
    items = [
        ("LCD_CAM (DVP)", "Camera", "OV5640 / OV2640, 24-pin FPC", "DVP 12 signals: GPIO 15,13,6,7,11,9,8,10,12,18,17,16", "<"),
        ("SPI (display)", "Display", "2.0\" 240x320 IPS, ST7789", "SPI: shared bus GPIO 21, 47, 48; CS 39, DC 14", ">"),
        ("I2C  GPIO 4, 5", "I2C devices", "camera SCCB, RTC, gauge, expanders A/B, SE", "SDA / SCL, two expanders, 4.7k pull-ups", "<>"),
        ("GPIO 2 / 1", "Buttons", "PTT + expander A (D-pad, SEL, BACK)", "PTT direct; both expander INTs on GPIO 1", "<"),
        ("UART1  GPIO 40, 41", "Fingerprint", "R503 / 4750 module", "UART TX/RX; IRQ via expander", "<>"),
        ("SPI shared  CS 42", "microSD: System", "device-managed files", "shared SPI bus, CS on GPIO 42", "<>"),
        ("SPI shared  CS 35", "microSD: Vault", "encrypted card brokered to host", "shared SPI bus, CS on GPIO 35", "<>"),
        ("Expander A", "Haptic", "motor driver", "MOSFET gate via expander", ">"),
        ("USB  GPIO 19, 20", "USB-C", "host connection", "D- / D+ (full speed)", "<>"),
    ]
    pitch = 62
    y0 = 62
    ys = [y0 + i * pitch for i in range(len(items))]
    d.block(MCU_X, 170, "ESP32-S3", "module", right=[(y, it[0]) for y, it in zip(ys, items)], top=24, bottom=ys[-1] + 30)
    dx, dw = 520, 280
    for y, it in zip(ys, items):
        d.block(dx, dw, it[1], it[2], left=[(y, "")], top=y - 26, bottom=y + 26)
        d.wire(MCU_X + 170 + STUB, dx - STUB, y, it[3], arrow={"<": "start", ">": "end", "<>": "both"}[it[4]], bundle=True)
    return d.svg()


def camera():
    pitch = 30
    d = D(780, 700, "Camera wiring (DVP)")
    sig = [("GPIO15", "XCLK", ">"), ("GPIO13", "PCLK", "<"), ("GPIO6", "VSYNC", "<"), ("GPIO7", "HREF", "<"),
           ("GPIO11", "D0", "<"), ("GPIO9", "D1", "<"), ("GPIO8", "D2", "<"), ("GPIO10", "D3", "<"),
           ("GPIO12", "D4", "<"), ("GPIO18", "D5", "<"), ("GPIO17", "D6", "<"), ("GPIO16", "D7", "<")]
    ys = [70 + i * pitch for i in range(len(sig))]
    mcu(d, [(y, s[0]) for y, s in zip(ys, sig)])
    extra = [("PWDN", 490), ("RESET", 540), ("3V3", 590), ("GND", 640)]
    dx, dw = 540, 200
    d.block(dx, dw, "Camera module", "24-pin DVP FPC", left=[(y, s[1]) for y, s in zip(ys, sig)] + [(y, n) for n, y in extra],
            top=ys[0] - 44, bottom=extra[-1][1] + 24)
    for y, s in zip(ys, sig):
        d.wire(XR, dx - STUB, y, None, arrow={"<": "start", ">": "end"}[s[2]])
    # tie-offs, drawn as stubs to the left of the module, below the signal rows
    d.line([(dx - STUB, 490), (dx - 70, 490)]); d.gnd(dx - 70, 490); d.text(dx - 80, 484, "tie low", "ts", "end")
    d.line([(dx - STUB, 540), (dx - 70, 540)]); d.vcc(dx - 70, 540); d.text(dx - 80, 544, "tie high", "ts", "end")
    d.line([(dx - STUB, 590), (dx - 70, 590)]); d.vcc(dx - 70, 590, "3V3")
    d.cap_down(dx - 48, 590, "100 nF", "left")
    d.line([(dx - STUB, 640), (dx - 70, 640)]); d.gnd(dx - 70, 640)
    d.text(24, 500, "SCCB (SIOD/SIOC) is on the shared", "ts")
    d.text(24, 514, "I2C bus: see the I2C diagram.", "ts")
    d.text(24, 534, "PWDN / RESET polarity and the", "ts")
    d.text(24, 548, "module's own LDOs: check the", "ts")
    d.text(24, 562, "module datasheet (verify).", "ts")
    return d.svg()


def display():
    d = D(780, 470, "Display wiring (SPI)")
    rows = [("GPIO21", "SCK", ">"), ("GPIO47", "MOSI", ">"), ("GPIO39", "CS", ">"), ("GPIO14", "DC", ">")]
    ys = [70 + i * 38 for i in range(4)]
    mcu(d, [(y, r[0]) for y, r in zip(ys, rows)])
    dx, dw = 540, 200
    rst_y = ys[-1] + 44
    bl_y = rst_y + 52
    pw = [(bl_y + 66, "VCC"), (bl_y + 112, "GND")]
    d.block(dx, dw, "2.0\" IPS panel module", "ST7789, 4-wire SPI", left=[(y, n) for y, n in zip(ys, ["SCK", "SDA (MOSI)", "CS", "DC"])] + [(rst_y, "RESET"), (bl_y, "LED (BL)")] + pw,
            top=ys[0] - 44, bottom=pw[-1][0] + 24)
    for y in ys:
        d.wire(XR, dx - STUB, y, None, arrow="end")
    d.flag(dx - STUB, rst_y, "EXP A: RESET", "left")
    # backlight driver stage inline, enabled from the expander
    bx, bw = 290, 130
    d.rect(bx, bl_y - 18, bw, 36, "boxopt")
    d.text(bx + bw / 2, bl_y - 3, "backlight driver", "ts", "middle")
    d.text(bx + bw / 2, bl_y + 11, "transistor", "ts", "middle")
    d.flag(bx, bl_y, "EXP A: BL EN", "left")
    d.line([(bx + bw, bl_y), (dx - STUB, bl_y)], "w", "end")
    d.vcc(bx + bw / 2, bl_y - 18, "3V3")
    d.line([(dx - STUB, pw[0][0]), (dx - 70, pw[0][0])]); d.vcc(dx - 70, pw[0][0]); d.cap_down(dx - 46, pw[0][0], "100 nF", "left")
    d.line([(dx - STUB, pw[1][0]), (dx - 70, pw[1][0])]); d.gnd(dx - 70, pw[1][0])
    d.text(24, bl_y + 40, "Backlight draws about 55 mA: never drive it", "ts")
    d.text(24, bl_y + 54, "straight from a pin. It is switched on and off", "ts")
    d.text(24, bl_y + 68, "from the expander (on or off, no PWM).", "ts")
    return d.svg()


def buttons():
    d = D(800, 660, "Button wiring: PTT and I2C expander")
    mcu(d, [(80, "GPIO2 (PTT)"), (270, "GPIO1 (INT)")])
    # PTT: direct, pull-up, RC debounce, switch to ground
    y = 80
    d.line([(XR, y), (420, y)])
    d.text(XR + 6, y - 6, "PTT", "ts")
    d.pullup(240, y, "10k")
    d.cap_down(320, y, "100 nF")
    d.line([(420, y), (420, y + 12)])
    d.switch_v(420, y + 12, "PTT")
    d.line([(420, y + 40), (420, y + 54)])
    d.gnd(420, y + 54)
    d.text(470, y + 10, "pull-up + RC debounce for clean", "ts")
    d.text(470, y + 24, "hold timing; wakes from deep sleep", "ts")
    # expander
    ex, ew = 330, 170
    iy = 270
    left = [(iy, "INTA"), (iy + 40, "SDA"), (iy + 80, "SCL"), (iy + 130, "A0"), (iy + 158, "A1"), (iy + 186, "A2"), (iy + 230, "RESET"), (iy + 262, "VDD"), (iy + 306, "VSS")]
    names = ["UP", "DOWN", "LEFT", "RIGHT", "SELECT", "BACK"]
    right = [(iy + i * 40, f"GPA{i}") for i in range(6)]
    d.block(ex, ew, "I/O expander A", "MCP23017, 0x20, I2C", left=left, right=right, top=iy - 44, bottom=iy + 330)
    d.wire(XR, ex - STUB, iy, "INT", arrow="start")
    d.flag(ex - STUB, iy + 40, "I2C SDA (GPIO4)")
    d.flag(ex - STUB, iy + 80, "I2C SCL (GPIO5)")
    # address pins to ground via a small bus
    bx = ex - 56
    for yy in (iy + 130, iy + 158, iy + 186):
        d.line([(ex - STUB, yy), (bx, yy)])
    d.line([(bx, iy + 130), (bx, iy + 186)])
    d.dot(bx, iy + 158)
    d.gnd(bx, iy + 186)
    d.text(bx - 6, iy + 168, "address 0x20", "ts", "end")
    d.line([(ex - STUB, iy + 230), (ex - 56, iy + 230)]); d.vcc(ex - 56, iy + 230)
    d.text(ex - 62, iy + 234, "tie high", "ts", "end")
    d.line([(ex - STUB, iy + 262), (ex - 80, iy + 262)]); d.vcc(ex - 80, iy + 262); d.cap_down(ex - 60, iy + 262, "100 nF", "right")
    d.line([(ex - STUB, iy + 306), (ex - 56, iy + 306)]); d.gnd(ex - 56, iy + 306)
    # six switches to ground, internal pull-ups enabled in firmware
    sx = 560
    for (yy, _), n in zip(right, names):
        d.line([(ex + ew + STUB, yy), (sx, yy)])
        d.switch_h(sx, yy, n)
        d.line([(sx + 28, yy), (sx + 70, yy)])
        d.gnd(sx + 70, yy)
    d.text(sx, iy - 36, "internal pull-ups enabled", "ts")
    return d.svg()


def i2c():
    d = D(820, 700, "Shared I2C bus")
    scl_y, sda_y = 84, 160
    mcu(d, [(scl_y, "GPIO5 (SCL)"), (sda_y, "GPIO4 (SDA)")])
    xs, xc = 236, 560   # SDA bus x, SCL bus x
    bx, bw = 300, 200   # device column
    devs = [("Camera", "OV5640 / OV2640 SCCB, 0x30", False), ("RTC", "DS3231 class, 0x68", False),
            ("Fuel gauge", "MAX17048 class, 0x36", False), ("I/O expander A", "MCP23017, 0x20: buttons, UI", False), ("I/O expander B", "MCP23017, 0x21: peripherals", False),
            ("Secure element", "SE050 0x48 / ATECC608B 0x60", True)]
    top0 = 210
    pitch = 70
    last = top0
    for i, (n, sub, opt) in enumerate(devs):
        y = top0 + i * pitch
        d.rect(bx, y - 24, bw, 52, "boxopt" if opt else "box")
        d.text(bx + 8, y - 8, n, "tt")
        d.text(bx + 8, y + 8, sub if len(sub) < 34 else sub[:34], "ts")
        if opt:
            d.text(bx + 8, y + 22, "", "ts")
        d.text(bx + 6, y + 21, "SDA", "pn")
        d.text(bx + bw - 6, y + 21, "SCL", "pn", "end")
        py = y + 17
        d.line([(xs, py), (bx, py)]); d.dot(xs, py)
        d.line([(bx + bw, py), (xc, py)]); d.dot(xc, py)
        last = py
    # SDA: MCU -> bus, bus runs down past every device, pull-up above the junction
    d.line([(XR, sda_y), (xs, sda_y)])
    d.line([(xs, sda_y), (xs, last)])
    d.pullup(xs, sda_y - 0, "4.7k")
    d.text(xs - 8, sda_y - 20, "SDA", "ts", "end")
    # SCL: runs across the top, above every device, then down the right-hand bus
    d.line([(XR, scl_y), (xc, scl_y)])
    d.line([(xc, scl_y), (xc, last)])
    d.pullup(xc, scl_y, "4.7k")
    d.text(XR + 8, scl_y - 6, "SCL", "ts")
    d.text(24, 620, "SDA bus on the left of the devices, SCL bus on the right,", "ts")
    d.text(24, 636, "so neither net crosses the other. Camera SCCB shares the bus", "ts")
    d.text(24, 652, "if the driver allows it (verify); otherwise use a second bus.", "ts")
    return d.svg()


def fingerprint():
    d = D(780, 600, "Fingerprint module wiring (UART)")
    ys = [70, 116]
    mcu(d, [(ys[0], "GPIO40 (TX)"), (ys[1], "GPIO41 (RX)")])
    dx, dw = 540, 200
    iy = 162
    vy, ty, gy = 250, 350, 410
    left = [(ys[0], "RX"), (ys[1], "TX"), (iy, "IRQ / WAKE"), (vy, "VCC"), (ty, "VT (touch)"), (gy, "GND")]
    d.block(dx, dw, "Fingerprint module", "R503 / 4750 family, 3.3 V logic", left=left, top=ys[0] - 44, bottom=gy + 24)
    d.wire(XR, dx - STUB, ys[0], "TX to module RX", arrow="end")
    d.wire(XR, dx - STUB, ys[1], "module TX to RX", arrow="start")
    d.flag(dx - STUB, iy, "EXP B: FP IRQ", "left")
    # switched VCC through a load switch
    lx, lw = 300, 120
    d.rect(lx, vy - 20, lw, 40, "box")
    d.text(lx + lw / 2, vy - 3, "load switch", "tt", "middle")
    d.text(lx + lw / 2, vy + 12, "high-side", "ts", "middle")
    d.line([(lx - 40, vy), (lx, vy)])
    d.vcc(lx - 40, vy)
    d.line([(lx + lw, vy), (dx - STUB, vy)])
    d.line([(lx + lw / 2, vy + 20), (lx + lw / 2, vy + 44)])
    d.flag(lx + lw / 2, vy + 44, "EN: EXP B", "left")
    # always-on touch rail, ground
    d.line([(dx - STUB, ty), (dx - 90, ty)]); d.vcc(dx - 90, ty); d.text(dx - 98, ty + 4, "always on", "ts", "end")
    d.line([(dx - STUB, gy), (dx - 90, gy)]); d.gnd(dx - 90, gy)
    d.text(24, 500, "Module VCC is switched so it can be powered down; the touch rail (VT)", "ts")
    d.text(24, 516, "stays on so a finger can wake the MCU (verify against the datasheet).", "ts")
    d.text(24, 532, "The IRQ reaches the MCU through expander B and the shared INT line.", "ts")
    d.text(24, 548, "Sensor UART is unauthenticated: convenience factor only.", "ts")
    return d.svg()


def sdcards():
    d = D(900, 760, "microSD wiring: System and Vault, both SPI mode on the shared bus")
    spi = [(70, "GPIO21 (SCK)", "SPI SCK"), (100, "GPIO47 (MOSI)", "SPI MOSI"), (130, "GPIO48 (MISO)", "SPI MISO")]
    sys_cs, vlt_cs = 278, 556
    rows = [(y, lab) for y, lab, _ in spi] + [(sys_cs, "GPIO42 (CS sys)"), (vlt_cs, "GPIO35 (CS vlt)")]
    mcu(d, rows)
    for y, _, net in spi:
        d.flag(XR, y, net, "right")
    dx, dw = 600, 220
    lx, lw = 330, 110
    # ---- System slot ----
    sy = [190, 212, 234, sys_cs]
    sp, scd = sys_cs + 44, sys_cs + 88
    d.block(dx, dw, "microSD slot: System", "SPI mode, shared bus", left=[(sy[0], "CLK"), (sy[1], "DI"), (sy[2], "DO"), (sy[3], "CS"), (sp, "VDD"), (scd, "CD")], top=sy[0] - 44, bottom=scd + 22)
    d.flag(dx - STUB, sy[0], "SPI SCK", "left"); d.flag(dx - STUB, sy[1], "SPI MOSI", "left"); d.flag(dx - STUB, sy[2], "SPI MISO", "left")
    d.wire(XR, dx - STUB, sys_cs, None, arrow="end")
    d.pullup(XR + 90, sys_cs, "10k")
    d.line([(lx - 36, sp), (lx, sp)]); d.vcc(lx - 36, sp)
    d.rect(lx, sp - 16, lw, 32, "box"); d.text(lx + lw / 2, sp + 4, "load switch", "tt", "middle")
    d.line([(lx + lw, sp), (dx - STUB, sp)]); d.cap_down(dx - 62, sp, "10 uF + 100 nF", "left")
    d.line([(lx + lw / 2, sp + 16), (lx + lw / 2, sp + 30)]); d.flag(lx + lw / 2, sp + 30, "EN: EXP B", "left")
    d.flag(dx - STUB, scd, "CD: EXP B", "left")
    # ---- Vault slot ----
    vy = [468, 490, 512, vlt_cs]
    vp, vcd = vlt_cs + 44, vlt_cs + 88
    d.block(dx, dw, "microSD slot: Vault", "SPI mode, shared bus", left=[(vy[0], "CLK"), (vy[1], "DI"), (vy[2], "DO"), (vy[3], "CS"), (vp, "VDD"), (vcd, "CD")], top=vy[0] - 44, bottom=vcd + 22)
    d.flag(dx - STUB, vy[0], "SPI SCK", "left"); d.flag(dx - STUB, vy[1], "SPI MOSI", "left"); d.flag(dx - STUB, vy[2], "SPI MISO", "left")
    d.wire(XR, dx - STUB, vlt_cs, None, arrow="end")
    d.pullup(XR + 90, vlt_cs, "10k")
    d.line([(lx - 36, vp), (lx, vp)]); d.vcc(lx - 36, vp)
    d.rect(lx, vp - 16, lw, 32, "box"); d.text(lx + lw / 2, vp + 4, "load switch", "tt", "middle")
    d.line([(lx + lw, vp), (dx - STUB, vp)]); d.cap_down(dx - 62, vp, "10 uF + 100 nF", "left")
    d.line([(lx + lw / 2, vp + 16), (lx + lw / 2, vp + 30)]); d.flag(lx + lw / 2, vp + 30, "EN: EXP B", "left")
    d.flag(dx - STUB, vcd, "CD: EXP B", "left")
    return d.svg()


def usbc():
    d = D(800, 560, "USB-C wiring")
    mcu(d, [(80, "GPIO20 (D+)"), (130, "GPIO19 (D-)")])
    # ESD array spans both data rows
    ex, ew = 300, 120
    d.rect(ex, 52, ew, 104, "box")
    d.text(ex + ew / 2, 70, "ESD array", "tt", "middle")
    d.text(ex + ew / 2, 84, "USBLC6 class", "ts", "middle")
    d.line([(XR, 80), (ex, 80)]); d.line([(XR, 130), (ex, 130)])
    d.text(XR + 6, 74, "D+", "ts"); d.text(XR + 6, 124, "D-", "ts")
    d.line([(ex + ew / 2, 156), (ex + ew / 2, 168)]); d.gnd(ex + ew / 2, 168)
    cx, cw = 560, 200
    rows = [(80, "D+"), (130, "D-"), (230, "CC1"), (290, "CC2"), (360, "VBUS"), (430, "GND"), (480, "SHELL")]
    d.block(cx, cw, "USB-C receptacle", "device (UFP) role", left=rows, top=36, bottom=504)
    d.line([(ex + ew, 80), (cx - STUB, 80)]); d.line([(ex + ew, 130), (cx - STUB, 130)])
    d.text(ex + ew + 6, 74, "90 ohm differential pair", "ts")
    # CC pull-downs
    for y, n in ((230, "CC1"), (290, "CC2")):
        d.line([(cx - STUB, y), (cx - 90, y)])
        d.pulldown(cx - 90, y, "5.1k")
    # VBUS: TVS to ground, flag to charger
    d.line([(cx - STUB, 360), (cx - 150, 360)])
    d.flag(cx - 150, 360, "VBUS to charger", "left")
    d.pulldown(cx - 80, 360, "TVS")
    d.dot(cx - 80, 360)
    d.line([(cx - STUB, 430), (cx - 90, 430)]); d.gnd(cx - 90, 430)
    d.line([(cx - STUB, 480), (cx - 90, 480)])
    d.text(cx - 96, 484, "to GND via RC", "ts", "end")
    d.gnd(cx - 90, 480)
    return d.svg()


def haptic():
    d = D(700, 440, "Haptic motor driver")
    d.flag(190, 250, "EXP A: HAPTIC", "left")
    d.line([(190, 250), (300, 250)])
    d.text(XR + 6, 268, "gate drive", "ts")
    d.res_h(0, 250, "1k", cx=250)
    # gate node with pulldown
    d.pulldown(330, 250, "100k")
    d.line([(300, 250), (344, 250)])
    # NMOS: gate plate at x=344, channel x=352
    d.line([(344, 236), (344, 264)])
    d.line([(352, 232), (352, 242)]); d.line([(352, 245), (352, 255)]); d.line([(352, 258), (352, 268)])
    d.line([(352, 237), (390, 237), (390, 190)])  # drain
    d.line([(352, 263), (390, 263), (390, 310)])  # source
    d.text(398, 200, "D", "ts"); d.text(398, 306, "S", "ts"); d.text(334, 232, "G", "ts")
    d.gnd(390, 310)
    # motor and flyback diode in parallel from 3V3 to drain
    d.line([(390, 190), (390, 170), (450, 170), (450, 120)])      # drain node to motor branch
    d.line([(390, 170), (330, 170), (330, 120)])                    # drain node to diode branch
    d.dot(390, 170)
    # motor
    d.a('<circle class="sym" cx="450" cy="100" r="16"/>')
    d.text(450, 105, "M", "tt", "middle")
    d.line([(450, 120), (450, 116)])
    d.line([(450, 84), (450, 60), (330, 60)])
    # flyback diode (cathode toward 3V3)
    d.a('<polygon class="sym" points="322,104 338,104 330,90"/>')
    d.line([(322, 90), (338, 90)])
    d.line([(330, 120), (330, 104)]); d.line([(330, 90), (330, 60)])
    d.dot(390, 60)
    d.line([(330, 60), (390, 60)])
    d.vcc(390, 60)
    d.text(344, 110, "flyback", "ts")
    d.text(470, 104, "coin motor", "ts")
    d.text(24, 380, "The gate is driven from expander A. The 100k pull-down keeps the motor off at reset.", "ts")
    d.text(24, 396, "No PWM from the expander: the motor is on or off. Alternative: a piezo through a transistor.", "ts")
    return d.svg()


def usbhost():
    d = D(900, 640, "Tier 1: USB host chip for the stick port")
    ys = [80, 120, 160, 200, 240]
    mcu(d, [(ys[0], "GPIO21 (SCK)"), (ys[1], "GPIO47 (MOSI)"), (ys[2], "GPIO48 (MISO)"), (ys[3], "GPIO36 (CS)"), (ys[4], "GPIO37 (INT)")])
    hx, hw = 330, 170
    dp, dm = 130, 170
    d.block(hx, hw, "USB host controller", "MAX3421E class, SPI", left=[(ys[0], "SCLK"), (ys[1], "MOSI"), (ys[2], "MISO"), (ys[3], "SS"), (ys[4], "INT")], right=[(dp, "D+"), (dm, "D-")], top=36, bottom=ys[4] + 24)
    d.wire(XR, hx - STUB, ys[0], "shared SPI bus", arrow="end")
    d.wire(XR, hx - STUB, ys[1], None, arrow="end")
    d.wire(XR, hx - STUB, ys[2], None, arrow="start")
    d.wire(XR, hx - STUB, ys[3], None, arrow="end")
    d.wire(XR, hx - STUB, ys[4], None, arrow="start")
    # ESD array inline on the data pair
    ex, ew = 600, 100
    d.rect(ex, 104, ew, 88, "box")
    d.text(ex + ew / 2, 126, "ESD", "tt", "middle")
    d.text(ex + ew / 2, 140, "array", "ts", "middle")
    d.line([(hx + hw + STUB, dp), (ex, dp)]); d.line([(hx + hw + STUB, dm), (ex, dm)])
    d.line([(ex + ew / 2, 192), (ex + ew / 2, 204)]); d.gnd(ex + ew / 2, 204)
    rx, rw = 760, 120
    vb, gd = 330, 480
    d.block(rx, rw, "USB-A 2.0", "for the stick", left=[(dp, "D+"), (dm, "D-"), (vb, "VBUS"), (gd, "GND")], top=36, bottom=gd + 24)
    d.line([(ex + ew, dp), (rx - STUB, dp)]); d.line([(ex + ew, dm), (rx - STUB, dm)])
    # stick VBUS: 5 V through a current-limited load switch
    lx, lw = 420, 140
    d.flag(XR + 60, vb, "5 V (host VBUS or boost)", "right")
    d.line([(XR + 60 + 10 + 7 * 24 + 14, vb), (lx, vb)], "pw")
    d.rect(lx, vb - 22, lw, 44, "box")
    d.text(lx + lw / 2, vb - 4, "load switch", "tt", "middle")
    d.text(lx + lw / 2, vb + 12, "current limit", "ts", "middle")
    d.line([(lx + lw, vb), (rx - STUB, vb)], "pw")
    d.line([(lx + 30, vb + 22), (lx + 30, vb + 52)])
    d.flag(lx + 30, vb + 52, "EN: EXP B", "right")
    d.line([(lx + 110, vb + 22), (lx + 110, vb + 92)])
    d.flag(lx + 110, vb + 92, "FLT: EXP B", "right")
    d.line([(hx + hw + STUB, gd), (rx - STUB, gd)])
    d.gnd(hx + hw + STUB, gd)
    d.text(660, gd - 6, "common ground", "ts", "middle")
    d.text(24, 600, "MAX3421E needs its own 12 MHz crystal and a 3.3 V supply (verify). It shares the SPI bus with the display and both microSD cards.", "ts")
    d.text(24, 616, "Full speed only: about 1 MB/s at best. Stick VBUS enable and fault come from expander B.", "ts")
    return d.svg()


def usbbroker():
    d = D(960, 440, "Tier 2: high-speed storage engine behind a USB 2.0 hub")
    hostx, hostw = 20, 140
    d.block(hostx, hostw, "Host computer", "plugs into Libra", right=[(100, "USB-C")], top=56, bottom=124)
    hx, hw = 250, 150
    d.block(hx, hw, "USB 2.0 hub", "high-speed", left=[(100, "UP")], right=[(100, "DS1"), (220, "DS2")], top=56, bottom=244)
    d.line([(hostx + hostw + STUB, 100), (hx - STUB, 100)], "wb", "both")
    ex, ew = 520, 190
    d.block(ex, ew, "ESP32-S3", "keys, UI, PIN (full-speed USB)", left=[(100, "USB FS")], top=56, bottom=124)
    d.line([(hx + hw + STUB, 100), (ex - STUB, 100)], "wb", "both")
    d.text((hx + hw + STUB + ex - STUB) / 2, 94, "keys", "ts", "middle")
    en = 520
    d.block(en, ew, "Storage engine", "i.MX RT1062 class, AES", left=[(220, "USB HS device")], right=[(300, "USB HS host")], top=176, bottom=330)
    d.line([(hx + hw + STUB, 220), (en - STUB, 220)], "wb", "both")
    d.text((hx + hw + STUB + en - STUB) / 2, 214, "drive", "ts", "middle")
    d.line([(ex + ew / 2, 124), (ex + ew / 2, 176)], "w", "both")
    d.text(ex + ew / 2 + 10, 154, "SPI / UART: unlock and volume key", "ts")
    sx, sw = 800, 130
    d.block(sx, sw, "USB stick", "any, ciphertext", left=[(300, "USB")], top=256, bottom=324)
    d.line([(en + ew + STUB, 300), (sx - STUB, 300)], "wb", "both")
    d.text((en + ew + STUB + sx - STUB) / 2, 294, "ciphertext", "ts", "middle")
    d.text(24, 380, "The hub lets the host see two devices: the key (ESP32-S3, FIDO/OpenPGP) and a virtual drive (engine, plaintext to the host). The stick is reachable", "ts")
    d.text(24, 396, "only through the engine, which encrypts and decrypts every block. The volume key is held in the engine's RAM only", "ts")
    d.text(24, 412, "while unlocked. Stick VBUS: current-limited switch from the engine side (not drawn).", "ts")
    return d.svg()


def system():
    d = D(1000, 600, "System architecture")
    L = [(90, "Camera", "OV5640 / OV2640, rear", "DVP", False),
         (170, "Buttons", "PTT + I/O expander", "GPIO, I2C", False),
         (250, "Fingerprint", "R503 / 4750 module", "UART", False),
         (330, "USB-C (host)", "FIDO2, OpenPGP card, Vault drive", "USB", False),
         (410, "Power", "USB power, 3.3 V (battery in v1)", "3.3 V", False)]
    R = [(90, "Display", "2.0\" IPS, ST7789", "SPI", False),
         (170, "microSD: System", "logs, contacts, backups", "SPI (shared)", False),
         (250, "microSD: Vault", "encrypted card brokered to host", "SD host", False),
         (330, "I2C devices", "RTC, gauge, expander, SE opt.", "I2C", False),
         (410, "Haptic", "motor / piezo driver", "GPIO", False),
         (490, "Stick port", "USB host chip + USB-A", "SPI + GPIO", False)]
    mx, mw = 400, 200
    d.block(mx, mw, "ESP32-S3", "BLE built in", left=[(y, "") for y, *_ in L], right=[(y, "") for y, *_ in R], top=44, bottom=520)
    lx, lw = 20, 210
    rx, rw = 770, 210
    for y, t, sub, lab, opt in L:
        d.block(lx, lw, t, sub, right=[(y, "")], top=y - 28, bottom=y + 28, dashed=opt)
        cls = "pw" if lab == "3.3 V" else "wb"
        d.line([(lx + lw + STUB, y), (mx - STUB, y)], cls, "both" if lab not in ("3.3 V",) else "end")
        d.text((lx + lw + STUB + mx - STUB) / 2, y - 6, lab, "ts", "middle")
    for y, t, sub, lab, opt in R:
        d.block(rx, rw, t, sub, left=[(y, "")], top=y - 28, bottom=y + 28, dashed=opt)
        d.line([(mx + mw + STUB, y), (rx - STUB, y)], "wb", "both" if lab not in ("GPIO",) else "end")
        d.text((mx + mw + STUB + rx - STUB) / 2, y - 6, lab, "ts", "middle")
    d.text(20, 560, "Thick lines carry signals, the red line is power. All boxes are in v0; the secure element is not fitted, and the stick port is optional in v1.", "ts")
    d.text(20, 576, "Detailed pins and wiring are in the Pin map and Wiring diagrams sections; power is in the Power tree section.", "ts")
    return d.svg()


def power():
    d = D(1200, 560, "Power tree")
    y = 90
    vx, vw = 20, 110
    cx, cw = 200, 180
    sx, sw = 450, 120
    rgx, rgw = 640, 150
    d.block(vx, vw, "USB-C VBUS", "5 V", right=[(y, "")], top=y - 30, bottom=y + 30)
    d.block(cx, cw, "Power-path charger", "v1: BQ24074 class (verify)", left=[(y, "")], right=[(y, "")], top=y - 30, bottom=y + 30, dashed=True)
    d.block(sx, sw, "Switch", "physical, on the load", left=[(y, "")], right=[(y, "")], top=y - 30, bottom=y + 30)
    d.block(rgx, rgw, "3.3 V regulator", "buck-boost (preferred)", left=[(y, "")], right=[(y, "")], top=y - 30, bottom=y + 30)
    d.line([(vx + vw + STUB, y), (cx - STUB, y)], "pw", "end")
    d.line([(cx + cw + STUB, y), (sx - STUB, y)], "pw", "end")
    d.text((cx + cw + sx) / 2, y - 6, "SYS", "ts", "middle")
    d.line([(sx + sw + STUB, y), (rgx - STUB, y)], "pw", "end")
    # battery and gauge hang off the charger (v1)
    bx = cx + cw / 2 - 75
    by, gy = 230, 350
    d.line([(cx + cw / 2, y + 30), (cx + cw / 2, by - 30)], "pw", "both")
    d.block(bx, 150, "1S LiPo", "v1: 3.0 to 4.2 V", top=by - 30, bottom=by + 30, dashed=True)
    d.line([(cx + cw / 2, by + 30), (cx + cw / 2, gy - 30)], "w")
    d.block(bx, 150, "Fuel gauge", "v1: MAX17048, I2C", top=gy - 30, bottom=gy + 30, dashed=True)
    # 3V3 rail with consumers
    rail_x = 880
    d.line([(rgx + rgw + STUB, y), (rail_x, y)], "pw")
    d.text(rgx + rgw + STUB + 6, y - 6, "3V3", "tp")
    cons = [(y + 60, "ESP32-S3", "dev board, camera, display"),
            (y + 130, "Always-on I2C parts", "RTC, I/O expander, optional SE"),
            (y + 200, "Fingerprint", "VCC via load switch; touch rail on"),
            (y + 270, "microSD System + Vault", "one load switch each"),
            (y + 340, "Haptic motor", "MOSFET driver")]
    d.line([(rail_x, y), (rail_x, cons[-1][0])], "pw")
    d.dot(rail_x, y)
    for yy, t, sub in cons:
        d.dot(rail_x, yy)
        d.line([(rail_x, yy), (rail_x + 30, yy)], "pw")
        d.block(rail_x + 56, 260, t, sub, left=[(yy, "")], top=yy - 28, bottom=yy + 28)
    d.text(20, 470, "v0 runs from USB through the dev board's own regulator. The charger, battery and fuel gauge (dashed) arrive with the v1 PCB.", "ts")
    d.text(20, 486, "The switch cuts the load, not the charger, so a v1 battery can charge while the device is off.", "ts")
    d.text(20, 502, "Stick VBUS (optional port) comes from the host VBUS through its own current-limited switch, not from this rail (the Second USB port section).", "ts")
    d.text(20, 518, "VBUS detection is not needed: TinyUSB reports host presence.", "ts")
    return d.svg()


def context():
    d = D(1000, 450, "Context: who and what talks to Libra")
    L = [(90, "You", "screen, buttons, camera, PIN", "trusted"),
         (170, "Host computer", "USB: FIDO2, OpenPGP, Vault drive", "untrusted"),
         (250, "Phone / companion", "BLE: backup, update, sync", "untrusted, optional"),
         (330, "Other Libra, QR codes", "key exchange, OTP enrolment", "untrusted input")]
    R = [(130, "SD cards", "System: input; Vault: ciphertext", "untrusted media"),
         (230, "USB stick", "ciphertext only, stick port", "untrusted media"),
         (330, "Keyservers, websites", "via host or phone only", "no direct link")]
    mx, mw = 400, 200
    d.block(mx, mw, "Libra", "trust boundary: everything inside the box", left=[(y, "") for y, *_ in L], right=[(y, "") for y, _, _, tr in R if tr != "no direct link"], top=44, bottom=380)
    lx, lw = 20, 210
    rx, rw = 770, 210
    for y, t, sub, tr in L:
        d.block(lx, lw, t, sub, right=[(y, "")], top=y - 28, bottom=y + 28, dashed=(tr != "trusted"))
        d.line([(lx + lw + STUB, y), (mx - STUB, y)], "wb", "both")
        d.text((lx + lw + STUB + mx - STUB) / 2, y - 6, tr, "ts", "middle")
    for y, t, sub, tr in R:
        if tr == "no direct link":
            d.block(rx, rw, t, sub, top=y - 28, bottom=y + 28, dashed=True)
            d.text(rx + rw / 2, y + 44, "no wire: not connected directly", "ts", "middle")
            continue
        d.block(rx, rw, t, sub, left=[(y, "")], top=y - 28, bottom=y + 28, dashed=True)
        d.line([(mx + mw + STUB, y), (rx - STUB, y)], "wb", "both")
        d.text((mx + mw + STUB + rx - STUB) / 2, y - 6, tr, "ts", "middle")
    d.text(20, 430, "Dashed boxes are untrusted. Only you and the firmware inside the boundary are trusted; every other source of data is checked.", "ts")
    return d.svg()


def mech_v1():
    S = 4  # px per mm
    d = D(1180, 560, "v1 mechanical layout: front, back and edge views (to scale, estimates)")
    # ---- front ----
    fx, fy, fw, fh = 70, 80, 50 * S, 95 * S
    d.text(fx + fw / 2, 44, "FRONT (face)", "tt", "middle")
    d.rrect(fx, fy, fw, fh, 18, "case")
    gw, gh = 36 * S, 49 * S
    gx, gy = fx + (fw - gw) / 2, fy + 8 * S
    d.rrect(gx, gy, gw, gh, 4, "glass")
    aw, ah = 30.6 * S, 40.8 * S
    d.rrect(gx + (gw - aw) / 2, gy + (gh - ah) / 2, aw, ah, 2, "active")
    d.text(fx + fw / 2, gy + gh / 2 - 4, "2.0\" screen", "ts", "middle")
    d.text(fx + fw / 2, gy + gh / 2 + 10, "active 30.6 x 40.8", "ts", "middle")
    cx, cy = fx + 60, fy + 300
    d.rrect(cx - 10, cy - 34, 20, 68, 3, "sym")
    d.rrect(cx - 34, cy - 10, 68, 20, 3, "sym")
    d.circle(cx, cy, 5, "dot")
    d.text(cx, cy + 56, "D-pad", "ts", "middle")
    d.circle(fx + 140, cy - 12, 13, "sym"); d.text(fx + 158, cy - 8, "SEL", "ts")
    d.circle(fx + 140, cy + 34, 13, "sym"); d.text(fx + 158, cy + 38, "BACK", "ts")
    d.rrect(fx + fw / 2 - 20, fy - 5, 40, 8, 3, "part")
    d.text(fx + fw / 2, fy - 12, "PTT on the top edge", "ts", "middle")
    d.dim_h(fx, fx + fw, fy + fh + 26, "50 mm")
    d.dim_v(fy, fy + fh, fx - 22, "95 mm")
    # ---- back ----
    bx = 340
    d.text(bx + fw / 2, 44, "BACK", "tt", "middle")
    d.rrect(bx, fy, fw, fh, 18, "case")
    d.circle(bx + 62, fy + 58, 24, "sym"); d.circle(bx + 62, fy + 58, 13, "lens")
    d.text(bx + 62, fy + 98, "camera", "ts", "middle")
    d.rrect(bx + 120, fy + 24, 60, 60, 3, "boxopt")
    d.text(bx + 150, fy + 98, "System microSD", "ts", "middle")
    d.text(bx + 150, fy + 110, "(under cover)", "ts", "middle")
    fpx, fpy = bx + fw / 2, fy + 240
    d.circle(fpx, fpy, 56, "sym")
    d.circle(fpx, fpy, 41.6, "hidden")
    d.text(fpx, fpy + 76, "R503: 28 mm (solid)", "ts", "middle")
    d.text(fpx, fpy + 90, "4750: 20.8 mm (dashed)", "ts", "middle")
    d.text(fpx, fpy + 106, "fingerprint module (required)", "tt", "middle")
    # ---- top edge ----
    ex, ey, ew, eh = 640, 80, 50 * S, 16 * S
    d.text(ex + ew / 2, 62, "TOP EDGE", "tt", "middle")
    d.rrect(ex, ey, ew, eh, 8, "case")
    d.rrect(ex + ew / 2 - 22, ey + 18, 44, 28, 4, "part")
    d.text(ex + ew / 2, ey + eh + 16, "PTT: recessed, firm, tell-by-touch", "ts", "middle")
    d.dim_v(ey, ey + eh, ex + ew + 22, "", "right")
    d.text(ex + ew + 34, ey + eh / 2 - 2, "16 mm thick", "tdim")
    d.text(ex + ew + 34, ey + eh / 2 + 12, "(22+ with an R503)", "tdim")
    # ---- bottom edge ----
    by = 240
    d.text(ex + ew / 2, by - 18, "BOTTOM EDGE", "tt", "middle")
    d.rrect(ex, by, ew, eh, 8, "case")
    d.rrect(ex + 32, by + 26, 36, 13, 5, "sym")
    d.text(ex + 50, by + eh + 16, "USB-C", "ts", "middle")
    d.rrect(ex + 130, by + 26, 32, 12, 2, "sym")
    d.text(ex + 146, by + eh + 16, "power switch", "ts", "middle")
    # ---- right side edge ----
    sx, sy, sw, sh = 1000, 80, 16 * S, 95 * S
    d.text(sx + sw / 2, 62, "SIDE EDGE", "tt", "middle")
    d.rrect(sx, sy, sw, sh, 8, "case")
    d.rrect(sx + 8, sy + 110, 48, 6, 1, "sym")
    d.text(sx - 8, sy + 118, "microSD Vault", "ts", "end")
    d.rrect(sx + 21, sy + 220, 22, 52, 2, "boxopt")
    d.text(sx - 8, sy + 250, "USB-A stick port", "ts", "end")
    d.text(sx - 8, sy + 264, "(optional in v1)", "ts", "end")
    d.text(24, 540, "Estimates to validate with printed shells. Solid lines are visible parts; dashed outlines are hidden or alternative parts.", "ts")
    return d.svg()


def stackup():
    S = 12  # px per mm
    d = D(1100, 520, "Thickness stack-up by region (estimates)")
    regions = [
        ("Camera region", [("Front shell", 1.5, "lay0"), ("Display module", 3.7, "lay1"), ("Gap", 0.5, None), ("PCB", 1.6, "lay2"), ("Camera module", 6.0, "lay3"), ("Back shell", 1.5, "lay0")]),
        ("Battery region", [("Front shell", 1.5, "lay0"), ("Display module", 3.7, "lay1"), ("Gap", 0.5, None), ("PCB", 1.6, "lay2"), ("Battery (500 mAh)", 5.5, "lay4"), ("Back shell", 1.5, "lay0")]),
        ("Fingerprint region, R503", [("Front shell", 1.5, "lay0"), ("Display module", 3.7, "lay1"), ("Gap", 0.5, None), ("PCB", 1.6, "lay2"), ("R503 module", 15.5, "lay5"), ("Back shell", 1.5, "lay0")]),
    ]
    top = 90
    for i, (title, layers) in enumerate(regions):
        x = 80 + i * 340
        w = 90
        d.text(x + w / 2 + 40, 52, title, "tt", "middle")
        y = top
        total = sum(t for _, t, _ in layers)
        for name, t, cls in layers:
            h = t * S
            if cls:
                d.rect(x, y, w, h, cls)
            if name != "Gap":
                d.line([(x + w, y + h / 2), (x + w + 14, y + h / 2)], "w")
                d.text(x + w + 18, y + h / 2 + 4, f"{name}  {t} mm", "ts")
            y += h
        d.dim_v(top, y, x - 16, f"{total:.1f} mm")
    d.text(24, 470, "Estimates, including a 0.5 mm clearance between the display and the PCB. The ESP32-S3 module (about 3.2 mm tall) sits on the PCB in a region without the battery or camera.", "ts")
    d.text(24, 486, "A fingerprint region over the battery is not possible with an R503; recessing the sensor through the display bay could save a few mm.", "ts")
    d.text(24, 502, "The 4750's thickness is unpublished, so its region is not drawn.", "ts")
    return d.svg()


ROW = 22


def _wrap(text, width=150):
    import textwrap
    return textwrap.wrap(text, width=width)


def _marker(d, x, y, n):
    d.circle(x, y, 7, "mk")
    d.text(x, y + 3.5, str(n), "mkt", "middle")


def _sheet(title, subtitle, shared, devices, notes, mcu_marks=None, mcu_corner=None):
    """Wiring sheet: MCU on the left, devices on the right, notes as a footer.

    shared:  [(mcu pin label, net name)]  drawn first, as flagged MCU pins
    devices: [{"title","sub","mark","pins":[(kind,label,extra[,mark])], "out": {...}}]
             kind "flag": device pin on a shared net, extra = net name
             kind "wire": straight wire to an MCU pin, extra = (MCU label, arrow)
    notes:   [(number, text)]  numbered footnotes referenced by markers
    """
    mcu_marks = mcu_marks or {}
    d = D(1120, 400, title)
    mx, mw = 20, 170
    dx, dw = 560, 250
    y = 78
    mcu_pins = []
    for lab, net in shared:
        mcu_pins.append((y, lab, net))
        y += ROW
    y += 10
    dev_rows = []
    for dev in devices:
        rows = []
        for pin in dev["pins"]:
            rows.append((y,) + tuple(pin))
            y += ROW
        dev_rows.append((dev, rows))
        y += 18
    wire_pins = [(r[0], r[3][0]) for dev, rows in dev_rows for r in rows if r[1] == "wire"]
    top = 36
    bottom = y - 4
    d.rrect(mx, top, mw, bottom - top, 6, "box")
    d.text(mx + 8, top + 16, "ESP32-S3", "tt")
    d.text(mx + 8, top + 30, subtitle, "ts")
    if mcu_corner:
        _marker(d, mx + mw - 8, top, mcu_corner)
    for yy, lab, net in mcu_pins:
        d.line([(mx + mw, yy), (mx + mw + STUB, yy)])
        d.text(mx + mw - 7, yy + 4, lab, "pn", "end")
        d.flag(mx + mw + STUB, yy, net, "right")
        if lab in mcu_marks:
            _marker(d, mx + 14, yy, mcu_marks[lab])
    for yy, lab in wire_pins:
        d.line([(mx + mw, yy), (mx + mw + STUB, yy)])
        d.text(mx + mw - 7, yy + 4, lab, "pn", "end")
        if lab in mcu_marks:
            _marker(d, mx + 14, yy, mcu_marks[lab])
    for dev, rows in dev_rows:
        y0, y1 = rows[0][0], rows[-1][0]
        d.rrect(dx, y0 - 14, dw, y1 - y0 + 28, 6, "box")
        d.text(dx + dw - 8, y0 + 4, dev["title"], "tt", "end")
        marks = dev.get("marks") or ([dev["mark"]] if dev.get("mark") else [])
        for i, mk in enumerate(marks):
            _marker(d, dx + 8 + i * 17, y0 - 14, mk)
        if len(rows) > 1 and dev.get("sub"):
            d.text(dx + dw - 8, y0 + 4 + ROW, dev["sub"], "ts", "end")
        for row in rows:
            yy, kind, label, extra = row[0], row[1], row[2], row[3]
            d.line([(dx - STUB, yy), (dx, yy)])
            d.text(dx + 7, yy + 4, label, "pn")
            if len(row) > 4 and row[4]:
                _marker(d, dx + dw - 14, yy, row[4])
            if kind == "flag":
                d.flag(dx - STUB, yy, extra, "left")
            else:
                d.line([(mx + mw + STUB, yy), (dx - STUB, yy)], "w", extra[1])
        out = dev.get("out")
        if out:
            oy = out["row"] + y0
            d.line([(dx + dw, oy), (dx + dw + STUB, oy)])
            d.text(dx + dw + STUB + 32, oy - 8, out["pin"], "ts", "middle")
            bx, bw = dx + dw + 90, 190
            d.rrect(bx, oy - 28, bw, 56, 6, "box")
            d.text(bx + 8, oy - 8, out["title"], "tt")
            d.text(bx + 8, oy + 8, out["sub"], "ts")
            d.line([(dx + dw + STUB, oy), (bx - STUB, oy)], "wb")
            d.line([(bx - STUB, oy), (bx, oy)])
            if out.get("mark"):
                _marker(d, bx + bw - 8, oy - 28, out["mark"])
    # footer notes
    ny = bottom + 34
    d.text(20, ny, "Notes", "tt")
    ny += 20
    for n, text in notes:
        _marker(d, 27, ny - 3.5, n)
        lines = _wrap(text)
        for i, line in enumerate(lines):
            d.text(44, ny + i * 15, line, "ts")
        ny += 15 * len(lines) + 8
    d.h = ny + 6
    return d.svg()


def v0_sheet_a():
    shared = [("GPIO4 (SDA)", "I2C SDA"), ("GPIO5 (SCL)", "I2C SCL"), ("GPIO1 (INT)", "EXP INT")]
    cam = [("flag", "SIOD (SDA)", "I2C SDA"), ("flag", "SIOC (SCL)", "I2C SCL")]
    for g, n in (("GPIO15", "XCLK"), ("GPIO13", "PCLK"), ("GPIO6", "VSYNC"), ("GPIO7", "HREF"), ("GPIO11", "D0"), ("GPIO9", "D1"),
                 ("GPIO8", "D2"), ("GPIO10", "D3"), ("GPIO12", "D4"), ("GPIO18", "D5"), ("GPIO17", "D6"), ("GPIO16", "D7")):
        cam.append(("wire", n, (g, "end" if n == "XCLK" else "start")))
    devices = [
        {"title": "Camera module", "sub": "OV5640 / OV2640, DVP", "marks": [4, 3], "pins": cam},
        {"title": "RTC breakout", "sub": "DS3231 class", "pins": [("flag", "SDA", "I2C SDA"), ("flag", "SCL", "I2C SCL")]},
        {"title": "I/O expander A", "sub": "MCP23017, 0x20", "marks": [5], "pins": [("flag", "SDA", "I2C SDA"), ("flag", "SCL", "I2C SCL"), ("flag", "INT", "EXP INT")],
         "out": {"row": ROW, "pin": "GPA0-5", "title": "Six buttons", "sub": "UP DOWN LEFT RIGHT SEL BACK"}},
        {"title": "I/O expander B", "sub": "MCP23017, 0x21", "marks": [6], "pins": [("flag", "SDA", "I2C SDA"), ("flag", "SCL", "I2C SCL"), ("flag", "INT", "EXP INT")],
         "out": {"row": ROW, "pin": "GPA0-7", "title": "Peripheral controls", "sub": "fingerprint, SD cards, stick port"}},
        {"title": "PTT button", "sub": "", "marks": [7], "pins": [("wire", "to GND", ("GPIO2", "start"))]},
        {"title": "Fingerprint module", "sub": "R503 / 4750, UART", "marks": [8], "pins": [("wire", "RX", ("GPIO40", "end")), ("wire", "TX", ("GPIO41", "start")), ("flag", "IRQ", "EXP B: FP IRQ")]},
        {"title": "Haptic driver", "sub": "", "marks": [9], "pins": [("flag", "gate", "EXP A: HAPTIC")]},
        {"title": "USB-C breakout", "sub": "to the host", "marks": [10], "pins": [("wire", "D+", ("GPIO20", "both")), ("wire", "D-", ("GPIO19", "both"))]},
    ]
    notes = [
        (1, "Power and ground are not drawn. Every module shares a common ground and the 3.3 V rail from the dev board; the power budget is in the Power tree section. Per-module detail with all passives is in the Wiring diagrams section."),
        (2, "One pair of 4.7 k pull-ups to 3.3 V on the shared I2C bus, not one pair per module. Check whether the breakouts already include pull-ups."),
        (3, "The camera's SCCB control lines share the I2C bus only if the camera driver allows it (verify). Otherwise use a second I2C bus on spare pins."),
        (4, "Keep the DVP wires short and of similar length. The module has its own regulators; PWDN and RESET tie-offs are in the camera diagram in the Wiring diagrams section."),
        (5, "Expander A: GPA0-5 are the six buttons (each switches to ground, internal pull-ups on); GPB0 display reset, GPB1 backlight enable, GPB2 haptic gate. Interrupt-on-change. See the buttons diagram in the Wiring diagrams section."),
        (6, "Expander B: GPA0 fingerprint IRQ (input), GPA1 fingerprint power enable, GPA2 and GPA3 System card detect and power enable, GPA4 and GPA5 Vault card detect and power enable, GPA6 stick VBUS enable, GPA7 stick overcurrent fault (input). Both expanders' INT outputs are open-drain and wired together to GPIO1 (verify)."),
        (7, "10 k pull-up to 3.3 V and a 100 nF debounce capacitor. See the buttons diagram in the Wiring diagrams section. GPIO2 can wake the device from deep sleep."),
        (8, "3.3 V logic only. Module VCC goes through a load switch enabled from expander B; the touch supply stays on. TX and RX cross. See the fingerprint diagram in the Wiring diagrams section."),
        (9, "1 k gate resistor, 100 k pull-down, flyback diode across the motor, driven from expander A (on or off, no PWM). See the haptic diagram in the Wiring diagrams section."),
        (10, "ESD protection on D+/D-, 5.1 k pull-downs on both CC pins, a 90 ohm differential pair. In v0 the dev board's own USB connector can serve. See the USB-C diagram in the Wiring diagrams section."),
    ]
    marks = {"GPIO4 (SDA)": 2, "GPIO5 (SCL)": 2}
    return _sheet("v0 wiring, sheet 1 of 2", "dev board, sheet 1 of 2", shared, devices, notes, marks, 1)


def v0_sheet_b():
    shared = [("GPIO21 (SCK)", "SPI SCK"), ("GPIO47 (MOSI)", "SPI MOSI"), ("GPIO48 (MISO)", "SPI MISO")]
    devices = [
        {"title": "2.0\" display", "sub": "ST7789, 4-wire SPI", "marks": [3], "pins": [("flag", "SCK", "SPI SCK"), ("flag", "SDA (MOSI)", "SPI MOSI"),
            ("wire", "CS", ("GPIO39", "end")), ("wire", "DC", ("GPIO14", "end")), ("flag", "RESET", "EXP A: RESET"), ("flag", "BL (via driver)", "EXP A: BL EN")]},
        {"title": "microSD: System", "sub": "SPI mode", "marks": [4], "pins": [("flag", "CLK", "SPI SCK"), ("flag", "DI", "SPI MOSI"), ("flag", "DO", "SPI MISO"), ("wire", "CS", ("GPIO42", "end"))]},
        {"title": "microSD: Vault", "sub": "SPI mode", "marks": [5, 4], "pins": [("flag", "CLK", "SPI SCK"), ("flag", "DI", "SPI MOSI"), ("flag", "DO", "SPI MISO"), ("wire", "CS", ("GPIO35", "end"))]},
        {"title": "USB host chip", "sub": "MAX3421E class", "marks": [6], "pins": [("flag", "SCLK", "SPI SCK"), ("flag", "MOSI", "SPI MOSI"), ("flag", "MISO", "SPI MISO"),
            ("wire", "SS", ("GPIO36", "end")), ("wire", "INT", ("GPIO37", "start"))],
         "out": {"row": 0, "pin": "D+ / D-", "title": "USB-A 2.0 receptacle", "sub": "for the stick, via ESD array", "mark": 7}},
    ]
    notes = [
        (1, "Power and ground are not drawn. Every module shares a common ground and 3.3 V, except the stick's 5 V (note 7). Per-module detail with all passives is in the Wiring diagrams section."),
        (2, "The three SPI nets are shared by the display, both microSD cards and the USB host chip, each with its own chip select. Start with a low SPI clock. On a v1.0 dev board, MISO is GPIO38, not GPIO48, because GPIO48 carries the RGB LED (Pin constraints and Pin map sections)."),
        (3, "Display reset and backlight enable come from expander A, not from MCU pins. The backlight draws about 55 mA and is switched through a transistor (on or off, no PWM). See the display diagram in the Wiring diagrams section."),
        (4, "10 k pull-up on each chip select, a pull-up on the shared MISO line, a load switch per card (enable from expander B) and card detect (expander B). See the SD diagram in the Wiring diagrams section."),
        (5, "The Vault runs in SPI mode on the shared bus, not on the SD host peripheral. This saves pins and costs little: full-speed USB limits the throughput to about 1 MB/s anyway."),
        (6, "Needs a 12 MHz crystal, a 3.3 V supply and ESD protection. The MCU is the USB host here, so allow only the mass-storage class (the Second USB port section). Full speed: about 1 MB/s."),
        (7, "Stick VBUS: a separate powered 5 V through a current-limited load switch, enable and fault on expander B. See the Second USB port section and the USB host diagram in the Wiring diagrams section."),
    ]
    marks = {"GPIO21 (SCK)": 2}
    return _sheet("v0 wiring, sheet 2 of 2", "dev board, sheet 2 of 2", shared, devices, notes, marks, 1)


def ui_screens():
    """Low-fidelity wireframes of the key screens on the 240 x 320 portrait panel."""
    SC = 0.72
    W, H = 240, 320
    cols, gap = 4, 26
    cw, ch = W * SC, H * SC
    rows = 2
    d = D(int(cols * (cw + gap) + gap), int(rows * (ch + 58) + 36), "Screen wireframes (240 x 320 portrait, low fidelity)")

    def screen(i, title, body, hint):
        c, r = i % cols, i // cols
        x = gap + c * (cw + gap)
        y = 30 + r * (ch + 58)
        d.text(x + cw / 2, y - 10, title, "tt", "middle")
        d.a(f'<g transform="translate({x},{y}) scale({SC})">')
        d.a(f'<rect class="scrbox" x="0" y="0" width="{W}" height="{H}" rx="10"/>')
        # status bar: protection badge and clock
        d.a(f'<rect class="scrhdr" x="0" y="0" width="{W}" height="26" rx="10"/>')
        d.a('<rect class="scrbadge" x="8" y="5" width="30" height="16" rx="4"/>')
        d.a('<text class="scrbt" x="23" y="17" text-anchor="middle">L1</text>')
        d.a(f'<text class="scrdim" x="{W-10}" y="18" text-anchor="end">14:32</text>')
        body()
        # hint bar with the button actions
        d.a(f'<rect class="scrhint" x="0" y="{H-30}" width="{W}" height="30" rx="0"/>')
        d.a(f'<text class="scrdim" x="{W/2}" y="{H-11}" text-anchor="middle">{hint}</text>')
        d.a('</g>')

    def t(x, y, s, cls="scrtxt", anchor="start"):
        from html import escape as _e
        d.a(f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}">{_e(s)}</text>')

    def ring(cx, cy, r, frac=0.7):
        import math
        d.a(f'<circle class="scrring0" cx="{cx}" cy="{cy}" r="{r}"/>')
        a = 2 * math.pi * frac
        x2, y2 = cx + r * math.sin(a), cy - r * math.cos(a)
        large = 1 if frac > 0.5 else 0
        d.a(f'<path class="scrring" d="M{cx},{cy-r} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f}"/>')

    def b_locked():
        t(W/2, 80, "Locked", "scrbig", "middle")
        t(W/2, 108, "Enter your combo", "scrtxt", "middle")
        for k in range(7):
            d.a(f'<circle class="scrdot" cx="{50+k*23}" cy="150" r="7"/>')
        t(W/2, 200, "Up  Down  Left  Right", "scrdim", "middle")
        t(W/2, 222, "Attempts left: 10", "scrdim", "middle")

    def b_idle():
        t(20, 62, "Dana", "scrbig")
        d.a('<rect class="scrid" x="20" y="78" width="70" height="70" rx="6"/>')
        t(110, 96, "ABCD EF01", "scrtxt"); t(110, 118, "Ed25519", "scrdim")
        t(110, 140, "L1 in RAM + flash", "scrdim")
        d.a('<rect class="scrchip" x="20" y="168" width="200" height="30" rx="6"/>')
        t(30, 188, "Stick detected: unlock", "scrtxt")
        t(20, 232, "3 accounts", "scrdim")

    def b_accounts():
        t(20, 56, "Accounts", "scrbig")
        for k, (n, hl) in enumerate((("GitHub", True), ("Mail", False), ("Bank", False), ("Servers", False))):
            yy = 80 + k * 44
            d.a(f'<rect class="{"scrsel" if hl else "scrrow"}" x="12" y="{yy}" width="216" height="38" rx="6"/>')
            t(24, yy + 25, n)
            t(216, yy + 25, "482 193" if hl else "...", "scrdim", "end")

    def b_code():
        t(W/2, 70, "GitHub", "scrtxt", "middle"); t(W/2, 90, "dana@example.org", "scrdim", "middle")
        t(W/2, 160, "482 193", "scrhuge", "middle")
        ring(W/2, 215, 26, 0.65); t(W/2, 221, "19", "scrtxt", "middle")

    def b_qr():
        import random
        random.seed(7)
        n, cell = 25, 6
        x0, y0 = (W - n * cell) / 2, 42
        for r_ in range(n):
            for c_ in range(n):
                finder = (r_ < 7 and c_ < 7) or (r_ < 7 and c_ >= n - 7) or (r_ >= n - 7 and c_ < 7)
                if finder or random.random() < 0.5:
                    d.a(f'<rect class="scrqr" x="{x0+c_*cell}" y="{y0+r_*cell}" width="{cell}" height="{cell}"/>')
        t(W/2, 232, "ABCD EF01 2345 6789", "scrdim", "middle")

    def b_confirm():
        t(W/2, 64, "Add account?", "scrbig", "middle")
        t(24, 108, "Issuer: GitHub"); t(24, 132, "Account: dana@example.org", "scrdim")
        t(24, 156, "SHA-1, 6 digits, 30 s", "scrdim")
        ring(W/2, 212, 26, 0.0)
        t(W/2, 218, "hold", "scrdim", "middle")

    def b_host():
        t(W/2, 60, "Sign request", "scrbig", "middle")
        t(24, 100, "From: your computer", "scrdim")
        t(24, 124, "Operation: git commit"); t(24, 148, "Hash: 3FA9 .. 07C2", "scrdim")
        ring(W/2, 212, 26, 0.45)
        t(W/2, 218, "hold", "scrdim", "middle")

    def b_sign():
        t(W/2, 58, "Sign Sam's key?", "scrbig", "middle")
        d.a('<rect class="scrid" x="20" y="72" width="56" height="56" rx="6"/>')
        t(90, 90, "Sam Lee", "scrtxt"); t(90, 110, "ABCD EF01 ...", "scrdim")
        t(20, 156, "UID: sam@example.org", "scrdim")
        d.a('<rect class="scrchip" x="20" y="168" width="200" height="28" rx="6"/>')
        t(30, 187, "I know them personally")
        ring(W/2, 232, 18, 0.0)

    def b_stick():
        t(W/2, 60, "Stick unlocked", "scrbig", "middle")
        t(24, 104, "Encrypted, 16 GB"); t(24, 128, "Read-only:  off", "scrdim")
        d.a('<rect class="scrchip" x="150" y="112" width="70" height="24" rx="12"/>')
        ring(W/2, 212, 26, 0.0)
        t(W/2, 218, "hold", "scrdim", "middle")

    screen(0, "Locked (combo entry)", b_locked, "Select: OK   Back: clear")
    screen(1, "Idle", b_idle, "PTT tap: my QR   D-pad: accounts")
    screen(2, "Accounts", b_accounts, "D-pad: move   Select: open")
    screen(3, "Authenticator code", b_code, "Back")
    screen(4, "My QR", b_qr, "Back")
    screen(5, "Add an account", b_confirm, "Hold PTT + finger: add   Back: no")
    screen(6, "Host request", b_host, "Hold + finger: approve  Back: deny")
    screen(7, "Key signing", b_sign, "Hold PTT + finger: sign   Back: no")
    d.h = int(rows * (ch + 58) + 40)
    return d.svg()


def ui_state():
    """Orthogonal UI state machine: Idle is the hub, each flow is a straight chain."""
    d = D(1480, 900, "UI state machine")
    BW, BH = 100, 44
    ix, iw = 250, 120
    ir = ix + iw

    def box(x, yc, name, sub=None, cls="st", w=None):
        w = w or BW
        d.rrect(x, yc - BH / 2, w, BH, 8, cls)
        d.text(x + w / 2, yc - 2 if sub else yc + 5, name, "stn", "middle")
        if sub:
            d.text(x + w / 2, yc + 13, sub, "sts", "middle")

    def lab(x1, x2, yc, lines):
        """Label an arrow: inline above the arrow if it fits, otherwise above the box row."""
        wd = max(len(l) for l in lines) * 5.9
        mid = (x1 + x2) / 2
        if wd <= (x2 - x1) - 6:
            y0 = yc - 7 - (len(lines) - 1) * 13
        else:
            y0 = yc - BH / 2 - 8 - (len(lines) - 1) * 13
        for i, l in enumerate(lines):
            d.text(mid, y0 + i * 13, l, "sts", "middle")

    def arrow(x1, x2, yc, lines=None, cls="w"):
        d.line([(x1, yc), (x2, yc)], cls, "end")
        if lines:
            lab(x1, x2, yc, lines)

    def pill(x, yc, lines):
        d.rrect(x, yc - 15, 62, 30, 15, "pill")
        d.text(x + 31, yc + 4, "Idle", "stn", "middle")
        arrow(x - 70, x, yc, lines)

    def chain(yc, first, items, end_lines):
        x = 470
        arrow(ir, x, yc, first)
        for k, (name, sub, before) in enumerate(items):
            if k > 0:
                arrow(x - 60, x, yc, before)
            box(x, yc, name, sub)
            x += BW + 60
        pill(x - 60 + 70, yc, end_lines)

    # Idle hub
    d.rrect(ix, 30, iw, 820, 10, "stidle")
    d.text(ix + iw / 2, 56, "Idle", "stn", "middle")
    d.text(ix + iw / 2, 72, "the hub", "sts", "middle")

    # simple chains
    chain(70, ["PTT tap"], [("ShowQR", "my QR", None)], ["Back or", "timeout"])
    chain(150, ["D-pad /", "Select"], [("Accounts", "list", None), ("TOTPCode", "code + ring", ["Select"])], ["Back"])
    chain(570, ["USB request"], [("HostRequest", "origin, summary", None)], ["approve: hold + finger", "deny: Back"])
    chain(650, ["System card", "inserted"], [("CardPrompt", "what was found", None)], ["proceed: hold", "ignore: Back"])
    chain(730, ["fingerprint,", "card detected"], [("VaultPrompt", "unlocked", None), ("Connected", "drive on host", ["hold = connect"])], ["Back, unplug,", "or timeout"])
    chain(810, ["fingerprint,", "stick detected"], [("StickPrompt", "unlocked", None), ("Connected", "drive on host", ["hold = connect"])], ["Back, unplug,", "or timeout"])

    # scan branch: Scan splits into three
    ys, yo, yt = 330, 250, 480
    arrow(ir, 470, ys, ["camera sees", "QR"])
    box(470, ys, "Scan", "camera")
    bus = 600
    d.line([(570, ys), (bus, ys)])
    d.dot(bus, ys)
    d.line([(bus, yo), (bus, yt)])
    # up: ConfirmOTP
    d.line([(bus, yo), (690, yo)], "w", "end"); lab(bus, 690, yo, ["TOTP QR"])
    box(690, yo, "ConfirmOTP", "issuer, account")
    pill(690 + BW + 70, yo, ["add: hold + finger", "no: Back"])
    # straight: key exchange chain
    d.line([(bus, ys), (690, ys)], "w", "end"); lab(bus, 690, ys, ["peer key QR"])
    box(690, ys, "ConfirmExchange", "peer, fingerprint", w=124)
    arrow(814, 874, ys, ["PTT hold"]); box(874, ys, "Challenge", "key proof")
    arrow(974, 1034, ys, ["proven"]); box(1034, ys, "HumanCheck", "know them?")
    ysg = 410
    d.line([(1084, ys + BH / 2), (1084, ysg - BH / 2)], "w", "end")
    d.text(1076, ys + BH / 2 + 18, "personally or", "sts", "end"); d.text(1076, ys + BH / 2 + 31, "ID checked", "sts", "end")
    box(1034, ysg, "Sign", "UIDs, level")
    arrow(1134, 1214, ysg, ["hold + finger"]); box(1214, ysg, "ReturnCert", "certificate")
    pill(1214 + BW + 70, ysg, ["certificate", "delivered"])
    # down: ShowText
    d.line([(bus, ys), (bus, yt)])
    d.line([(bus, yt), (690, yt)], "w", "end"); lab(bus, 690, yt, ["unknown QR"])
    box(690, yt, "ShowText", "refused")
    pill(690 + BW + 70, yt, ["Back"])

    # left side: Locked and Settings
    d.dot(70, 230)
    d.line([(70, 230), (70, 268)], "w", "end")
    d.text(80, 252, "power-up", "sts")
    d.rrect(20, 268, 100, 44, 8, "st"); d.text(70, 288, "Locked", "stn", "middle"); d.text(70, 303, "combo entry", "sts", "middle")
    arrow(120, ix, 280, ["combo"])
    d.line([(ix, 302), (120, 302)], "w", "end")
    d.text((120 + ix) / 2, 318, "Back (long),", "sts", "middle"); d.text((120 + ix) / 2, 331, "timeout", "sts", "middle")
    d.line([(70, 312), (70, 388)], "w", "end")
    d.text(78, 352, "Back held", "sts"); d.text(78, 365, "at power-on", "sts")
    d.rrect(20, 388, 100, 44, 8, "st"); d.text(70, 408, "Settings", "stn", "middle"); d.text(70, 423, "two levels", "sts", "middle")
    arrow(120, ix, 410, ["Back"])

    d.text(20, 872, "Back from any other screen returns to Idle unless noted. A dashed Idle marks the end of a flow.", "ts")
    d.text(20, 888, "hold + finger is the approval gate: hold PTT while a fingerprint is read (the combo is the fallback).", "ts")
    return d.svg()


DIAGRAMS = {
    "system": system, "ui_state": ui_state, "ui_screens": ui_screens, "mech_v1": mech_v1, "stackup": stackup, "v0_sheet_a": v0_sheet_a, "v0_sheet_b": v0_sheet_b, "context": context, "power": power, "overview": overview, "camera": camera, "display": display, "buttons": buttons,
    "i2c": i2c, "fingerprint": fingerprint, "usbhost": usbhost, "usbbroker": usbbroker, "sdcards": sdcards, "usbc": usbc, "haptic": haptic,
}

CSS = """
  .wiring { margin: 1.2rem 0; padding: .6rem; border: 1px solid var(--bs-border-color); border-radius: .5rem; background: var(--bs-body-bg); overflow-x: auto; }
  .wiring-svg { display: block; width: 100%; height: auto; max-width: 900px; margin: 0 auto; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  .wiring-svg .w { stroke: var(--bs-body-color); stroke-width: 1.5; fill: none; }
  .wiring-svg .wb { stroke: var(--accent); stroke-width: 3; fill: none; }
  .wiring-svg .pw { stroke: #c0392b; stroke-width: 1.5; fill: none; }
  [data-bs-theme="dark"] .wiring-svg .pw { stroke: #ff8a7a; }
  .wiring-svg .box { fill: var(--bs-tertiary-bg); stroke: var(--bs-body-color); stroke-width: 1.4; }
  .wiring-svg .boxopt { fill: none; stroke: var(--bs-secondary-color); stroke-width: 1.4; stroke-dasharray: 5 4; }
  .wiring-svg .sym { fill: var(--bs-body-bg); stroke: var(--bs-body-color); stroke-width: 1.4; }
  .wiring-svg .dot { fill: var(--bs-body-color); }
  .wiring-svg .flag { fill: var(--accent-soft); stroke: var(--accent); stroke-width: 1.2; }
  .wiring-svg .arrow { fill: var(--bs-body-color); }
  .wiring-svg text { fill: var(--bs-body-color); font-size: 12px; }
  .wiring-svg .tt { font-weight: 700; font-size: 13px; }
  .wiring-svg .ts { fill: var(--bs-secondary-color); font-size: 11px; }
  .wiring-svg .pn { font-size: 11px; font-weight: 600; }
  .wiring-svg .tp { fill: #c0392b; font-size: 11px; font-weight: 700; }
  [data-bs-theme="dark"] .wiring-svg .tp { fill: #ff8a7a; }
  .wiring-svg .tf { fill: var(--accent); font-size: 11px; font-weight: 700; }
  .wiring-svg .case { fill: var(--bs-tertiary-bg); stroke: var(--bs-body-color); stroke-width: 2; }
  .wiring-svg .glass { fill: var(--bs-secondary-bg); stroke: var(--bs-body-color); stroke-width: 1.2; }
  .wiring-svg .active { fill: var(--accent-soft); stroke: var(--accent); stroke-width: 1.2; }
  .wiring-svg .part { fill: var(--accent); stroke: var(--accent); }
  .wiring-svg .lens { fill: var(--bs-body-color); stroke: none; }
  .wiring-svg .hidden { fill: none; stroke: var(--bs-secondary-color); stroke-width: 1.2; stroke-dasharray: 4 3; }
  .wiring-svg .lead { stroke: var(--bs-secondary-color); stroke-width: 1.5; stroke-dasharray: 6 4; fill: none; }
  .wiring-svg .dimw { stroke: var(--bs-secondary-color); stroke-width: 1; fill: none; }
  .wiring-svg .tdim { fill: var(--bs-secondary-color); font-size: 11px; font-weight: 600; }
  .wiring-svg .mk { fill: var(--accent); stroke: none; }
  .wiring-svg .mkt { fill: var(--bs-body-bg); font-size: 10px; font-weight: 700; }
  .wiring-svg .scrbox { fill: var(--bs-body-bg); stroke: var(--bs-body-color); stroke-width: 2.5; }
  .wiring-svg .scrhdr { fill: var(--accent-soft); stroke: none; }
  .wiring-svg .scrhint { fill: var(--accent-soft); stroke: none; }
  .wiring-svg .scrbadge { fill: var(--accent); stroke: none; }
  .wiring-svg .scrbt { fill: var(--bs-body-bg); font-size: 11px; font-weight: 700; }
  .wiring-svg .scrtxt { fill: var(--bs-body-color); font-size: 15px; }
  .wiring-svg .scrdim { fill: var(--bs-secondary-color); font-size: 13px; }
  .wiring-svg .scrbig { fill: var(--bs-body-color); font-size: 22px; font-weight: 700; }
  .wiring-svg .scrhuge { fill: var(--bs-body-color); font-size: 40px; font-weight: 700; letter-spacing: 2px; }
  .wiring-svg .scrchip { fill: var(--bs-tertiary-bg); stroke: var(--bs-border-color); stroke-width: 1.5; }
  .wiring-svg .scrrow { fill: none; stroke: var(--bs-border-color); stroke-width: 1.5; }
  .wiring-svg .scrsel { fill: var(--accent-soft); stroke: var(--accent); stroke-width: 2; }
  .wiring-svg .scrid { fill: var(--bs-secondary-bg); stroke: var(--bs-body-color); stroke-width: 1.5; }
  .wiring-svg .scrdot { fill: var(--bs-body-color); }
  .wiring-svg .scrring0 { fill: none; stroke: var(--bs-border-color); stroke-width: 7; }
  .wiring-svg .scrring { fill: none; stroke: var(--accent); stroke-width: 7; stroke-linecap: round; }
  .wiring-svg .scrqr { fill: var(--bs-body-color); }
  .wiring-svg .st { fill: var(--bs-tertiary-bg); stroke: var(--bs-body-color); stroke-width: 1.6; }
  .wiring-svg .stidle { fill: var(--accent-soft); stroke: var(--accent); stroke-width: 2.5; }
  .wiring-svg .pill { fill: none; stroke: var(--bs-secondary-color); stroke-width: 1.4; stroke-dasharray: 5 3; }
  .wiring-svg .stn { fill: var(--bs-body-color); font-size: 13px; font-weight: 700; }
  .wiring-svg .sts { fill: var(--bs-secondary-color); font-size: 11px; }
  .wiring-svg .lay0 { fill: var(--bs-secondary-bg); stroke: var(--bs-body-color); stroke-width: 1; }
  .wiring-svg .lay1 { fill: var(--accent-soft); stroke: var(--bs-body-color); stroke-width: 1; }
  .wiring-svg .lay2 { fill: var(--bs-tertiary-bg); stroke: var(--bs-body-color); stroke-width: 1; }
  .wiring-svg .lay3 { fill: var(--accent); fill-opacity: .35; stroke: var(--bs-body-color); stroke-width: 1; }
  .wiring-svg .lay4 { fill: #c0392b; fill-opacity: .25; stroke: var(--bs-body-color); stroke-width: 1; }
  .wiring-svg .lay5 { fill: var(--accent); fill-opacity: .6; stroke: var(--bs-body-color); stroke-width: 1; }
"""
