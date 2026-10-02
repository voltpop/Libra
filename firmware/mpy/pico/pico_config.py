# pico_config.py - pins and addresses for the interim LCD test rig (edit to match your wiring)
#
# Default wiring (Pico / Pico 2, GPIO numbers not pin numbers). See WIRING.md.
#   LCD_MODE "parallel": a bare 16-pin module on six GPIOs (LCD_PINS below), RW tied to GND
#   LCD_MODE "i2c":      a module with a PCF8574 backpack: SDA = GP4 (pin 6), SCL = GP5 (pin 7)
#   LCD_MODE "text":     no display, print the two lines in the shell
#   Buttons, each between its GPIO and GND:
#     UP GP16, DOWN GP17, LEFT GP18, RIGHT GP19, SELECT GP20, BACK GP21, PTT GP22
#   A button set to None is simply not used; the console (`press u`) covers it.

LCD_MODE = "parallel"
LCD_PINS = {"RS": 2, "E": 3, "D4": 4, "D5": 5, "D6": 6, "D7": 7}  # pins 4, 5, 6, 7, 9, 10

I2C_ID = 0  # used only when LCD_MODE is "i2c"
SDA = 4
SCL = 5
I2C_FREQ = 400000
LCD_ADDRS = (0x27, 0x3F)  # tried in this order if found on the bus

BUTTONS = {
    "UP": 16,      # pin 21
    "DOWN": 17,    # pin 22
    "LEFT": 18,    # pin 24
    "RIGHT": 19,   # pin 25
    "SELECT": 20,  # pin 26
    "BACK": 21,    # pin 27
    "PTT": 22,     # pin 29   (GND for the button board: pin 23 or 28)
}

NOTES_PATH = "qa_notes.txt"
LCD_REFRESH_MS = 120

# RGB status LED (4 pins: one per colour plus the common leg). None disables it.
#   R GP13 (pin 17), G GP14 (pin 19), B GP15 (pin 20); common leg to GND (cathode) or 3V3 (anode).
#   One series resistor (220 to 330 ohm) per colour leg. Run pico_main.led_test() to check the order.
LED_PINS = {"R": 13, "G": 14, "B": 15}
LED_COMMON = "cathode"  # or "anode" if the long leg goes to 3V3
LED_REFRESH_MS = 25

# Idle sleep: with no button or console activity for this long the LCD characters and the LED go
# dark; any button wakes them (that press is not acted on), as does anything needing attention.
# 0 turns it off. Keep it shorter than the session's idle lock (60 s by default).
IDLE_SLEEP_MS = 30000

# Plugged-in symbol (a chain link on the Idle screen): the board's VBUS sense pin.
#   Pico / Pico 2:      GP24 (the number 24)
#   Pico W / Pico 2 W:  the radio chip's WL_GPIO2 (the string "WL_GPIO2"); GP24 is the radio's there
# None turns the symbol off. Your board is a Pico 2 W (checked: reads 1 while plugged in).
USB_SENSE_PIN = "WL_GPIO2"
