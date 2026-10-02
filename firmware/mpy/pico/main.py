# main.py - the board runs this at every power-up and after a reset: start the interim rig.
#
# It is what makes a restart really restart: the chip reboots and the rig comes straight back
# (locked), with no computer needed. To stop it booting into the rig, delete this file from the
# board (`mpremote fs rm :main.py`). Thonny and mpremote interrupt it normally.

import pico_main

pico_main.run()
