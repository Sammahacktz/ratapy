"""GPIO input devices wired straight to the Raspberry Pi (gpiozero-backed).

The Pi twins of the Arduino input devices: `PiDigitalInput`, `PiButton`,
`PiLimitSwitch`, `PiMotionSensor`, `PiUltrasonic`, `PiRotaryEncoder`. Each is a
`LocalDevice` reading the Pi's own pins through gpiozero and implements the same
``Abstract*`` contract as its Arduino counterpart::

    rp = Raspberry()
    button = PiButton(4)             # GPIO4
    if button.was_pressed:
        ...

**Pins are BCM GPIO numbers** (gpiozero's default), NOT Arduino board pins.

`PiButton` re-implements the edge/long-press logic (`was_pressed`, `held_seconds`,
`pressed_for`, ...) in its own code -- the abstract contract guarantees the *methods*
match the Arduino `Button`; the implementations are kept separate on purpose.

Note the pull-resistor difference: on the Pi ``pull_up=False`` uses the chip's
INTERNAL pull-DOWN (the Pi has one; an AVR does not), so a plain button to 3.3 V
needs no external resistor. ``.value`` is always the raw pin level (True = HIGH).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ...protocol import RataError
from ..abstract_devices import (
    AbstractButton,
    AbstractDigitalInput,
    AbstractLimitSwitch,
    AbstractMotionSensor,
    AbstractRotaryEncoder,
    AbstractUltrasonic,
)
from .base import LocalDevice
from .pins import GPIOLike

if TYPE_CHECKING:
    from ...raspberry import Raspberry


class PiDigitalInput(LocalDevice, AbstractDigitalInput):
    """A digital input on a Pi GPIO pin (BCM numbering).

        pin = PiDigitalInput(4, pull_up=True)
        if pin.value:      # True when the pin reads HIGH
            ...

    ``pull_up=True`` enables the internal pull-up (rests HIGH); ``pull_up=False``
    enables the internal pull-DOWN (rests LOW) -- the Pi has both, so no external
    resistor is needed either way. ``.value`` is the raw electrical level.
    """

    def __init__(self, pin: GPIOLike, pull_up: bool = False,
                 board: "Raspberry | None" = None) -> None:
        self.pin: int = int(pin)
        self.pull_up: bool = pull_up
        self._dev: Any = None
        super().__init__(board)

    def _hw(self) -> Any:
        if self._dev is None:
            from gpiozero import DigitalInputDevice
            # gpiozero: pull_up=True -> internal pull-up; False -> internal pull-down.
            self._dev = DigitalInputDevice(self.pin, pull_up=self.pull_up)
        return self._dev

    @property
    def value(self) -> bool:
        """Read the pin now: True if HIGH, False if LOW (raw level)."""
        return bool(self._hw().pin.state)

    def read(self) -> bool:
        return self.value

    def _release(self) -> None:
        if self._dev is not None:
            self._dev.close()
            self._dev = None

    def __repr__(self) -> str:
        return f"PiDigitalInput(pin={self.pin})"


class PiButton(PiDigitalInput, AbstractButton):
    """A push button or switch on a Pi GPIO pin.

        button = PiButton(4)            # internal pull-up on by default
        if button.is_pressed: ...
        button.wait_for_press()

    Same behaviour as the Arduino `Button`: with the default ``pull_up=True`` wire
    the button between the pin and GND (released HIGH, pressed LOW -- `is_pressed`
    accounts for that). `was_pressed`/`was_released` are one-shot edges;
    `held_seconds`, `pressed_for` and `wait_pressed_for` cover long presses.
    ``normally_closed=True`` is for a switch that conducts at rest (see
    `PiLimitSwitch`).
    """

    def __init__(self, pin: GPIOLike, pull_up: bool = True,
                 normally_closed: bool = False,
                 board: "Raspberry | None" = None) -> None:
        self.normally_closed: bool = normally_closed
        self._pressed_since: float | None = None
        self._released_at: float | None = None
        self._reported_press: float | None = None
        self._reported_release: float | None = None
        super().__init__(pin, pull_up, board)

    @property
    def is_pressed(self) -> bool:
        # pull-up: pressed pulls the pin LOW; otherwise pressed drives it HIGH.
        down = (not self.value) if self.pull_up else self.value
        if self.normally_closed:
            down = not down
        now = time.monotonic()
        if down:
            if self._pressed_since is None or self._released_at is not None:
                self._pressed_since = now
                self._released_at = None
        elif self._pressed_since is not None and self._released_at is None:
            self._released_at = now
        return down

    def _hold(self) -> float | None:
        """Seconds this button has been down *now*, or None if it is up. One read."""
        if not self.is_pressed:
            return None
        since = self._pressed_since
        return 0.0 if since is None else time.monotonic() - since

    @property
    def held_seconds(self) -> float:
        """How long the button has been down -- or, once let go, how long that
        press lasted. 0.0 only until it has ever been pressed."""
        held = self._hold()
        if held is not None:
            return held
        since, until = self._pressed_since, self._released_at
        if since is None or until is None:
            return 0.0
        return until - since

    @property
    def is_released(self) -> bool:
        return not self.is_pressed

    @property
    def was_pressed(self) -> bool:
        """True **once** per press, then False until the next one."""
        self.is_pressed                     # one read; refreshes the edge state
        since = self._pressed_since
        if since is None or since == self._reported_press:
            return False
        self._reported_press = since
        return True

    @property
    def was_released(self) -> bool:
        """True **once** per release, then False until the next one."""
        self.is_pressed
        at = self._released_at
        if at is None or at == self._reported_release:
            return False
        self._reported_release = at
        return True

    def wait_for_press(self, timeout: float | None = None, poll: float = 0.02) -> None:
        """Block until the button is pressed (optional timeout in seconds)."""
        self._wait(lambda: self.is_pressed, timeout, poll, "press")

    def wait_for_release(self, timeout: float | None = None, poll: float = 0.02) -> None:
        """Block until the button is released (optional timeout in seconds)."""
        self._wait(lambda: self.is_released, timeout, poll, "release")

    def pressed_for(self, seconds: float) -> bool:
        """True if the button is down *right now* and has been for `seconds`.

        Instant/non-blocking, and it times from the first read that *saw* the
        button down -- so poll it in a loop (or use `wait_pressed_for`).
        """
        if seconds < 0:
            raise ValueError(f"pressed_for() takes a positive time, got {seconds}")
        held = self._hold()
        return held is not None and held >= seconds

    def wait_pressed_for(self, seconds: float, poll: float = 0.02) -> bool:
        """Watch the button for `seconds`: True if it is held that whole time."""
        if seconds < 0:
            raise ValueError(f"wait_pressed_for() takes a positive time, got {seconds}")
        deadline = time.monotonic() + seconds
        while True:
            if not self.is_pressed:
                return False
            now = time.monotonic()
            if now >= deadline:
                return True
            time.sleep(min(poll, deadline - now))

    def _wait(self, cond: Callable[[], bool], timeout: float | None,
              poll: float, what: str) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not cond():
            if deadline is not None and time.monotonic() > deadline:
                raise RataError(f"{self!r}: no {what} within {timeout}s")
            time.sleep(poll)

    def __repr__(self) -> str:
        nc = ", normally_closed=True" if self.normally_closed else ""
        return f"PiButton(pin={self.pin}{nc})"


class PiLimitSwitch(PiButton, AbstractLimitSwitch):
    """An end-stop / limit switch on a Pi GPIO pin -- a `PiButton` CLOSED at rest.

        stop = PiLimitSwitch(5)
        if stop.is_pressed:            # the axis has reached the end
            ...
    """

    def __init__(self, pin: GPIOLike, pull_up: bool = True,
                 normally_closed: bool = True,
                 board: "Raspberry | None" = None) -> None:
        super().__init__(pin, pull_up, normally_closed, board)

    def __repr__(self) -> str:
        return f"PiLimitSwitch(pin={self.pin})"


class PiMotionSensor(PiDigitalInput, AbstractMotionSensor):
    """A PIR motion sensor on a Pi GPIO pin.

        pir = PiMotionSensor(4)
        if pir.motion_detected: ...
        pir.wait_for_motion()

    A PIR drives its output HIGH when it sees motion, so no pull resistor is used.
    """

    def __init__(self, pin: GPIOLike, board: "Raspberry | None" = None) -> None:
        super().__init__(pin, pull_up=False, board=board)

    @property
    def motion_detected(self) -> bool:
        return self.value

    def wait_for_motion(self, timeout: float | None = None, poll: float = 0.05) -> None:
        """Block until motion is seen (optional timeout in seconds)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.motion_detected:
            if deadline is not None and time.monotonic() > deadline:
                raise RataError(f"{self!r}: no motion within {timeout}s")
            time.sleep(poll)

    def __repr__(self) -> str:
        return f"PiMotionSensor(pin={self.pin})"


