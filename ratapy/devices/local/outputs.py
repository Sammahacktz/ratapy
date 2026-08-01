"""GPIO output devices wired straight to the Raspberry Pi (gpiozero-backed).

The Pi twins of the Arduino output devices -- digital (`PiLED`, `PiRelay`,
`PiBuzzer`, `PiSolenoid`) and PWM (`PiPWM`, `PiDimmableLED`, `PiDCMotor`,
`PiMosfet`, `PiRGBLED`). Each is a `LocalDevice` driving the Pi's own pins through
gpiozero, and each implements the same ``Abstract*`` contract as its Arduino
counterpart -- separate code, guaranteed-identical method surface::

    rp = Raspberry()
    led = PiLED(17)          # GPIO17 on the Pi itself
    led.on(); led.blink(3)

**Pins are BCM GPIO numbers** (gpiozero's default), NOT Arduino board pins:
``PiLED(17)`` is GPIO17 (header pin 11). See the Arduino ``LED`` for the wire-
protocol version.

Blink / fade / pulse are **non-blocking**, exactly like the Arduino versions -- but
where the Arduino's firmware runs them in the background, here **gpiozero** does
(its own blink/pulse threads, and its ``source`` thread for fades). RATA spawns no
threads of its own for this; it just tracks *when* the action finishes so
``is_busy()`` / ``wait()`` behave like an Arduino `Device` (so these devices drop
straight into a ``with BackgroundTasks():`` block).

The PWM devices use gpiozero's **software** PWM, which jitters under CPU load --
fine for an LED, marginal for anything timing-critical. For smoothness put them on
a hardware-PWM pin (GPIO12/13/18/19) and install ``pigpio``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from ..abstract_devices import (
    AbstractBuzzer,
    AbstractDCMotor,
    AbstractDigitalOutput,
    AbstractDimmableLED,
    AbstractLED,
    AbstractMosfet,
    AbstractPWM,
    AbstractRelay,
    AbstractRGBLED,
    AbstractSolenoid,
)
from .base import LocalDevice
from .pins import GPIOLike

if TYPE_CHECKING:
    from ...raspberry import Raspberry

# gpiozero's ``source`` thread reads one value every ``source_delay`` seconds; ~50 Hz
# is smooth enough for a fade and coarse enough not to thrash the CPU.
_TICK = 0.02


def _samples(seconds: float) -> int:
    """How many ``_TICK`` samples span `seconds` (at least one)."""
    return max(1, round(seconds / _TICK))


def _linspace(start: float, end: float, n: int) -> list[float]:
    """`n` values from just-after-`start` to exactly `end`."""
    return [start + (end - start) * (i + 1) / n for i in range(n)]


# --- digital outputs ------------------------------------------------------

class PiDigitalOutput(LocalDevice, AbstractDigitalOutput):
    """A simple on/off digital output on a Pi GPIO pin (BCM numbering).

        out = PiDigitalOutput(17)
        out.on(); out.off(); out.toggle(); out.blink(3)

    The generic primitive; for readable code use `PiLED` / `PiRelay` / `PiBuzzer`.
    ``active_high=False`` inverts the pin (a LOW drives it "on") -- see `PiRelay`.
    """

    def __init__(self, pin: GPIOLike, *, active_high: bool = True,
                 board: "Raspberry | None" = None) -> None:
        self.pin: int = int(pin)
        self._active_high: bool = active_high
        self._on: bool = False
        self._dev: Any = None                       # gpiozero DigitalOutputDevice
        super().__init__(board)

    def _hw(self) -> Any:
        if self._dev is None:
            from gpiozero import DigitalOutputDevice
            self._dev = DigitalOutputDevice(
                self.pin, active_high=self._active_high, initial_value=self._on)
        return self._dev

    @property
    def is_on(self) -> bool:
        return self._on

    def on(self) -> None:
        self._clear_busy()
        self._hw().on()                             # gpiozero stops any running blink
        self._on = True

    def off(self) -> None:
        self._clear_busy()
        self._hw().off()
        self._on = False

    def toggle(self) -> None:
        self.off() if self._on else self.on()

    def blink(self, times: int = 1, on: float = 0.5, off: float = 0.5) -> None:
        """Blink `times` times (0 = forever), `on`/`off` seconds per phase.

        Non-blocking -- gpiozero toggles the pin on its own background thread. Ends
        with the pin off.
        """
        if not 0 <= times <= 0xFFFF:
            raise ValueError(f"times must be 0..65535 (0 = forever), got {times}")
        self._on = False
        n = None if times == 0 else times
        self._hw().blink(on_time=on, off_time=off, n=n, background=True)
        self._mark_busy(None if times == 0 else times * (on + off))

    def _release(self) -> None:
        if self._dev is not None:
            self._dev.close()                       # stops any blink thread too
            self._dev = None

    def __repr__(self) -> str:
        return f"PiDigitalOutput(pin={self.pin})"


class PiLED(PiDigitalOutput, AbstractLED):
    """An LED on a Pi GPIO pin -- the friendly name for a plain on/off output.

        led = PiLED(17)
        led.on(); led.off(); led.toggle(); led.blink(3)
    """

    def __repr__(self) -> str:
        return f"PiLED(pin={self.pin})"


class PiRelay(PiDigitalOutput, AbstractRelay):
    """A relay on a Pi GPIO pin.

        relay = PiRelay(17)
        relay.on(); relay.off(); relay.toggle()

    Many relay boards are ACTIVE-LOW; pass ``active_low=True`` so ``on()`` always
    means "energised". Unlike the Arduino `Relay`, ``blink()`` works fine on an
    active-low module here -- gpiozero runs the blink in Python and honours the
    inversion on every phase (the Arduino refuses it, because the firmware toggling
    the pin can't know about the inversion).
    """

    def __init__(self, pin: GPIOLike, active_low: bool = False,
                 board: "Raspberry | None" = None) -> None:
        self.active_low: bool = active_low
        super().__init__(pin, active_high=not active_low, board=board)

    def __repr__(self) -> str:
        return f"PiRelay(pin={self.pin})"


class PiBuzzer(PiDigitalOutput, AbstractBuzzer):
    """An active buzzer on a Pi GPIO pin (beeps on its own when powered).

        buzzer = PiBuzzer(17)
        buzzer.beep()                # one short beep
        buzzer.beep(0.05, times=3)   # three quick beeps
    """

    def beep(self, duration: float = 0.1, times: int = 1, gap: float = 0.1) -> None:
        """Beep `times` times, `duration` s each, `gap` s between. Non-blocking."""
        self.blink(times, on=duration, off=gap)

    def __repr__(self) -> str:
        return f"PiBuzzer(pin={self.pin})"


class PiSolenoid(PiDigitalOutput, AbstractSolenoid):
    """A solenoid / electromagnetic actuator on a Pi GPIO pin.

        lock = PiSolenoid(17)
        lock.energize(); lock.deenergize()
        lock.pulse(0.2)              # fire 0.2 s, then release -- non-blocking

    Wiring is identical to the Arduino `Solenoid`: drive it through a MOSFET or
    relay (never off a pin), with a flyback diode across the coil, and prefer
    ``pulse()`` for intermittent-duty coils.

    IMPORTANT difference from the Arduino version: here the release is timed by
    gpiozero's background thread, **not** the board's firmware. If your process is
    killed mid-pulse the coil stays energized -- the Arduino `Solenoid.pulse()` is
    crash-safe (the board finishes the pulse), this one is not.
    """

    def energize(self) -> None:
        self.on()

    def deenergize(self) -> None:
        self.off()

    @property
    def is_energized(self) -> bool:
        return self._on

    def pulse(self, seconds: float = 0.1) -> None:
        """Energize for `seconds`, then release (gpiozero thread). Non-blocking."""
        if seconds <= 0:
            raise ValueError(f"pulse seconds must be positive, got {seconds}")
        self._on = False
        self._hw().blink(on_time=seconds, off_time=0, n=1, background=True)
        self._mark_busy(seconds)

    def __repr__(self) -> str:
        return f"PiSolenoid(pin={self.pin})"


# --- PWM outputs ----------------------------------------------------------

class PiPWM(LocalDevice, AbstractPWM):
    """A PWM output on a Pi GPIO pin (BCM numbering).

        led = PiPWM(18)
        led.set(128)          # 0..255 duty
        led.fraction(0.25)    # 0.0..1.0
        led.off()

    Software PWM by default (jitters under load); a hardware-PWM pin
    (GPIO12/13/18/19) + pigpio is smoother. Fade/pulse/blink run on gpiozero's own
    background thread -- see the module docstring.
    """

    def __init__(self, pin: GPIOLike, *, board: "Raspberry | None" = None) -> None:
        self.pin: int = int(pin)
        self._value: float = 0.0                    # last-set fraction, 0..1
        self._dev: Any = None                       # gpiozero PWMOutputDevice
        super().__init__(board)

    def _hw(self) -> Any:
        if self._dev is None:
            from gpiozero import PWMOutputDevice
            self._dev = PWMOutputDevice(self.pin, initial_value=self._value)
        return self._dev

    def _drive(self, f: float) -> None:
        """Set the duty now, cancelling any running effect (source or blink)."""
        dev = self._hw()
        dev.source = None                           # stop a running fade/pulse source
        dev.value = f
        self._value = f
        self._clear_busy()

    def _run(self, values: Iterator[float] | list[float], duration: float | None) -> None:
        """Hand a value stream to gpiozero's background source thread."""
        dev = self._hw()
        dev.source_delay = _TICK
        dev.source = iter(values)
        self._mark_busy(duration)

    def set(self, value: int) -> None:
        """Set the duty cycle, 0 (off) .. 255 (full)."""
        if not 0 <= value <= 255:
            raise ValueError(f"PWM value must be 0..255, got {value}")
        self._drive(value / 255)

    def fraction(self, f: float) -> None:
        """Set the duty as a fraction, 0.0 .. 1.0."""
        if not 0.0 <= f <= 1.0:
            raise ValueError(f"fraction must be 0.0..1.0, got {f}")
        self._drive(f)

    def off(self) -> None:
        self._drive(0.0)

    def fade(self, value: int, duration: float = 1.0) -> None:
        """Ramp the duty smoothly to `value` (0..255) over `duration` s. Non-blocking."""
        if not 0 <= value <= 255:
            raise ValueError(f"PWM value must be 0..255, got {value}")
        target = value / 255
        n = _samples(duration)
        self._run(_linspace(self._value, target, n), duration)
        self._value = target                        # where it ends up

    def pulse(self, cycles: int = 1, period: float = 2.0, peak: int = 255) -> None:
        """Breathe up and down `cycles` times (0 = forever), `period` s per cycle."""
        if not 0 <= cycles <= 0xFFFF:
            raise ValueError(f"cycles must be 0..65535 (0 = forever), got {cycles}")
        if not 0 <= peak <= 255:
            raise ValueError(f"peak must be 0..255, got {peak}")
        pk = peak / 255
        half = _samples(period / 2)
        one = _linspace(0.0, pk, half) + _linspace(pk, 0.0, half)
        self._run(_repeat(one, cycles), None if cycles == 0 else cycles * period)
        self._value = 0.0

    def blink(self, times: int = 1, on: float = 0.5, off: float = 0.5,
              peak: int = 255) -> None:
        """Blink `times` times (0 = forever) between `peak` duty and off."""
        if not 0 <= times <= 0xFFFF:
            raise ValueError(f"times must be 0..65535 (0 = forever), got {times}")
        if not 0 <= peak <= 255:
            raise ValueError(f"peak must be 0..255, got {peak}")
        pk = peak / 255
        one = [pk] * _samples(on) + [0.0] * _samples(off)
        self._run(_repeat(one, times), None if times == 0 else times * (on + off))
        self._value = 0.0

    def _release(self) -> None:
        if self._dev is not None:
            self._dev.close()
            self._dev = None

    def __repr__(self) -> str:
        return f"PiPWM(pin={self.pin})"


def _repeat(one_cycle: list[float], times: int) -> Iterator[float]:
    """`one_cycle` repeated `times` times, or forever when ``times == 0``."""
    if times == 0:
        while True:
            yield from one_cycle
    else:
        for _ in range(times):
            yield from one_cycle


class _PiPercentPWM(PiPWM):
    """Pi-side percent duty shared by `PiDimmableLED`/`PiDCMotor`/`PiMosfet`.

    The Pi analogue of the Arduino `_PercentPWM` -- deliberately separate code (the
    two transports share the abstract contract, not the implementation). Not public.
    """

    def __init__(self, pin: GPIOLike, *, board: "Raspberry | None" = None) -> None:
        super().__init__(pin, board=board)
        self._percent: float = 0.0

    @property
    def percent(self) -> float:
        """The duty this was last set to, 0..100 (what you asked for)."""
        return self._percent

    def _set_percent(self, percent: float, what: str) -> None:
        if not 0 <= percent <= 100:
            raise ValueError(f"{what} must be 0..100, got {percent}")
        self.fraction(percent / 100)
        self._percent = percent

    def _fade_percent(self, percent: float, duration: float, what: str) -> None:
        if not 0 <= percent <= 100:
            raise ValueError(f"{what} must be 0..100, got {percent}")
        self.fade(round(percent / 100 * 255), duration)
        self._percent = percent

    def off(self) -> None:
        super().off()
        self._percent = 0.0


class PiDimmableLED(_PiPercentPWM, AbstractDimmableLED):
    """An LED on a Pi PWM pin -- like `PiLED`, but with brightness and fades.

        led = PiDimmableLED(18)
        led.on()               # full brightness
        led.brightness(30)     # 30 %
        led.fade_to(0, 1.5)    # fade to off over 1.5 s
        led.pulse(2)           # "breathe" twice
    """

    @property
    def is_on(self) -> bool:
        return self._percent > 0

    def brightness(self, percent: float) -> None:
        """Set brightness to `percent` (0..100)."""
        self._set_percent(percent, "brightness")

    def on(self) -> None:
        self.brightness(100)

    def toggle(self) -> None:
        self.off() if self.is_on else self.on()

    def fade_to(self, percent: float, duration: float = 1.0) -> None:
        """Smoothly change brightness to `percent` over `duration` s. Non-blocking."""
        self._fade_percent(percent, duration, "brightness")

    def pulse(self, cycles: int = 1, period: float = 2.0, peak: int = 255) -> None:
        """Smoothly 'breathe' up and down `cycles` times (0 = forever). Non-blocking."""
        super().pulse(cycles, period, peak)
        self._percent = 0.0

    def __repr__(self) -> str:
        return f"PiDimmableLED(pin={self.pin})"


class PiDCMotor(_PiPercentPWM, AbstractDCMotor):
    """A DC motor on a Pi PWM/enable pin (one direction), speed 0..100 %.

        motor = PiDCMotor(18)
        motor.speed(70)        # 70 % power
        motor.stop()
    """

    @property
    def is_running(self) -> bool:
        return self._percent > 0

    def speed(self, percent: float) -> None:
        """Run at `percent` power (0..100)."""
        self._set_percent(percent, "speed")

    def stop(self) -> None:
        self.speed(0)

    def __repr__(self) -> str:
        return f"PiDCMotor(pin={self.pin})"


class PiMosfet(_PiPercentPWM, AbstractMosfet):
    """A MOSFET switching a DC load from a Pi PWM pin -- a solid-state relay that
    can also do anything in between.

        pump = PiMosfet(18)
        pump.on()              # full power
        pump.level(40)         # ...or 40 % of it
        pump.fade_to(0, 2)     # ramp down over 2 s
        pump.off()

    Use a logic-level MOSFET (the Pi's 3.3 V gate won't fully open an ordinary one).
    """

    @property
    def is_on(self) -> bool:
        return self._percent > 0

    def level(self, percent: float) -> None:
        """Drive the load at `percent` power (0..100)."""
        self._set_percent(percent, "level")

    def on(self) -> None:
        self.level(100)

    def toggle(self) -> None:
        self.off() if self.is_on else self.on()

    def fade_to(self, percent: float, duration: float = 1.0) -> None:
        """Ramp to `percent` power over `duration` s. Non-blocking."""
        self._fade_percent(percent, duration, "level")

    def __repr__(self) -> str:
        return f"PiMosfet(pin={self.pin})"


class PiRGBLED(LocalDevice, AbstractRGBLED):
    """A common-cathode (default) or common-anode RGB LED on three Pi PWM pins.

        rgb = PiRGBLED(red=17, green=27, blue=22)
        rgb.color(255, 0, 0)    # red; each channel 0..255
        rgb.off()

    Three BCM GPIO pins, one per channel. ``common_anode=True`` inverts for a
    common-anode LED.
    """

    def __init__(self, red: GPIOLike, green: GPIOLike, blue: GPIOLike,
                 common_anode: bool = False,
                 board: "Raspberry | None" = None) -> None:
        self.red: int = int(red)
        self.green: int = int(green)
        self.blue: int = int(blue)
        self.common_anode: bool = common_anode
        self._last: tuple[int, int, int] = (0, 0, 0)
        self._dev: Any = None
        super().__init__(board)

    def _hw(self) -> Any:
        if self._dev is None:
            from gpiozero import RGBLED
            # gpiozero inverts internally for common-anode via active_high.
            self._dev = RGBLED(self.red, self.green, self.blue,
                               active_high=not self.common_anode)
        return self._dev

    def color(self, r: int, g: int, b: int) -> None:
        """Set the colour; each of r, g, b is 0..255."""
        for v in (r, g, b):
            if not 0 <= v <= 255:
                raise ValueError(f"colour channels must be 0..255, got {(r, g, b)}")
        self._hw().color = (r / 255, g / 255, b / 255)
        self._last = (int(r), int(g), int(b))

    def off(self) -> None:
        self.color(0, 0, 0)

    def _release(self) -> None:
        if self._dev is not None:
            self._dev.close()
            self._dev = None

    def __repr__(self) -> str:
        return f"PiRGBLED(red={self.red}, green={self.green}, blue={self.blue})"
