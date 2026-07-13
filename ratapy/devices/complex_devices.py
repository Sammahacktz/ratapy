"""Devices 

Every piece of hardware is an object. You create it, you call methods on it:

    led = LED(pin=2)
    led.on()
    led.blink(3)

A pin can be a number or the label on the board -- ``LED(pin=13)`` or
``LED(pin=AnalogPin.A0)``, the latter resolved against that board's pin map
(see ``Arduino.resolve_pin``).

Each device attaches itself to a board (an Arduino). Pass ``board=`` explicitly,
or leave it out to use the active board (the one most recently registered).
Adding new hardware means writing one more class here that sets ``DEVICE_TYPE``,
returns its config from ``_params()``, and exposes friendly methods
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from .. import protocol as p
from ..protocol import RataError
from ..boards import Arduino, PinLike
from ..executor import ParallelExecutor, active_executor
from ..raspberry import Raspberry
from ..scheduler import Scheduler


class Device(ABC):
    """Base class for everything you can plug into an Arduino."""

    DEVICE_TYPE: ClassVar[int]  # set by each subclass (see protocol.DEV_*)

    @staticmethod
    def _pick_board(board: Arduino | None) -> Arduino:
        """The board a device will attach to: the given one, or the active one.

        Subclasses call this *before* super().__init__() when they need the board
        to resolve a pin label ("A1" means a different number on each model).
        It is idempotent, so passing the result on to super() is free.
        """
        return board if board is not None else Raspberry.current().active_board

    def __init__(self, board: Arduino | None = None) -> None:
        # No board given: use the active board of the current Raspberry.
        self._board: Arduino = self._pick_board(board)
        self._executor: ParallelExecutor | None = None
        # This device's own place in time: the monotonic instant its next command
        # is due. 0.0 means "now" -- see sleep().
        self._cursor: float = 0.0
        self._validate() # fail fast with a clear error, before sending
        self._id: int = self._board._register(self, self.DEVICE_TYPE, self._params())

    def _validate(self) -> None:
        """Check this device is wireable on its board. Override for pwm/analog."""
        for pin in self._pins():
            self._board.check_pin(pin)

    def set_executor(self, executor: ParallelExecutor) -> None:
        """Route this device's commands into `executor` until remove_executor().

        Queued commands only run when executor.execute() is called together
        with everything else queued on it.
        """
        self._executor = executor

    def remove_executor(self) -> None:
        """Commands run immediately again."""
        self._executor = None

    @abstractmethod
    def _params(self) -> bytes:
        """Configuration bytes sent to the firmware at registration time."""

    def _pins(self) -> list[int]:
        """Pins this device uses, validated against the board before registering."""
        return []

    # Thin wrappers so subclasses read/write without touching ids or the board.
    # If an executor is bound (set_executor) or a `with ParallelExecutor():`
    # block is active, the write is queued for a simultaneous start instead of
    # sent immediately. A bound executor wins over an ambient `with` block.
    def _send(self, data: bytes) -> None:
        ex = self._executor or active_executor()
        if ex is not None:
            ex.add(self._board, self._id, data)
            return
        if self._cursor > time.monotonic():      # a sleep() put us in the future
            dev_id = self._id
            board = self._board
            self._scheduler().at(self._cursor, lambda: board._write(dev_id, data))
            return
        self._board._write(self._id, data)

    def _scheduler(self) -> Scheduler:
        rp = self._board._rp
        if rp is None:                     # board never registered -> no owner
            rp = Raspberry.current()
        return rp.scheduler

    def sleep(self, seconds: float) -> None:
        """Delay THIS device's next command by `seconds`, without blocking.

        ``time.sleep`` stops your whole script, so every other device waits with
        it. This only moves *this* device's clock forward: the call returns at
        once, and each device keeps its own timing::

            led.on(); led2.on()
            led.sleep(3);  led.off()     # led  goes off at t+3
            led2.sleep(1); led2.off()    # led2 goes off at t+1, not t+4

        The delay applies to commands, not reads -- a value has to be fetched
        when you ask for it, so ``sensor.value`` is always read now.

        Because the commands after it run later, your script has to still be
        around when they do: leave a ``with Raspberry()`` block (it waits), or
        call ``rp.wait()``.
        """
        if seconds < 0:
            raise ValueError(f"sleep() takes a positive delay, got {seconds}")
        if self._executor is not None or active_executor() is not None:
            raise RataError(
                f"{self!r}: sleep() cannot be used inside a ParallelExecutor -- "
                "an executor exists to start commands together, at one instant. "
                "Sleep before or after the block instead."
            )
        # From the later of "now" and where this device already is, so successive
        # sleeps add up instead of collapsing onto the same instant.
        self._cursor = max(self._cursor, time.monotonic()) + seconds

    def _read_raw(self) -> bytes:
        """All value bytes the device returned (for multi-value sensors)."""
        return self._board._read(self._id)

    def _recv(self) -> int:
        """The device's value as one signed 16-bit int (single-value sensors)."""
        data = self._read_raw()
        if len(data) < 2:
            raise RataError("short value response")
        return p.i16(data)

    def is_busy(self) -> bool:
        """True while a background action is still running on the board.

        Instantaneous devices (an LED's ``on()``/``off()`` take effect at once)
        are never busy, so the default is ``False``. Long-running actuators like
        a stepper override this to report their progress.
        """
        return False

    def wait(self, timeout: float | None = None, poll: float = 0.02) -> None:
        """Block until this device's current action finishes.

        Every device has this, so the same loop shape works for all of them::

            stepper.step(400); stepper.wait()   # blocks until the move ends
            led.blink(3);      led.wait()        # returns at once -- nothing to await

        For a device whose commands complete instantly it returns immediately
        (there is nothing in progress). For a background action it polls
        :meth:`is_busy` until the board reports idle, or raises on ``timeout``
        (seconds; ``None`` waits forever).
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.is_busy():
            if deadline is not None and time.monotonic() > deadline:
                raise RataError(f"{self!r} still busy after {timeout}s")
            time.sleep(poll)


class DigitalOutput(Device):
    """A simple on/off digital output on any digital pin.

        out = DigitalOutput(pin=2)
        out.on()
        out.off()
        out.toggle()
        out.blink(3)              # blink 3 times
        out.blink(3, on=0.1)      # faster

    This is the generic primitive; for readable code use the friendly components
    built on it -- `LED`, `Relay`, `Buzzer` (also in ratapy.devices).
    """

    DEVICE_TYPE: ClassVar[int] = p.DEV_DIGITAL_OUT

    def __init__(self, pin: PinLike, board: Arduino | None = None) -> None:
        board = self._pick_board(board)
        self.pin: int = board.resolve_pin(pin)
        self._on: bool = False
        super().__init__(board)

    def _params(self) -> bytes:
        return bytes([self.pin])

    def _pins(self) -> list[int]:
        return [self.pin]

    @property
    def is_on(self) -> bool:
        return self._on

    def on(self) -> None:
        self._send(b"\x01") # also cancels any running blink
        self._on = True

    def off(self) -> None:
        self._send(b"\x00") # also cancels any running blink
        self._on = False

    def toggle(self) -> None:
        self.off() if self._on else self.on()

    def is_busy(self) -> bool:
        """True while a blink pattern is still running on the board."""
        return self._recv() != 0

    def blink(self, times: int = 1, on: float = 0.5, off: float = 0.5) -> None:
        """Blink `times` times (0 = forever), `on`/`off` seconds per phase.

        Non-blocking: hands the whole pattern to the board, which toggles the pin
        itself in the background, and returns immediately. So several devices
        blink at once, and it works inside a ``with ParallelExecutor():`` block
        (both blinks start together). Call :meth:`wait` to block until it ends::

            led.blink(3); led.wait()      # blink 3x, then continue
            led.blink(0)                  # blink forever (until on()/off())

        `on`/`off` are seconds (0..65.535). Ends with the pin off.
        """
        if not 0 <= times <= 0xFFFF:
            raise ValueError(f"times must be 0..65535 (0 = forever), got {times}")
        on_ms, off_ms = round(on * 1000), round(off * 1000)
        if not (0 <= on_ms <= 0xFFFF and 0 <= off_ms <= 0xFFFF):
            raise ValueError("on/off must be 0..65.535 seconds")
        self._send(b"\x02" + times.to_bytes(2, "big")
                   + on_ms.to_bytes(2, "big") + off_ms.to_bytes(2, "big"))
        self._on = False # the pattern finishes with the pin off


class StepperWithDriver(Device):
    """A 4-wire stepper motor on a driver board (e.g. 28BYJ-48 + ULN2003).

        stepper = StepperWithDriver(pins=[8, 10, 9, 11])
        stepper.step(200, speed=100)    # non-blocking: returns immediately
        stepper.wait()                  # block until the move finishes

    ``step()`` only hands the goal to the firmware; the motor runs in the
    background there (AccelStepper), so several steppers move at once and other
    devices stay usable while it turns. Start moves simultaneously with
    ParallelExecutor.

    For a 28BYJ-48 on a ULN2003 board, pass the pins in IN1, IN3, IN2, IN4
    order (AccelStepper's expected coil sequence).
    """

    DEVICE_TYPE: ClassVar[int] = p.DEV_STEPPER

    def __init__(self, pins: Sequence[PinLike], board: Arduino | None = None) -> None:
        if len(pins) != 4:
            raise ValueError(f"a 4-wire stepper needs exactly 4 pins, got {len(pins)}")
        board = self._pick_board(board)
        self.pins: tuple[int, ...] = tuple(board.resolve_pin(x) for x in pins)
        super().__init__(board)

    def _params(self) -> bytes:
        return bytes(self.pins)

    def _pins(self) -> list[int]:
        return list(self.pins)

    def step(self, steps: int, speed: int = 200) -> None:
        """Move `steps` steps (negative = reverse) at `speed` steps/second.

        Non-blocking: returns as soon as the board has accepted the goal.
        Use `wait()` / `is_moving` to track completion. Queued instead of run
        when an executor is bound (set_executor) or a `with ParallelExecutor():`
        block is active.
        """
        if not -32768 <= steps <= 32767:
            raise ValueError(f"steps must fit a signed 16-bit int, got {steps}")
        if not 1 <= speed <= 65535:
            raise ValueError(f"speed must be 1..65535 steps/s, got {speed}")
        self._send(steps.to_bytes(2, "big", signed=True) + speed.to_bytes(2, "big"))

    def run(self, speed: int) -> None:
        """Spin continuously at `speed` steps/s (negative = reverse) until `stop()`.

        Non-blocking -- for wheels, conveyors, anything that turns indefinitely.
        The motor keeps going with no target, so don't `wait()` on it (it never
        ends); call `stop()` to halt.
        """
        if not -32767 <= speed <= 32767 or speed == 0:
            raise ValueError(f"speed must be a non-zero signed 16-bit int, got {speed}")
        self._send(b"\x01" + speed.to_bytes(2, "big", signed=True))

    def stop(self) -> None:
        """Stop the motor now -- halts a `step()` move or a `run()` and releases the coils."""
        self._send(b"\x00")

    @property
    def is_moving(self) -> bool:
        """True while a move or continuous run is in progress on the board."""
        return self._recv() != 0

    def is_busy(self) -> bool:
        """Busy while the motor is still moving (drives the shared `wait()`)."""
        return self.is_moving

    def __repr__(self) -> str:
        return f"StepperWithDriver(pins={list(self.pins)})"


class PWM(Device):
    """A PWM output -- LED brightness, DC-motor speed, buzzer volume.

        led = PWM(pin=9)
        led.set(128)          # 0..255 duty
        led.fraction(0.25)    # 0.0..1.0
        led.off()

    Must be on a PWM-capable pin (checked against the board).
    """

    DEVICE_TYPE: ClassVar[int] = p.DEV_PWM

    def __init__(self, pin: PinLike, board: Arduino | None = None) -> None:
        board = self._pick_board(board)
        self.pin: int = board.resolve_pin(pin)
        super().__init__(board)

    def _params(self) -> bytes:
        return bytes([self.pin])

    def _validate(self) -> None:
        self._board.check_pin(self.pin, pwm=True)

    def set(self, value: int) -> None:
        """Set the duty cycle, 0 (off) .. 255 (full)."""
        if not 0 <= value <= 255:
            raise ValueError(f"PWM value must be 0..255, got {value}")
        self._send(bytes([value]))

    def fraction(self, f: float) -> None:
        """Set the duty as a fraction, 0.0 .. 1.0."""
        if not 0.0 <= f <= 1.0:
            raise ValueError(f"fraction must be 0.0..1.0, got {f}")
        self.set(round(f * 255))

    def off(self) -> None:
        self.set(0)

    def is_busy(self) -> bool:
        """True while a fade / pulse / blink is still running on the board."""
        return self._recv() != 0

    def fade(self, value: int, duration: float = 1.0) -> None:
        """Ramp the duty smoothly to `value` (0..255) over `duration` seconds.

        Non-blocking: the board runs the ramp in the background. `wait()` blocks
        until it lands; works inside a ParallelExecutor block.
        """
        if not 0 <= value <= 255:
            raise ValueError(f"PWM value must be 0..255, got {value}")
        dur_ms = round(duration * 1000)
        if not 0 <= dur_ms <= 0xFFFF:
            raise ValueError("duration must be 0..65.535 seconds")
        self._send(b"\x01" + bytes([value]) + dur_ms.to_bytes(2, "big"))

    def pulse(self, cycles: int = 1, period: float = 2.0, peak: int = 255) -> None:
        """Breathe up and down `cycles` times (0 = forever), `period` s per cycle.

        Non-blocking (the board runs it). Ends at 0. `peak` is the top duty
        (0..255). Use `wait()` to block until it finishes.
        """
        if not 0 <= cycles <= 0xFFFF:
            raise ValueError(f"cycles must be 0..65535 (0 = forever), got {cycles}")
        if not 0 <= peak <= 255:
            raise ValueError(f"peak must be 0..255, got {peak}")
        per_ms = round(period * 1000)
        if not 0 <= per_ms <= 0xFFFF:
            raise ValueError("period must be 0..65.535 seconds")
        self._send(b"\x02" + cycles.to_bytes(2, "big") + bytes([peak])
                   + per_ms.to_bytes(2, "big"))

    def blink(self, times: int = 1, on: float = 0.5, off: float = 0.5,
              peak: int = 255) -> None:
        """Blink `times` times (0 = forever) between `peak` duty and off.

        Non-blocking, like the digital blink -- the board runs the pattern.
        """
        if not 0 <= times <= 0xFFFF:
            raise ValueError(f"times must be 0..65535 (0 = forever), got {times}")
        if not 0 <= peak <= 255:
            raise ValueError(f"peak must be 0..255, got {peak}")
        on_ms, off_ms = round(on * 1000), round(off * 1000)
        if not (0 <= on_ms <= 0xFFFF and 0 <= off_ms <= 0xFFFF):
            raise ValueError("on/off must be 0..65.535 seconds")
        self._send(b"\x03" + times.to_bytes(2, "big") + bytes([peak])
                   + on_ms.to_bytes(2, "big") + off_ms.to_bytes(2, "big"))


class Servo(Device):
    """A hobby servo motor.

        servo = Servo(pin=9)
        servo.angle(90)              # snap to 90 degrees
        servo.move(0, duration=1.5)  # sweep smoothly to 0 over 1.5 s; servo.wait()

    Non-blocking; the board holds the position. Works on any digital pin.
    """

    DEVICE_TYPE: ClassVar[int] = p.DEV_SERVO

    def __init__(self, pin: PinLike, board: Arduino | None = None) -> None:
        board = self._pick_board(board)
        self.pin: int = board.resolve_pin(pin)
        super().__init__(board)

    def _params(self) -> bytes:
        return bytes([self.pin])

    def _pins(self) -> list[int]:
        return [self.pin]

    def angle(self, degrees: int) -> None:
        """Snap to `degrees` (0..180) immediately."""
        if not 0 <= degrees <= 180:
            raise ValueError(f"servo angle must be 0..180, got {degrees}")
        self._send(bytes([degrees]))

    def move(self, degrees: int, duration: float = 0.0) -> None:
        """Move to `degrees` (0..180), sweeping smoothly over `duration` seconds.

        `duration=0` is an instant move (same as `angle`). Otherwise the board
        eases there in the background (non-blocking) -- so servos move at once
        and it composes with a ParallelExecutor. Use `wait()` to block until it
        arrives.
        """
        if not 0 <= degrees <= 180:
            raise ValueError(f"servo angle must be 0..180, got {degrees}")
        if duration <= 0:
            self.angle(degrees)
            return
        dur_ms = round(duration * 1000)
        if not 0 <= dur_ms <= 0xFFFF:
            raise ValueError("duration must be 0..65.535 seconds")
        self._send(b"\x01" + bytes([degrees]) + dur_ms.to_bytes(2, "big"))

    def is_busy(self) -> bool:
        """True while a timed sweep is still in progress on the board."""
        return self._recv() != 0


class DigitalInput(Device):
    """A digital input -- button, switch, PIR motion, limit switch.

        button = DigitalInput(pin=4, pull_up=True)
        if button.value:      # True when the pin reads HIGH
            ...

    A floating pin reads noise, so it needs a resistor to sit at a known level:

    - pull-UP  (`pull_up=True`):  wire to GND, rests HIGH, pressed = LOW. Uses
      the chip's INTERNAL resistor -- nothing to add. This is the common case.
    - pull-DOWN (`pull_up=False`): wire to VCC, rests LOW, pressed = HIGH. AVR
      has NO internal pull-down, so add an EXTERNAL ~10k pin->GND resistor
      yourself; this just leaves the pin a plain floating INPUT.

    (`Button` wraps the pull-up case and flips the logic so `is_pressed` reads
    right; for pull-down wiring use DigitalInput and read `.value` directly.)
    """

    DEVICE_TYPE: ClassVar[int] = p.DEV_DIGITAL_IN

    def __init__(self, pin: PinLike, pull_up: bool = False,
                 board: Arduino | None = None) -> None:
        board = self._pick_board(board)
        self.pin: int = board.resolve_pin(pin)
        self.pull_up: bool = pull_up
        super().__init__(board)

    def _params(self) -> bytes:
        return bytes([self.pin, 1 if self.pull_up else 0])

    def _pins(self) -> list[int]:
        return [self.pin]

    @property
    def value(self) -> bool:
        """Read the pin now: True if HIGH, False if LOW."""
        return self._recv() != 0

    def read(self) -> bool:
        return self.value


class AnalogInput(Device):
    """An analog input -- potentiometer, LDR, and most analog sensors.

        pot = AnalogInput(channel=0)             # A0
        pot = AnalogInput(channel=AnalogPin.A0)  # the same, said out loud
        pot.value                          # raw 0..1023
        pot.voltage()                      # volts (default vref 5.0)
        pot.fraction                       # 0.0..1.0

    `channel` is the analog channel number: 0 for A0, 1 for A1, ... -- or the
    label (AnalogPin.A1), which means the same channel on every board.
    Note this is a *channel*, not a pin number: A0 is channel 0 everywhere, while
    its pin number differs per model. Convert to real units (temperature, lux,
    ...) on this side -- the board returns the raw ADC reading.
    """

    DEVICE_TYPE: ClassVar[int] = p.DEV_ANALOG_IN

    def __init__(self, channel: PinLike, board: Arduino | None = None) -> None:
        board = self._pick_board(board)
        # A label works here too (AnalogPin.A1 == channel 1), which is
        # how most people think of an analog input.
        self.channel: int = board.resolve_channel(channel)
        super().__init__(board)

    def _params(self) -> bytes:
        return bytes([self.channel])

    def _validate(self) -> None:
        n = self._board.NUM_ANALOG_INPUTS
        if n and not (0 <= self.channel < n):
            raise ValueError(
                f"{self._board.MODEL} has analog channels 0..{n - 1} "
                f"(A0..A{n - 1}), got A{self.channel}"
            )

    @property
    def value(self) -> int:
        """Read the raw ADC value now, 0..1023."""
        return self._recv()

    def read(self) -> int:
        return self.value

    @property
    def fraction(self) -> float:
        """The reading as 0.0..1.0."""
        return self._recv() / 1023

    def voltage(self, vref: float = 5.0) -> float:
        """The reading in volts, given the board's reference voltage."""
        return self._recv() / 1023 * vref


