"""Servos wired straight to the Raspberry Pi's GPIO (gpiozero-backed).

`PiServo` and `PiContinuousServo` -- the Pi twins of the Arduino `Servo` /
`ContinuousServo`, on top of gpiozero's `AngularServo`. Same contract
(`AbstractServo` / `AbstractContinuousServo`), separate implementation::

    rp = Raspberry()
    arm = PiServo(18)            # GPIO18 (a hardware-PWM pin -- best for a servo)
    arm.angle(90)
    arm.move(0, duration=1.0)    # sweep smoothly over 1 s (non-blocking); arm.wait()

**Pins are BCM GPIO numbers**, not Arduino board pins. A servo is driven by a
50 Hz pulse; gpiozero uses **software** PWM, so the signal jitters and the servo
may buzz -- put it on a hardware-PWM pin (GPIO12/13/18/19) and install ``pigpio``
for a steady hold. The timed ``move()`` sweep runs on gpiozero's own background
``source`` thread (RATA spawns none), so it is non-blocking like the Arduino
version; ``wait()`` blocks until it lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..abstract_devices import AbstractContinuousServo, AbstractServo
from .base import LocalDevice
from .pins import GPIOLike

if TYPE_CHECKING:
    from ...raspberry import Raspberry

_TICK = 0.02          # gpiozero source step (~50 Hz), as for the PWM outputs


class PiServo(LocalDevice, AbstractServo):
    """A hobby servo on a Pi GPIO pin (BCM numbering). Angle 0..180 degrees."""

    def __init__(self, pin: GPIOLike, *, board: "Raspberry | None" = None) -> None:
        self.pin: int = int(pin)
        self._angle: float | None = None           # None until first commanded
        self._dev: Any = None                       # gpiozero AngularServo, lazy
        super().__init__(board)

    def _hw(self) -> Any:
        if self._dev is None:
            from gpiozero import AngularServo
            self._dev = AngularServo(self.pin, min_angle=0, max_angle=180)
            if self._angle is not None:
                self._dev.angle = self._angle
        return self._dev

    @staticmethod
    def _to_value(degrees: float) -> float:
        """0..180 degrees -> gpiozero's -1..1 servo value (min_angle=0, max_angle=180)."""
        return degrees / 90.0 - 1.0

    def angle(self, degrees: int) -> None:
        """Snap to `degrees` (0..180) immediately."""
        if not 0 <= degrees <= 180:
            raise ValueError(f"servo angle must be 0..180, got {degrees}")
        dev = self._hw()
        dev.source = None                           # cancel any running sweep
        dev.angle = float(degrees)
        self._angle = float(degrees)
        self._clear_busy()

    def move(self, degrees: int, duration: float = 0.0) -> None:
        """Move to `degrees` (0..180), sweeping smoothly over `duration` s.

        ``duration=0`` is an instant move (same as `angle`). Otherwise gpiozero's
        background ``source`` eases there (non-blocking); call `wait()` to block
        until it arrives.
        """
        if not 0 <= degrees <= 180:
            raise ValueError(f"servo angle must be 0..180, got {degrees}")
        if duration <= 0:
            self.angle(degrees)
            return
        start = 90.0 if self._angle is None else self._angle
        n = max(1, round(duration / _TICK))
        values = [self._to_value(start + (degrees - start) * (i + 1) / n)
                  for i in range(n)]
        dev = self._hw()
        dev.source_delay = _TICK
        dev.source = iter(values)
        self._angle = float(degrees)
        self._mark_busy(duration)

    def _release(self) -> None:
        if self._dev is not None:
            self._dev.close()
            self._dev = None

    def __repr__(self) -> str:
        return f"PiServo(pin={self.pin})"


class PiContinuousServo(PiServo, AbstractContinuousServo):
    """A continuous-rotation servo on a Pi GPIO pin, where the 'angle' is speed.

        wheel = PiContinuousServo(18)
        wheel.speed(100)     # full speed forward
        wheel.speed(-50)     # half speed reverse
        wheel.stop()

    speed is -100..100 (0 = stop). Same -100..100 -> 0..180 mapping the Arduino
    `ContinuousServo` uses; trim `stop()` if your servo creeps at 90.
    """

    def speed(self, percent: float) -> None:
        if not -100 <= percent <= 100:
            raise ValueError(f"speed must be -100..100, got {percent}")
        self.angle(round(90 + percent * 0.9))   # -100..100 -> 0..180 (90 = stop)

    def stop(self) -> None:
        self.angle(90)

    def __repr__(self) -> str:
        return f"PiContinuousServo(pin={self.pin})"
