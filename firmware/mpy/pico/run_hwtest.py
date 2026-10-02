# run_hwtest.py - open this on the Pico in Thonny and press Run (or run it with mpremote).
# The LCD shows each button as you press it, with progress n/7. Press Stop to end early.

import pico_main

pico_main.hwtest_all()
