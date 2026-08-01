"""LocalDevice -- the base for devices attached to the master itself.

Most RATA devices hang off an Arduino and are driven over the wire protocol.
Some devices, though, need too much processing (or bandwidth) to sit behind a
little AVR: cameras, addressable LED strips, OLED displays. Those plug straight
into the Raspberry Pi (the master) and do their work in Python, on the Pi.

The user-facing API is deliberately the *same* as a normal device -- you pass a
``board=``, except here the board is the Raspberry itself::

    rp = Raspberry()
    cam = PiCamera(board=rp)
    strip = PiNeoPixel(count=30, board=rp)

Under the hood there is no Arduino, no `Link`, no protocol frame -- a LocalDevice
talks to Pi hardware directly through a Python library (Picamera2, rpi_ws281x,
...). What it shares with a firmware device is the object model and the
lifecycle: the Raspberry tracks it and closes it in `Raspberry.close()`.
"""

from __future__ import annotations

import math
import time
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
        # Monotonic instant a running background action is due to finish (0.0 =
        # idle). Drives is_busy()/wait() -- see _mark_busy(). Effectful devices
        # (a PiServo mid-sweep, a PiLED mid-blink) set this; readers never do.
        self._busy_until: float = 0.0
        self._board._register_local(self)

    @property
    def board(self) -> Raspberry:
        """The master this device is attached to."""
        return self._board

    # --- lifecycle, mirroring ratapy.devices.Device -----------------------
    # So a Pi device drives exactly like an Arduino one -- same is_busy()/wait(),
    # so the same `dev.move(...); dev.wait()` shape works, including inside a
    # `with BackgroundTasks():` block. The background work itself is run by
    # gpiozero (the Pi's equivalent of the Arduino's firmware), not by RATA
    # threads; here we only track WHEN it finishes.

    def is_busy(self) -> bool:
        """True while a background action (blink / fade / sweep / pulse) is running.

        Instant devices never set a deadline, so they are never busy -- the same
        default as an Arduino `Device`. Effectful devices report their progress by
        setting a completion time when they start one.
        """
        return time.monotonic() < self._busy_until

    def wait(self, timeout: float | None = None, poll: float = 0.02) -> None:
        """Block until this device's current action finishes.

        Every device has this, so the same loop shape works for all of them (and
        for the Arduino versions): ``dev.blink(3); dev.wait()``. Instant commands
        return at once; a background action polls :meth:`is_busy` until done, or
        raises on ``timeout`` (seconds; ``None`` waits forever).
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.is_busy():
            if deadline is not None and time.monotonic() > deadline:
                raise RataError(f"{self!r} still busy after {timeout}s")
            time.sleep(poll)

    def _mark_busy(self, duration: float | None) -> None:
        """Mark a background action running for ``duration`` s (None = until stopped)."""
        self._busy_until = math.inf if duration is None else time.monotonic() + duration

    def _clear_busy(self) -> None:
        """Mark idle now (a fresh instant command cancels any running action)."""
        self._busy_until = 0.0

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
