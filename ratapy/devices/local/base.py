"""LocalDevice -- the base for devices attached to the master itself.

Most RATA devices hang off an Arduino and are driven over the wire protocol.
Some devices, though, need too much processing (or bandwidth) to sit behind a
little AVR: cameras, addressable LED strips, OLED displays. Those plug straight
into the Raspberry Pi (the master) and do their work in Python, on the Pi.

The user-facing API is deliberately the *same* as a normal device -- you pass a
``board=``, except here the board is the Raspberry itself::

    rp = Raspberry()
    cam = Camera(board=rp)
    strip = NeoPixel(count=30, board=rp)

Under the hood there is no Arduino, no `Link`, no protocol frame -- a LocalDevice
talks to Pi hardware directly through a Python library (Picamera2, rpi_ws281x,
...). What it shares with a firmware device is the object model and the
lifecycle: the Raspberry tracks it and closes it in `Raspberry.close()`.
"""

from __future__ import annotations

from abc import ABC

from ...protocol import RataError
from ...raspberry import Raspberry


class LocalDevice(ABC):
    """Base class for devices wired to the master (the Raspberry Pi) directly.

    Subclasses drive real Pi hardware in Python. They should:

    - call ``super().__init__(board)`` first (registers for cleanup);
    - import their backing library (picamera2, rpi_ws281x, ...) at module top --
      those live in the optional ``pi`` Poetry group, and `ratapy.devices` loads
      these modules lazily so RATA still imports on a non-Pi machine;
    - open the actual hardware lazily (in a method / on first use, not in
      ``__init__``), and override :meth:`_release` to shut it down.
    """

    def __init__(self, board: Raspberry | None = None) -> None:
        resolved = board if board is not None else Raspberry.current()
        if not isinstance(resolved, Raspberry):
            raise RataError(
                f"{type(self).__name__} attaches to the Raspberry (the master), "
                f"not to {resolved!r} -- pass board=<your Raspberry>. "
                "Devices that run on an Arduino live in ratapy.devices instead."
            )
        self._board: Raspberry = resolved
        self._closed: bool = False
        self._board._register_local(self)

    @property
    def board(self) -> Raspberry:
        """The master this device is attached to."""
        return self._board

    def close(self) -> None:
        """Release any hardware this device holds.

        Called automatically by :meth:`Raspberry.close` (and by using the device
        as a context manager). Idempotent -- override :meth:`_release` to add the
        actual teardown instead of overriding this.
        """
        if self._closed:
            return
        self._closed = True
        self._release()

    def _release(self) -> None:
        """Hardware teardown hook -- override in subclasses. Called once."""

    def __enter__(self) -> "LocalDevice":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
