"""USB-HID gadget devices -- the Pi presented to a host PC as a gamepad + drive.

Master-attached devices (like `ratapy.devices.local`) that make the Raspberry
*itself* a USB peripheral via Linux gadget mode:

- `Gamepad` -- a USB joystick whose buttons/axes are fed from RATA input devices.
- `Storage` -- toggle whether the Pi also appears as a removable drive.

Both need a Raspberry created with ``usb_device=True``. On a machine that can't be
a USB gadget they fall back to a logged simulation (unless ``usb_strict=True``), so
scripts and tests still run anywhere. Re-exported from `ratapy.devices`.

Unlike `local/`, nothing here imports a Pi-only library (it is all ConfigFS +
`/dev/hidgN` filesystem I/O), so this package imports on any machine.
"""

from __future__ import annotations

from .gadget import Identity
from .gamepad import Gamepad
from .storage import Storage

__all__ = ["Gamepad", "Storage", "Identity"]