class RotaryEncoder(Device):
    """An incremental rotary encoder (quadrature, e.g. a KY-040).

        knob = RotaryEncoder(clk=2, dt=3)
        knob.position      # signed count since the last reset (turn = +/-)
        knob.detents       # position / steps_per_detent (whole clicks)
        knob.reset()       # zero the count

    The board decodes the pulses (they arrive too fast to poll from here), so you
    just read the accumulated position. Most encoders emit ~4 counts per physical
    click -- adjust `steps_per_detent` if yours differs. A KY-040's push button is
    a separate `Button` on its SW pin.
    """

    DEVICE_TYPE: ClassVar[int] = p.DEV_ENCODER

    def __init__(self, clk: PinLike, dt: PinLike, steps_per_detent: int = 4,
                 board: Arduino | None = None) -> None:
        board = self._pick_board(board)
        self.clk: int = board.resolve_pin(clk)
        self.dt: int = board.resolve_pin(dt)
        self.steps_per_detent: int = steps_per_detent
        super().__init__(board)

    def _params(self) -> bytes:
        return bytes([self.clk, self.dt])

    def _pins(self) -> list[int]:
        return [self.clk, self.dt]

    @property
    def position(self) -> int:
        """Raw signed quadrature count since the last reset."""
        return self._recv()

    @property
    def detents(self) -> int:
        """Whole clicks turned (position / steps_per_detent, toward zero)."""
        return int(self._recv() / self.steps_per_detent)

    def reset(self) -> None:
        """Set the position count back to zero."""
        self._send(b"\x00")


