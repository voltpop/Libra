# Wiring the interim UI rig

Raspberry Pi Pico (or Pico 2) + a 1602 LCD + up to seven push buttons.
`pico_config.py` has `LCD_MODE`: `"parallel"` for a bare 16-pin module (the default), `"i2c"` for a
module with a PCF8574 backpack, `"text"` for no display. Pin numbers below are the **physical pin**
(1 to 40) and the **GPIO** name; the config uses GPIO numbers.

## Pico pins used (USB connector at the top)

```
            +-----[ USB ]-----+
  GP0   1  |o               o| 40  VBUS (5 V)  <- LCD VDD, backlight A
  GP1   2  |o               o| 39  VSYS
  GND   3  |o  <- LCD GND   o| 38  GND
  GP2   4  |o  <- LCD RS    o| 37  3V3_EN
  GP3   5  |o  <- LCD E     o| 36  3V3(OUT)
  GP4   6  |o  <- LCD D4    o| 35  ADC_VREF
  GP5   7  |o  <- LCD D5    o| 34  GP28
  GND   8  |o  <- LCD GND   o| 33  GND
  GP6   9  |o  <- LCD D6    o| 32  GP27
  GP7  10  |o  <- LCD D7    o| 31  GP26
  GP8  11  |o               o| 30  RUN
  GP9  12  |o               o| 29  GP22  <- PTT
  GND  13  |o               o| 28  GND   <- button board GND
  GP10 14  |o               o| 27  GP21  <- BACK
  GP11 15  |o               o| 26  GP20  <- SELECT
  GP12 16  |o               o| 25  GP19  <- RIGHT
  GP13 17  |o  <- LED R     o| 24  GP18  <- LEFT
  GND  18  |o  <- LED GND   o| 23  GND   <- button board GND
  GP14 19  |o  <- LED G     o| 22  GP17  <- DOWN
  GP15 20  |o  <- LED B     o| 21  GP16  <- UP
            +-----------------+
```

## A bare 16-pin module (LCD_MODE = "parallel")

The module's pins are printed on its board: `VSS VDD V0 RS RW E D0 D1 D2 D3 D4 D5 D6 D7 A K`
(pin 1 to pin 16). Check the labels on yours before wiring.

| Module pin | Name | Connect to |
|---|---|---|
| 1 | VSS | GND |
| 2 | VDD | Pico pin 40 (VBUS, 5 V) |
| 3 | V0 (contrast) | the **middle** leg of a ~10 kΩ pot whose outer legs go to 5 V and GND. No pot: try V0 to GND through 1 to 2 kΩ |
| 4 | RS | Pico pin 4 (GP2) |
| 5 | RW | **GND**. Never to a Pico pin: the module must only listen |
| 6 | E | Pico pin 5 (GP3) |
| 7 to 10 | D0 to D3 | leave unconnected (4-bit mode) |
| 11 | D4 | Pico pin 6 (GP4) |
| 12 | D5 | Pico pin 7 (GP5) |
| 13 | D6 | Pico pin 9 (GP6) |
| 14 | D7 | Pico pin 10 (GP7) |
| 15 | A (backlight +) | 5 V through a ~220 Ω resistor |
| 16 | K (backlight −) | GND |

That is the six signal wires to the Pico: **RS, E, D4, D5, D6, D7**.

Why this is safe for the Pico: the module runs at 5 V, but the Pico only drives it. RW is tied to
GND, so the module never outputs anything, and no 5 V ever reaches a Pico pin. The Pico's 3.3 V
signals are normally accepted as logic high by a 5 V module (the datasheet minimum is about 2.2 V),
though a particular module can be fussy. If the text is garbled, check the wires and contrast first.

Power from the Pico's USB: the module and backlight draw roughly 30 to 60 mA, which USB handles.
Ground everything together: use any Pico GND pin (3 or 8 is closest) and a breadboard ground rail.

## A module with an I2C backpack (LCD_MODE = "i2c")

The backpack has a 4-pin header and its own small chip. Set `LCD_MODE = "i2c"` and wire:

| Backpack | Pico |
|---|---|
| GND | pin 3 |
| VCC | pin 36 (3V3) for the safe option |
| SDA | pin 6 (GP4) |
| SCL | pin 7 (GP5) |

If you power it from 5 V instead, first measure SDA to GND with SDA and SCL **not connected**: about
5 V means the backpack's pull-ups go to 5 V, which the original Pico (RP2040) does not tolerate.
Remove the two pull-ups, use a level shifter, or power it from 3V3. The Pico 2 (RP2350) is documented
as more tolerant but I have not checked that against its datasheet, so do not rely on it.

## The RGB status LED (4 pins, on GP13, GP14, GP15)

A common 4-pin RGB LED has three colour legs and one common leg (the longest). Default wiring:

