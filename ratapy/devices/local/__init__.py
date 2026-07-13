"""Master-attached devices -- hardware wired to the Raspberry Pi directly.

Some devices are too heavy to sit behind an Arduino (they need real processing
or bandwidth): cameras, addressable LED strips, OLED displays. These plug into
the Pi (the master) and run in Python here, but keep the same object API as a
firmware device -- you just pass the Raspberry as the board::

    rp = Raspberry()
    cam = Camera(board=rp)          # Picamera2 + OpenCV
    strip = NeoPixel(count=30, board=rp)

Everything here is re-exported from `ratapy.devices`, so end users never import
this subpackage directly:

    from ratapy.devices import Camera, Cam, NeoPixel

Backing libraries (Picamera2, OpenCV, rpi_ws281x) are Pi-only. `Camera` and
`NeoPixel` are therefore imported **lazily** (PEP 562): the base class and other
consumers can `from ratapy.devices.local.base import LocalDevice` on a plain PC
without dragging in those libraries, and only touching `Camera`/`NeoPixel`
actually imports them (raising the library's own ImportError if absent).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import LocalDevice

if TYPE_CHECKING:
    from .camera import Cam, Camera, Frame
    from .neopixel import Color, NeoPixel

# name -> submodule that defines it; imported on first access only.
_LAZY: dict[str, str] = {
    "Camera": "camera",
    "Cam": "camera",
    "Frame": "camera",
    "NeoPixel": "neopixel",
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
    "Camera",
    "Cam",
    "Frame",
    "NeoPixel",
    "Color",
]