class Ultrasonic(Device):
    """An HC-SR04 ultrasonic distance sensor.

        sonar = Ultrasonic(trigger=7, echo=8)
        sonar.distance_mm     # int millimetres, or None if nothing echoed back
        sonar.distance_cm     # float centimetres, or None

    Reading blocks briefly on the board (up to ~25 ms) while it waits for the
    echo, so avoid hammering it inside a tight motion loop.
    """

    DEVICE_TYPE: ClassVar[int] = p.DEV_ULTRASONIC

    def __init__(self, trigger: PinLike, echo: PinLike,
                 board: Arduino | None = None) -> None:
        board = self._pick_board(board)
        self.trigger: int = board.resolve_pin(trigger)
        self.echo: int = board.resolve_pin(echo)
        super().__init__(board)

    def _params(self) -> bytes:
        return bytes([self.trigger, self.echo])

    def _pins(self) -> list[int]:
        return [self.trigger, self.echo]

    @property
    def distance_mm(self) -> int | None:
        """Distance in millimetres, or None if out of range (no echo)."""
        v = self._recv()
        return None if v < 0 else v

    @property
    def distance_cm(self) -> float | None:
        mm = self.distance_mm
        return None if mm is None else mm / 10


@dataclass
class DHTReading:
    """One temperature + humidity sample from a DHT sensor."""
    temperature: float   # degrees Celsius
    humidity: float      # percent relative humidity