class PiUltrasonic(LocalDevice, AbstractUltrasonic):
    """An HC-SR04 ultrasonic distance sensor on Pi GPIO pins (BCM numbering).

        sonar = PiUltrasonic(trigger=23, echo=24)
        sonar.distance_mm     # int millimetres, or None if out of range
        sonar.distance_cm     # float centimetres, or None

    Use a voltage divider on ECHO (the HC-SR04 drives 5 V; the Pi's pins are 3.3 V
    tolerant only). gpiozero clamps a no-echo reading to ``max_distance``; RATA
    reports that as None to match the Arduino `Ultrasonic`.
    """

    def __init__(self, trigger: GPIOLike, echo: GPIOLike, *, max_distance_m: float = 4.0,
                 board: "Raspberry | None" = None) -> None:
        self.trigger: int = int(trigger)
        self.echo: int = int(echo)
        self.max_distance_m: float = max_distance_m
        self._dev: Any = None
        super().__init__(board)

    def _hw(self) -> Any:
        if self._dev is None:
            from gpiozero import DistanceSensor
            self._dev = DistanceSensor(
                echo=self.echo, trigger=self.trigger, max_distance=self.max_distance_m)
        return self._dev

    @property
    def distance_mm(self) -> int | None:
        """Distance in millimetres, or None if out of range (no echo)."""
        d = float(self._hw().distance)           # metres, 0..max_distance
        if d >= self.max_distance_m - 1e-9:      # clamped -> nothing echoed back
            return None
        return int(round(d * 1000))

    @property
    def distance_cm(self) -> float | None:
        mm = self.distance_mm
        return None if mm is None else mm / 10

    def _release(self) -> None:
        if self._dev is not None:
            self._dev.close()
            self._dev = None

    def __repr__(self) -> str:
        return f"PiUltrasonic(trigger={self.trigger}, echo={self.echo})"


