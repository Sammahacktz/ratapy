"""Devices -- everything you attach to a board.

Three kinds, split across the files but imported from here as one surface:

- complex_devices.py -- devices that need custom firmware support (a matching
  Device subclass in the Arduino firmware): DigitalOutput, PWM, Servo,
  DigitalInput, AnalogInput, StepperWithDriver, Ultrasonic, DHT, RotaryEncoder.

- simple_devices.py -- "simple" devices: pure-Python conveniences built on the
  complex ones by inheritance or composition, with no new firmware. LED, Relay,
  Buzzer, DimmableLED, Button, RGBLED, Joystick, ...

- local/ -- master-attached devices: hardware wired straight to the Raspberry Pi
  (too heavy for an Arduino) and driven in Python there. Camera (Picamera2 +
  OpenCV), NeoPixel. You pass the Raspberry itself as the board.

- hid/ -- the Pi presented to a host PC as a USB gamepad (`Gamepad`) + drive
  (`Storage`), fed from RATA input devices. Needs a Raspberry with usb_device=True.

Import any of them from `ratapy.devices`; which file they live in is an internal
detail.

    from ratapy.devices import DigitalOutput, RotaryEncoder   # firmware-backed
    from ratapy.devices import LED, Button, RGBLED            # conveniences
    from ratapy.devices import Camera, NeoPixel               # on the Pi itself

The master-attached devices in `local/` pull in Pi-only libraries (picamera2,
rpi_ws281x -- the optional `pi` Poetry group). They are imported *lazily*: this
module loads them only when you actually reference `Camera`/`NeoPixel`/..., so
`import ratapy.devices` still works on a plain PC that only drives Arduinos. On
such a machine, touching one of those names raises the library's own ImportError.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .complex_devices import (
    Device,
    DigitalOutput,
    PWM,
    Servo,
    DigitalInput,
    AnalogInput,
    StepperWithDriver,
    Ultrasonic,
    DHT,
    DHTReading,
    RotaryEncoder,
)
from .simple_devices import (
    LED,
    DimmableLED,
    DCMotor,
    Mosfet,
    Relay,
    Buzzer,
    ContinuousServo,
    Potentiometer,
    LightSensor,
    TMP36,
    SoilMoisture,
    Button,
    LimitSwitch,
    MotionSensor,
    RGBLED,
    Joystick,
    RotarySwitch,
)
# USB-HID gadget devices (the Pi itself as a gamepad + drive). Pure filesystem
# I/O, no Pi-only libraries, so these import on any machine.
from .hid import Gamepad, Identity, Storage, Identity
# Master-attached devices are resolved lazily via __getattr__ (below), so the
# Pi-only imports in `local/` only run when one of these names is used. For type
# checkers we still declare the real imports.
if TYPE_CHECKING:
    from .local import (
        LocalDevice,
        Camera,
        Cam,
        Frame,
        NeoPixel,
        Color,
    )

_LOCAL_EXPORTS = frozenset(
    {"LocalDevice", "Camera", "Cam", "Frame", "NeoPixel", "Color"}
)


def __getattr__(name: str) -> Any:
    """Resolve master-attached devices on first use (PEP 562)."""
    if name in _LOCAL_EXPORTS:
        from . import local
        return getattr(local, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
    # complex (firmware-backed) devices
    "Device",
    "DigitalOutput",
    "PWM",
    "Servo",
    "DigitalInput",
    "AnalogInput",
    "StepperWithDriver",
    "Ultrasonic",
    "DHT",
    "DHTReading",
    "RotaryEncoder",
    # simple (pure-Python convenience) devices
    "LED",
    "DimmableLED",
    "DCMotor",
    "Mosfet",
    "Relay",
    "Buzzer",
    "ContinuousServo",
    "Potentiometer",
    "LightSensor",
    "TMP36",
    "SoilMoisture",
    "Button",
    "LimitSwitch",
    "MotionSensor",
    "RGBLED",
    "Joystick",
    "RotarySwitch",
    # USB-HID gadget devices (the Pi presented to a host as a gamepad + drive)
    "Gamepad",
    "Storage",
    "Identity",
    "Identity",
    # master-attached devices (run on the Raspberry Pi itself)
    "LocalDevice",
    "Camera",
    "Cam",
    "Frame",
    "NeoPixel",
    "Color",
]