class DHT(Device):
    """A DHT11 / DHT22 (AM2302) temperature + humidity sensor.

        dht = DHT(pin=4, kind=22)     # kind is 11 or 22
        r = dht.read()                # one round-trip for BOTH values
        r.temperature, r.humidity

    A DHT is slow: leave ~2 s between reads (a DHT22) or the sensor returns an
    error. Both values come back in a single read (this is the multi-value
    sensor the variable-length VALUE response was built for).
    """

    DEVICE_TYPE: ClassVar[int] = p.DEV_DHT
    _ERR = -32768        # INT16_MIN sentinel the firmware sends on a failed read

    def __init__(self, pin: PinLike, kind: int = 22,
                 board: Arduino | None = None) -> None:
        if kind not in (11, 22):
            raise ValueError(f"DHT kind must be 11 or 22, got {kind}")
        board = self._pick_board(board)
        self.pin: int = board.resolve_pin(pin)
        self.kind: int = kind
        super().__init__(board)

    def _params(self) -> bytes:
        return bytes([self.pin, self.kind])

    def _pins(self) -> list[int]:
        return [self.pin]

    def read(self) -> DHTReading:
        """Read temperature (degC) and humidity (%) in one shot."""
        data = self._read_raw()
        if len(data) < 4:
            raise RataError("short DHT response")
        t = p.i16(data, 0)
        h = p.i16(data, 2)
        if t == self._ERR or h == self._ERR:
            raise RataError(f"{self!r}: DHT read failed (check wiring / wait between reads)")
        return DHTReading(temperature=t / 10, humidity=h / 10)

    def __repr__(self) -> str:
        return f"DHT(pin={self.pin}, kind={self.kind})"
