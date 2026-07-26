"""Beginner example: master -> board -> device.

Shows the non-blocking model: an action (`blink`) hands its whole pattern to the
board and returns at once, so devices run concurrently and `wait()` is how you
block until one finishes.
"""

import time

from ratapy import Raspberry
from ratapy.boards import Mega
from ratapy.devices import LED
from ratapy.executor import ParallelExecutor

rp = Raspberry(port="/dev/ttyUSB0")   # the master owns the bus

ad1 = Mega("A")                       # a specific board model on the bus
rp.register_arduino(ad1)              # ...verified against the flashed firmware

led1 = LED(pin=2, board=ad1)          # two devices on that board
#led2 = LED(pin=3, board=ad1)

# Persist the registry to the board's EEPROM so these devices survive a reset /
# power-cycle -- and so the control panel (which resets the board when it opens
# the port) can still list them after this script ends. Without this, the
# devices live only in RAM and vanish the moment anything reconnects.
ad1.save_devices()

led1.on()
time.sleep(2)
led1.off()

# blink() is non-blocking -- it returns immediately and the board does the
# blinking. So both LEDs blink at the same time, at different rates.
led1.blink(5, on=1, off=0.5)
#led2.blink(5, on=0.1, off=0.2)
#led1.wait()                           # block until each finishes
#led2.wait()

# # Start both blinks in the very same firmware pass (perfectly in sync).
# with ParallelExecutor():
#     led1.blink(5, on=0.2, off=0.2)
#     led2.blink(5, on=0.2, off=0.2)
# led1.wait()
# led2.wait()

rp.close()