| LED leg | Goes to |
|---|---|
| Red, through a 220 ohm resistor | Pico pin 17 (GP13) |
| Green, through a 220 ohm resistor | Pico pin 19 (GP14) |
| Blue, through a 220 ohm resistor | Pico pin 20 (GP15) |
| Common (longest leg), **common cathode** | GND (pin 18, between GP13 and GP14, is handy) |
| Common (longest leg), **common anode** | 3V3 (pin 36), and set `LED_COMMON = "anode"` in `pico_config.py` |

**Each colour leg needs its own series resistor** (about 220 to 330 ohm). Without one the LED, and
the Pico pin, can be damaged. Green and blue are dimmer than red at the same resistor; that is normal.
Not sure which kind you have? Wire it as cathode and run `pico_main.led_test()`: it shows OFF, red,
green, blue and white. If it is lit during OFF, or the colours are inverted, set
`LED_COMMON = "anode"`. If the colours come in the wrong order, swap the pins in `LED_PINS`.
`pico_main.led_demo()` then plays every state once, labelled.

What the LED means:

| LED | Meaning |
|---|---|
| dim steady blue | powered and unlocked |
| blue breathing slowly | powered and locked |
| colour sweeping continuously between green and blue | waiting for you to hold PTT (an approval is on screen) |
| blue fading to green while you hold PTT | an approval hold filling; green flash when it commits |
| green double blink | success (saved, set, moved, approved by combo) |
| red triple blink | error (wrong combo, bad QR, request expired) |
| short white blink | a PTT tap (the harmless action) |
| short orange blip | a hold released too early |
| cyan pulses | a request arrived from the computer |
| steady purple | a code is on screen |
| solid red | wiped |

## The buttons (on their own board)

The seven buttons start at **GP16** and run up the Pico's right-hand edge from the bottom (USB at the top): Up, Down, Left, Right, Select, Back, then PTT last. The
button board needs **eight wires**: seven signals and one common ground. Use GND pin 23 or 28, which
sit in the middle of the button pins. If the board has bare switches, each switch connects its
signal to GND when pressed and nothing else is needed: the Pico's internal pull-ups are on.

| Button | GPIO | Pico pin |
|---|---|---|
| Up | GP16 | 21 |
| Down | GP17 | 22 |
| Left | GP18 | 24 |
| Right | GP19 | 25 |
| Select | GP20 | 26 |
| Back | GP21 | 27 |
| PTT | GP22 | 29 |
| common GND | | 23 or 28 |

Keep the cable short (under about 30 cm); a ribbon cable or twisted pairs help. If the button board
has its own power, resistors or LEDs, or pulls signals to 5 V, **do not connect it** until the levels
are checked: the original Pico's pins are not 5 V-safe, and a board that pulls to a supply reads
the opposite way round to what this rig expects.

Wire fewer if you like: set an unused button to `None` in `pico_config.py` and use the console
(`press u`, `press p 1800`). A button that is not connected is harmless. If your board's order
differs, edit the `BUTTONS` table in `pico_config.py`.

## Checking it

Run the interactive test. In Thonny: open `run_hwtest.py` from the Pico (File > Open > "Raspberry Pi
Pico") and press Run, or type `import pico_main` then `pico_main.hwtest()` in the Shell. With mpremote
(Thonny closed): `mpremote run pico/run_hwtest.py`.

- The LCD shows `Button test  0/7` and "Press a button". If it is blank, fix the display first (see
  the table below). The Shell prints `LCD: parallel on GP2, GP3, GP4, GP5, GP6, GP7`; a parallel
  module cannot be detected, so you confirm it by looking.
- Press each button. The display shows `> UP 0.3s`: the name and how long you are holding it, and the
  top line counts `3/7`. The Shell prints each press with its GPIO number.
- When all seven have been seen it shows `ALL 7 OK!`. If you stop early, or the 3-minute window runs
  out, it lists the buttons it never saw (scrolling on the display, and in the Shell).
- A name that differs from the button you pressed means the board's order differs from the table
  above: edit `BUTTONS` in `pico_config.py`.

Then try the rig itself: `pico_main.run()`, type `unlock`, then `host sign`, and hold PTT for about two
seconds. The top line fills with `#` and then shows Approved.

## If something is wrong

| Symptom | Likely cause |
|---|---|
| Nothing on the display, backlight on | contrast: turn the pot; or V0 is not wired |
| Row of solid blocks on the top line, nothing else | the module is powered and the contrast is fine, but it never got initialised: check E, RS, D4 to D7 and that RW is on GND |
| Garbled or shifted characters | a data wire (D4 to D7) is loose or swapped; check against the table |
| Text on the wrong line or only one line | the module may be a 1601 (one line) or the E wire is loose |
| Backlight off | pin 15 or 16 not connected, or no resistor-limited 5 V on A |
| A button does nothing | its pin number in `pico_config.py`, and the other leg must go to GND |
| A button acts pressed all the time | that pin is shorted to GND |
