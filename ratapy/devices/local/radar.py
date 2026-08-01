"""PiRadar -- a 24 GHz mmWave presence/localization radar on the Pi (RD-03D).

The Ai-Thinker **RD-03D** is a 24 GHz FMCW radar that tracks up to three moving
targets and streams each one's position over UART: an (x, y) coordinate in the
horizontal plane, a speed, and a range. Unlike a plain Doppler motion sensor (one
"something moved" bit), this actually *locates* people::

    rp = Raspberry()
    radar = PiRadar(port="/dev/ttyAMA0", board=rp)
    for target in radar.read():          # the targets in the next frame
        print(target.x, target.y, "mm", target.speed, "cm/s")

It is a **serial** device: the RD-03D's TX/RX go to a UART the Pi can read --
the Pi's GPIO UART (`/dev/ttyAMA0` or `/dev/serial0`, enable it in raspi-config)
or a USB-serial adapter (`/dev/ttyUSB0`). The module's DM/DP pins are its USB port
for the vendor config tool; RATA reads the UART stream, so no Arduino and no RATA
firmware are involved. Power is 5 V; the logic is 3.3 V. Default baud 256000.

Frames: header ``AA FF 03 00``, then 3 targets x 8 bytes, footer ``55 CC``. Each
target is x(mm), y(mm), speed(cm/s) as sign-flagged 15-bit values, then range(mm)
as u16; an all-zero slot means "no target". A target's ``x`` is signed left(-) /
right(+) of boresight, ``y`` is distance out in front.

.. warning::
   The byte-level decode here is from the RD-03D protocol docs and is **not yet
   verified against real hardware**. If coordinates look mirrored or wrong, grab
   a frame with :meth:`raw_frame` and check it -- a flipped sign bit is the usual
   culprit. Some units also boot in single-target mode and need the vendor tool
   (or a config command) to enable the 3-target stream this parser expects.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, cast

import serial

from ...protocol import RataError
from .base import LocalDevice

_HEADER = b"\xAA\xFF\x03\x00"
_FOOTER = b"\x55\xCC"
_MAX_TARGETS = 3
_TARGET_BYTES = 8
_REST = _MAX_TARGETS * _TARGET_BYTES + len(_FOOTER)   # bytes after the header


def _signed(lo: int, hi: int) -> int:
    """RD-03D coordinate/speed: 15-bit magnitude, MSB is the SIGN FLAG (1 = +)."""
    raw = lo | (hi << 8)
    mag = raw & 0x7FFF
    return mag if (raw & 0x8000) else -mag


@dataclass(frozen=True)
class RadarTarget:
    """One tracked target from the radar. Distances mm, speed cm/s."""
    x: int              # left (-) / right (+) of boresight, mm
    y: int              # distance out in front, mm
    speed: int          # cm/s, toward (-) / away (+) -- per the module's sign
    distance: int       # reported range, mm

    @property
    def range_mm(self) -> float:
        """Straight-line distance from the radar, from x and y."""
        return math.hypot(self.x, self.y)

    @property
    def angle_deg(self) -> float:
        """Bearing off boresight in degrees: 0 = straight ahead, + = right."""
        return math.degrees(math.atan2(self.x, self.y)) if self.y else 0.0


class PiRadar(LocalDevice):
    """An RD-03D 24 GHz multi-target radar on a Pi serial port. See the module doc.

    Args:
        port: the serial device the radar's TX/RX reach (default the Pi's own
            UART; use e.g. ``/dev/ttyUSB0`` for a USB-serial adapter).
        baud: serial speed (the RD-03D default is 256000).
        board: the Raspberry to attach to (defaults to the current master).
    """

    def __init__(self, port: str = "/dev/ttyAMA0", baud: int = 256000,
                 board: "object | None" = None) -> None:
        super().__init__(board)   # type: ignore[arg-type]  # LocalDevice checks Raspberry
        self.port = port
        self.baud = baud
        self._ser: Any = None

    def _serial(self) -> Any:
        """Open the port on first use (lazy, so construction works off a Pi)."""
        if self._ser is None:
            try:
                self._ser = serial.Serial(self.port, self.baud, timeout=0.5)
            except serial.SerialException as e:
                raise RataError(f"could not open radar on {self.port}: {e}") from e
        return self._ser

    def _read_payload(self, timeout: float) -> bytes:
        """Sync to the next full frame; return its 24-byte target payload."""
        ser = self._serial()
        deadline = time.monotonic() + timeout
        window = b""
        while time.monotonic() < deadline:
            b = cast(bytes, ser.read(1))          # pyserial is untyped
            if not b:
                continue
            window = (window + b)[-len(_HEADER):]
            if window == _HEADER:
                rest = cast(bytes, ser.read(_REST))
                if len(rest) == _REST and rest[-len(_FOOTER):] == _FOOTER:
                    return rest[:-len(_FOOTER)]
                window = b""                      # bad footer -> resync
        raise RataError(
            f"no radar frame on {self.port} within {timeout}s -- check wiring, "
            f"baud ({self.baud}), and that the module is in multi-target mode"
        )

    def read(self, timeout: float = 1.0) -> list[RadarTarget]:
        """The targets in the next frame (empty list = frame seen, nobody in view).

        Blocks until a frame arrives or ``timeout`` seconds pass (then raises).
        Call it in your loop, or from a `BackgroundTasks` task to keep a main
        loop free.
        """
        payload = self._read_payload(timeout)
        targets: list[RadarTarget] = []
        for i in range(_MAX_TARGETS):
            b = payload[i * _TARGET_BYTES:(i + 1) * _TARGET_BYTES]
            if b == bytes(_TARGET_BYTES):         # all-zero slot: no target here
                continue
            targets.append(RadarTarget(
                x=_signed(b[0], b[1]),
                y=_signed(b[2], b[3]),
                speed=_signed(b[4], b[5]),
                distance=b[6] | (b[7] << 8),
            ))
        return targets

    def raw_frame(self, timeout: float = 1.0) -> bytes:
        """One whole frame (header..footer) as raw bytes -- for checking the decode."""
        return _HEADER + self._read_payload(timeout) + _FOOTER

    def _release(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    def __repr__(self) -> str:
        return f"PiRadar(port={self.port!r}, baud={self.baud})"
