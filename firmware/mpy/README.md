# firmware/mpy

MicroPython prototypes of the pure-logic pieces from the "First code slice" in `LIBRA.md`.
They also run on CPython. The production firmware is C on ESP-IDF; these pin down behaviour
and tests first. Hardware, storage and clock are injected, so every module runs against fakes.

| Module | What it is |
|---|---|
| `lb_oath.py` | TOTP/HOTP, RFC 4226/6238; counter stored before the code is shown |
| `lb_qrparse.py` | Strict allow-list `otpauth://` parser (fuzzed) |
| `lb_session.py` | Unlock gate (combo, counted attempts, delays, wipe) and approval gate |
| `lb_hold.py` | Hold-to-confirm engine |
| `lb_ui.py` | UI model: the screen state machine; `screen()` returns a plain dict, no rendering |
| `lb_settings.py`, `lb_dt.py` | Settings (push to show, weakening needs approval); calendar maths for the Set time page |
| `lb_fakes.py`, `lb_rig.py` | Simulated drivers (clock with time warp, keystore, OATH store, fingerprint) and the wiring of the real modules to them |
| `lb_text.py`, `lb_ticks.py` | Display-safety text rules; wrap-safe millisecond arithmetic |
| `lb_lcd.py`, `lb_console.py`, `lb_samples.py` | 16x2 LCD renderer, text command console, canned QA data |
| `lb_sleep.py` | When the LCD and LED go dark after idle, and wake (pure logic) |
| `lb_hwtest.py` | State of the interactive button test (pure logic) |
| `lb_led.py` | What the RGB status LED shows (blue powered, red error, green success, blue-to-green on a hold) |
| `pico/` | Interim Pico rig: LCD drivers (parallel and I2C), debounced buttons, pin config, `pico_main.py`, `run_hwtest.py`, `WIRING.md` |
| `sim/` | Browser simulator for QA (host only): see below |
| `plugins/` | The one extension seam (hash backends); read its README first |

Run (from this directory):

    for t in lb_oath lb_qrparse lb_hold lb_session lb_ui lb_settings_ui lb_led lb_led_ui lb_sleep lb_hosttime lb_dt lb_settings lb_lcd lb_console lb_hwtest pico_hw sim; do python3 tests/test_$t.py || break; done

`test_sim.py` is host-only (HTTP server); the rest also run on a board.

## UI simulator (for QA)

    python3 sim/sim_server.py          # open http://127.0.0.1:8765/

The real UI model on simulated parts: click the buttons or use the keyboard (arrows, Enter, Esc,
Space). The side panel triggers host requests, scans sample QR codes, breaks the fingerprint or
the clock, skips time, and power-cycles. "Save note" writes the note with the current screen and
the last inputs to `sim/qa_notes.jsonl` (git-ignored). Binds to localhost only; nothing in it is
secure or persistent. The demo combo is Up Down Left Right Up Down Left Right Up Down.

On a board: copy the `lb_*.py` files and the tests to the device, install `unittest`
(Thonny: Tools > Manage packages), and run a test file.

Do not put real secrets on a development board; use the RFC test vectors.

## Interim hardware UI rig (Pico + 1602 LCD + buttons)

Wiring, pin tables and a checklist are in **`pico/WIRING.md`**. In short: a bare 16-pin module uses
six GPIOs (RS, E, D4 to D7 on GP2 to GP7) with RW tied to GND (`LCD_MODE = "parallel"`, the default);
a module with an I2C backpack uses GP4/GP5 (`LCD_MODE = "i2c"`); seven buttons go on GP16 to GP22, each
to GND. Edit `pico/pico_config.py` to change any of it.

Copy every `lb_*.py`, `ucompat.py` and the files in `pico/` to the board's root. Then:

    import pico_main
    pico_main.hwtest()       # interactive: the LCD shows each button as you press it, n/7
    pico_main.lcd_test()     # patterns on the display
    pico_main.selftest()     # scripted check of the logic with the real clock; needs no hardware
    pico_main.run()          # the rig; type console commands in the shell (`help`)

Any display failure falls back to printing the two lines in the shell, and every button also works
as `press u` etc. Notes (`note TEXT`) append to `qa_notes.txt` on the board. To start at power-up,
save `pico_main.py` as `main.py` with a call to `run()`. Quit Thonny before using `mpremote`.

## Using the device (rig or simulator)

| Screen | How |
|---|---|
| Accounts | any direction on Idle |
| Settings | **Select** on Idle: Set time, Time zone, Reorder accounts, Push to show |
| A code | open an account; with **push to show** (on by default) hold PTT to see it, release to hide it |
| Set time | Settings > Set time. Typed in **local time** (see Time zone). Left/Right or Select pick the field, Up/Down change it (hold to repeat). **Hold PTT on that page for 1.5 s to set the clock**; editing a field restarts the hold |
| Time zone | Settings > Time zone. Up/Down change the offset by 15 minutes, Left/Right by an hour (-12:00 to +14:00), Select saves. No daylight-saving rules: change it by hand |
| Reorder | Select grabs, Up/Down move, Select drops, Back cancels |
| Push to show | Select toggles. Turning it off needs a PTT hold; turning it on does not |

The clock is UTC underneath (TOTP needs it); the zone only changes what is displayed and what you type.

The RGB LED (wiring and the colour table are in `pico/WIRING.md`): `pico_main.led_test()` checks the wiring,
`pico_main.led_demo()` plays every state. The browser simulator shows the same LED above the device.
