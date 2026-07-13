"""RATA -- Raspberry-pi Attached Things.

Control LEDs, motors, servos and sensors on one or more Arduinos from Python,
with every device configured dynamically at runtime.

The package is organised into submodules -- import what you need from each:

    from ratapy import Raspberry              # the master (top-level)
    from ratapy.boards import Mega, Uno, Nano, Leonardo, Micro # board models
    from ratapy.devices import (              # everything you attach to a board
        DigitalOutput, PWM, Servo, DigitalInput, AnalogInput,   # firmware-backed
        StepperWithDriver, Ultrasonic, DHT, RotaryEncoder,
        LED, DimmableLED, Button, Potentiometer, RGBLED, Joystick,  # conveniences
        Camera, Cam, NeoPixel,                 # wired to the Pi itself
    )
    from ratapy.executor import ParallelExecutor
    from ratapy.link import SerialLink, I2CLink

`ratapy.devices` gathers three groups behind one import: `complex_devices` (need
firmware), `simple_devices` (pure-Python helpers), and `local` (heavy devices --
Camera, NeoPixel -- wired to the Raspberry Pi itself, passing the Raspberry as
the board).

Quick start::

    from ratapy import Raspberry
    from ratapy.boards import Mega
    from ratapy.devices import LED

    rp = Raspberry(port="/dev/ttyUSB0")
    board = Mega("A")
    rp.register_arduino(board)

    LED(pin=2, board=board).blink(3)

Only the master and the error type live at the top level; boards, devices and
components come from their submodules. See README.md for the full guide.
"""

from __future__ import annotations

from .protocol import RataError
from .raspberry import Raspberry

__all__ = ["Raspberry", "RataError"]

__version__ = "0.1.0"
