"""Master-attached devices -- hardware wired to the Raspberry Pi directly.

Some devices are too heavy to sit behind an Arduino (they need real processing
or bandwidth): cameras, addressable LED strips, OLED displays. These plug into
the Pi (the master) and run in Python here, but keep the same object API as a
firmware device -- you just pass the Raspberry as the board::

    rp = Raspberry()
    cam = PiCamera(board=rp)          # Picamera2 + OpenCV
    strip = PiNeoPixel(count=30, board=rp)

Everything here is re-exported from `ratapy.devices`, so end users never import
this subpackage directly:

    from ratapy.devices import PiCamera, PiCam, PiNeoPixel

Backing libraries (Picamera2, OpenCV, rpi_ws281x) are Pi-only. `PiCamera` and
`PiNeoPixel` are therefore imported **lazily** (PEP 562): the base class and other
consumers can `from ratapy.devices.local.base import LocalDevice` on a plain PC
without dragging in those libraries, and only touching `PiCamera`/`PiNeoPixel`
actually imports them (raising the library's own ImportError if absent).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import LocalDevice

if TYPE_CHECKING:
    from .adxl345 import PiADXL345
    from .radar import PiRadar, RadarTarget
    from .audio import PiMicrophone, PiSpeaker
    from .camera import Frame, PiCam, PiCamera
    from .neopixel import Color, PiNeoPixel

# name -> submodule that defines it; imported on first access only.
_LAZY: dict[str, str] = {
    "PiADXL345": "adxl345",
    "PiRadar": "radar",
    "RadarTarget": "radar",
    "PiMicrophone": "audio",
    "PiSpeaker": "audio",
    "PiCamera": "camera",
    "PiCam": "camera",
    "Frame": "camera",
    "PiNeoPixel": "neopixel",
    "Color": "neopixel",
}


def __getattr__(name: str) -> Any:
    """Import a Pi-only device on first use (PEP 562)."""
    module = _LAZY.get(name)
    if module is not None:
        from importlib import import_module

        mod = import_module(f".{module}", __name__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
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
]
