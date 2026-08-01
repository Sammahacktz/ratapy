"""Devices -- everything you attach to a board.

Several kinds, split across the files but imported from here as one surface:

- abstract_devices.py -- pure abstract contracts (`AbstractServo`, `AbstractLED`,
  ...). Each names the methods a device must have; both the Arduino version and
  the Pi version inherit the matching one, so the two are guaranteed to match. No
  logic lives here. Type against these for code that takes either transport.

- complex_devices.py -- devices that need custom firmware support (a matching
  Device subclass in the Arduino firmware): DigitalOutput, PWM, Servo,
  DigitalInput, AnalogInput, StepperWithDriver, Ultrasonic, DHT, RotaryEncoder.

- simple_devices.py -- "simple" devices: pure-Python conveniences built on the
  complex ones by inheritance or composition, with no new firmware. LED, Relay,
  Buzzer, DimmableLED, Button, RGBLED, Joystick, ...

- local/ -- master-attached devices, driven in Python on the Raspberry Pi itself
  (you pass the Raspberry as the board). Two sorts: the heavy ones that can't sit
  on an Arduino (PiCamera, PiNeoPixel, PiRadar, ...), and the **GPIO twins** of the
  Arduino devices (`PiLED`, `PiButton`, `PiServo`, ... -- gpiozero-backed), so the
  same device can run behind an Arduino or on the Pi's own pins.

- hid/ -- the Pi presented to a host PC as a USB gamepad (`Gamepad`) + drive
  (`Storage`), fed from RATA input devices. Needs a Raspberry with usb_device=True.

Import any of them from `ratapy.devices`; which file they live in is an internal
detail.

    from ratapy.devices import DigitalOutput, RotaryEncoder   # firmware-backed
    from ratapy.devices import LED, Button, RGBLED            # conveniences
    from ratapy.devices import PiLED, PiButton, PiServo       # on the Pi's own GPIO
    from ratapy.devices import PiCamera, PiNeoPixel           # heavy Pi devices
    from ratapy.devices import AbstractServo                  # the shared contract

The master-attached devices in `local/` pull in Pi-only libraries (picamera2,
rpi_ws281x -- the optional `pi` Poetry group). They are imported *lazily*: this
module loads them only when you actually reference `PiCamera`/`PiNeoPixel`/..., so
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
    DS18B20,
    DS18S20,
    DS1822,
    ADXL345,
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
    Solenoid,
    ContinuousServo,
    Potentiometer,
    LightSensor,
    TMP36,
    SoilMoisture,
    MQ2,
    Button,
    LimitSwitch,
    MotionSensor,
    RGBLED,
    Joystick,
    RotarySwitch,
)
# The Pi GPIO pin labels (PiPin.GPIO17). Pure enum, no Pi-only libs, so it imports
# eagerly and off-Pi -- unlike the Pi devices themselves (resolved lazily below).
from .local.pins import GPIOLike, PiPin
# The abstract contracts every device implements on BOTH transports. Type against
# these to write code that takes either an Arduino device or its Pi twin.
from .abstract_devices import (
    AbstractDigitalOutput,
    AbstractLED,
    AbstractRelay,
    AbstractBuzzer,
    AbstractSolenoid,
    AbstractPWM,
    AbstractDimmableLED,
    AbstractDCMotor,
    AbstractMosfet,
    AbstractRGBLED,
    AbstractServo,
    AbstractContinuousServo,
    AbstractDigitalInput,
    AbstractButton,
    AbstractLimitSwitch,
    AbstractMotionSensor,
    AbstractUltrasonic,
    AbstractRotaryEncoder,
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
        PiADXL345,
        PiRadar,
        RadarTarget,
        PiMicrophone,
        PiSpeaker,
        PiCamera,
        PiCam,
        Frame,
        PiNeoPixel,
        Color,
        PiDigitalOutput,
        PiLED,
        PiRelay,
        PiBuzzer,
        PiSolenoid,
        PiPWM,
        PiDimmableLED,
        PiDCMotor,
        PiMosfet,
        PiRGBLED,
        PiDigitalInput,
        PiButton,
        PiLimitSwitch,
        PiMotionSensor,
        PiUltrasonic,
        PiRotaryEncoder,
        PiServo,
        PiContinuousServo,
    )

_LOCAL_EXPORTS = frozenset({
    "LocalDevice", "PiADXL345", "PiRadar", "RadarTarget", "PiMicrophone",
    "PiSpeaker", "PiCamera", "PiCam", "Frame", "PiNeoPixel", "Color",
    # GPIO devices (gpiozero-backed) -- the Pi twins of the Arduino devices
    "PiDigitalOutput", "PiLED", "PiRelay", "PiBuzzer", "PiSolenoid", "PiPWM",
    "PiDimmableLED", "PiDCMotor", "PiMosfet", "PiRGBLED", "PiDigitalInput",
    "PiButton", "PiLimitSwitch", "PiMotionSensor", "PiUltrasonic",
    "PiRotaryEncoder", "PiServo", "PiContinuousServo",
})


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
    "DS18B20",
    "DS18S20",
    "DS1822",
    "ADXL345",
    "DHTReading",
    "RotaryEncoder",
    # simple (pure-Python convenience) devices
    "LED",
    "DimmableLED",
    "DCMotor",
    "Mosfet",
    "Relay",
    "Buzzer",
    "Solenoid",
    "ContinuousServo",
    "Potentiometer",
    "LightSensor",
    "TMP36",
    "SoilMoisture",
    "MQ2",
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
    # abstract contracts (shared by each Arduino device and its Pi twin)
    "AbstractDigitalOutput",
    "AbstractLED",
    "AbstractRelay",
    "AbstractBuzzer",
    "AbstractSolenoid",
    "AbstractPWM",
    "AbstractDimmableLED",
    "AbstractDCMotor",
    "AbstractMosfet",
    "AbstractRGBLED",
    "AbstractServo",
    "AbstractContinuousServo",
    "AbstractDigitalInput",
    "AbstractButton",
    "AbstractLimitSwitch",
    "AbstractMotionSensor",
    "AbstractUltrasonic",
    "AbstractRotaryEncoder",
    # master-attached devices (run on the Raspberry Pi itself; Pi* prefix)
    "LocalDevice",
    "PiADXL345",
    "PiRadar",
    "RadarTarget",
    "PiMicrophone",
    "PiSpeaker",
    "PiCamera",
    "PiCam",
    "Frame",
    "PiNeoPixel",
    "Color",
    # GPIO devices on the Pi itself (gpiozero-backed twins of the Arduino devices)
    "PiDigitalOutput",
    "PiLED",
    "PiRelay",
    "PiBuzzer",
    "PiSolenoid",
    "PiPWM",
    "PiDimmableLED",
    "PiDCMotor",
    "PiMosfet",
    "PiRGBLED",
    "PiDigitalInput",
    "PiButton",
    "PiLimitSwitch",
    "PiMotionSensor",
    "PiUltrasonic",
    "PiRotaryEncoder",
    "PiServo",
    "PiContinuousServo",
    # Pi GPIO pin labels
    "PiPin",
    "GPIOLike",
]