class PiRotaryEncoder(LocalDevice, AbstractRotaryEncoder):
    """An incremental (quadrature) rotary encoder on Pi GPIO pins.

        knob = PiRotaryEncoder(clk=5, dt=6)
        knob.position      # signed count since the last reset
        knob.detents       # position / steps_per_detent
        knob.reset()       # zero the count

    Note: gpiozero counts one step per detent, so ``steps_per_detent`` defaults to
    1 here -- unlike the Arduino `RotaryEncoder`, which sees ~4 raw quadrature
    counts per click.
    """

    def __init__(self, clk: GPIOLike, dt: GPIOLike, steps_per_detent: int = 1,
                 board: "Raspberry | None" = None) -> None:
        self.clk: int = int(clk)
        self.dt: int = int(dt)
        self.steps_per_detent: int = steps_per_detent
        self._zero: int = 0                          # reset() offset
        self._dev: Any = None
        super().__init__(board)

    def _hw(self) -> Any:
        if self._dev is None:
            from gpiozero import RotaryEncoder
            self._dev = RotaryEncoder(self.clk, self.dt, max_steps=0)
        return self._dev

    @property
    def position(self) -> int:
        """Signed count since the last reset."""
        return int(self._hw().steps) - self._zero

    @property
    def detents(self) -> int:
        """Whole clicks turned (position / steps_per_detent, toward zero)."""
        return int(self.position / self.steps_per_detent)

    def reset(self) -> None:
        """Set the position count back to zero."""
        self._zero = int(self._hw().steps)

    def _release(self) -> None:
        if self._dev is not None:
            self._dev.close()
            self._dev = None

    def __repr__(self) -> str:
        return f"PiRotaryEncoder(clk={self.clk}, dt={self.dt})"
