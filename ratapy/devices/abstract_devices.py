"""Abstract devices -- the shared contract between the Arduino and Pi versions.

Every device in RATA now exists in two independent implementations: one behind an
Arduino (over the wire protocol, in ``complex_devices`` / ``simple_devices``) and
one wired straight to the Raspberry Pi's GPIO (in ``local/``, on top of gpiozero).
The two share **no implementation** -- a ``Servo`` and a ``PiServo`` are separate
classes with separate code. What they share is *this file*: a set of pure abstract
base classes that name the methods every version must have.

Both the Arduino class and the Pi class inherit the matching ``Abstract*`` here, so
the two are guaranteed to expose the same surface -- if either ever drops a method,
it stops being instantiable and a test catches it. Nothing here has a body: these
are contracts, not code.

The payoff is transport-agnostic code. Type against the abstract and either version
fits::

    def sweep(s: AbstractServo) -> None:   # takes a Servo OR a PiServo
        s.move(0, duration=1.0)
        s.move(180, duration=1.0)

The hierarchy mirrors the concrete "is-a" relationships (an ``LED`` is a
``DigitalOutput``), so the contracts compose the same way the implementations do.

Note what is deliberately *not* in the contract:

- **Constructors.** A pin means different things on each side -- an Arduino board
  pin number vs. a Raspberry **BCM GPIO** number -- and the boards differ
  (``board=Arduino`` vs ``board=Raspberry``). Each class owns its own ``__init__``.
- **Lifecycle helpers** (``wait()`` / ``is_busy()`` / ``sleep()``). Those are
  transport mechanics (a firmware poll vs a background thread), not device API.
- **Analog inputs.** The Pi has no ADC, so ``AnalogInput`` and everything built on
  it stay Arduino-only -- there is no abstract for them, because there is no Pi
  half to hold to a shared contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


# --- digital outputs ------------------------------------------------------

class AbstractDigitalOutput(ABC):
    """An on/off output: ``on()`` / ``off()`` / ``toggle()`` / ``blink()``."""

    @property
    @abstractmethod
    def is_on(self) -> bool:
        """Whether the output is currently driven on."""

    @abstractmethod
    def on(self) -> None:
        """Drive the output on."""

    @abstractmethod
    def off(self) -> None:
        """Drive the output off."""

    @abstractmethod
    def toggle(self) -> None:
        """Flip the output."""

    @abstractmethod
    def blink(self, times: int = 1, on: float = 0.5, off: float = 0.5) -> None:
        """Blink ``times`` times (0 = forever), ``on``/``off`` seconds per phase.

        Non-blocking on both transports: the work runs in the background (the
        board's firmware for an Arduino, a thread for the Pi) and the call returns
        at once. Ends with the output off.
        """


class AbstractLED(AbstractDigitalOutput):
    """A plain on/off LED -- a ``DigitalOutput`` named for its most common use."""


class AbstractRelay(AbstractDigitalOutput):
    """A relay. ``on()`` means ENERGISED whatever the module's wiring.

    Constructed with ``active_low`` for modules that energise on a LOW pin; that
    is a constructor concern (not part of this contract), but ``on()``/``off()``
    must always speak in terms of energised/de-energised.
    """


class AbstractBuzzer(AbstractDigitalOutput):
    """An active buzzer (beeps on its own when powered)."""

    @abstractmethod
    def beep(self, duration: float = 0.1, times: int = 1, gap: float = 0.1) -> None:
        """Beep ``times`` times, ``duration`` s each, ``gap`` s between. Non-blocking."""


class AbstractSolenoid(AbstractDigitalOutput):
    """A solenoid / electromagnetic actuator -- an on/off pull."""

    @abstractmethod
    def energize(self) -> None:
        """Pull the solenoid in (coil on) and hold it."""

    @abstractmethod
    def deenergize(self) -> None:
        """Release the solenoid (coil off)."""

    @property
    @abstractmethod
    def is_energized(self) -> bool:
        """Whether ``energize()``/``deenergize()`` last left it on."""

    @abstractmethod
    def pulse(self, seconds: float = 0.1) -> None:
        """Energize for ``seconds``, then release. Non-blocking."""


# --- PWM outputs ----------------------------------------------------------

class AbstractPWM(ABC):
    """A PWM output -- a duty cycle 0 (off) .. 255 (full)."""

    @abstractmethod
    def set(self, value: int) -> None:
        """Set the duty cycle, 0 (off) .. 255 (full)."""

    @abstractmethod
    def fraction(self, f: float) -> None:
        """Set the duty as a fraction, 0.0 .. 1.0."""

    @abstractmethod
    def off(self) -> None:
        """Duty to zero."""

    @abstractmethod
    def fade(self, value: int, duration: float = 1.0) -> None:
        """Ramp the duty smoothly to ``value`` (0..255) over ``duration`` s. Non-blocking."""

    @abstractmethod
    def pulse(self, cycles: int = 1, period: float = 2.0, peak: int = 255) -> None:
        """Breathe up and down ``cycles`` times (0 = forever), ``period`` s per cycle."""

    @abstractmethod
    def blink(self, times: int = 1, on: float = 0.5, off: float = 0.5,
              peak: int = 255) -> None:
        """Blink ``times`` times (0 = forever) between ``peak`` duty and off."""


class AbstractDimmableLED(AbstractPWM):
    """An LED on a PWM pin -- brightness (0..100 %) and fades."""

    @property
    @abstractmethod
    def is_on(self) -> bool: ...

    @property
    @abstractmethod
    def percent(self) -> float:
        """The duty this was last set to, 0..100 (what you asked for)."""

    @abstractmethod
    def brightness(self, percent: float) -> None:
        """Set brightness to ``percent`` (0..100)."""

    @abstractmethod
    def on(self) -> None: ...

    @abstractmethod
    def toggle(self) -> None: ...

    @abstractmethod
    def fade_to(self, percent: float, duration: float = 1.0) -> None:
        """Smoothly change brightness to ``percent`` over ``duration`` s. Non-blocking."""


class AbstractDCMotor(AbstractPWM):
    """A DC motor on a driver's PWM/enable pin (one direction), speed 0..100 %."""

    @property
    @abstractmethod
    def is_running(self) -> bool: ...

    @property
    @abstractmethod
    def percent(self) -> float:
        """The power this was last set to, 0..100."""

    @abstractmethod
    def speed(self, percent: float) -> None:
        """Run at ``percent`` power (0..100)."""

    @abstractmethod
    def stop(self) -> None: ...


class AbstractMosfet(AbstractPWM):
    """A MOSFET switching a DC load -- a solid-state relay that can also do PWM."""

    @property
    @abstractmethod
    def is_on(self) -> bool: ...

    @property
    @abstractmethod
    def percent(self) -> float:
        """The level this was last set to, 0..100."""

    @abstractmethod
    def level(self, percent: float) -> None:
        """Drive the load at ``percent`` power (0..100)."""

    @abstractmethod
    def on(self) -> None: ...

    @abstractmethod
    def toggle(self) -> None: ...

    @abstractmethod
    def fade_to(self, percent: float, duration: float = 1.0) -> None:
        """Ramp to ``percent`` power over ``duration`` s. Non-blocking."""


# --- servos ---------------------------------------------------------------

class AbstractServo(ABC):
    """A hobby servo -- ``angle(0..180)`` and a timed ``move()``."""

    @abstractmethod
    def angle(self, degrees: int) -> None:
        """Snap to ``degrees`` (0..180)."""

    @abstractmethod
    def move(self, degrees: int, duration: float = 0.0) -> None:
        """Move to ``degrees`` (0..180); ``duration>0`` sweeps smoothly (non-blocking)."""


class AbstractContinuousServo(AbstractServo):
    """A continuous-rotation servo, where the 'angle' controls speed/direction."""

    @abstractmethod
    def speed(self, percent: float) -> None:
        """Run at ``percent`` speed, -100..100 (0 = stop)."""

    @abstractmethod
    def stop(self) -> None: ...


# --- digital inputs -------------------------------------------------------

class AbstractDigitalInput(ABC):
    """A digital input -- read HIGH/LOW."""

    @property
    @abstractmethod
    def value(self) -> bool:
        """Read the pin now: True if HIGH, False if LOW."""

    @abstractmethod
    def read(self) -> bool:
        """Read the pin now (same as ``value``)."""


class AbstractButton(AbstractDigitalInput):
    """A push button or switch, with edges and long-press timing.

    ``normally_closed`` (a switch that conducts at rest) is a constructor concern,
    not part of the contract.
    """

    @property
    @abstractmethod
    def is_pressed(self) -> bool:
        """True for every read while the button is down (a level)."""

    @property
    @abstractmethod
    def is_released(self) -> bool: ...

    @property
    @abstractmethod
    def was_pressed(self) -> bool:
        """True once per press, then False until the next (an edge)."""

    @property
    @abstractmethod
    def was_released(self) -> bool:
        """True once per release, then False until the next."""

    @property
    @abstractmethod
    def held_seconds(self) -> float:
        """How long the button has been (or, once let go, was) down."""

    @abstractmethod
    def pressed_for(self, seconds: float) -> bool:
        """True if the button is down right now and has been for ``seconds``."""

    @abstractmethod
    def wait_pressed_for(self, seconds: float, poll: float = 0.02) -> bool:
        """Watch for ``seconds``: True if held that whole time (blocking)."""

    @abstractmethod
    def wait_for_press(self, timeout: float | None = None, poll: float = 0.02) -> None:
        """Block until pressed (optional timeout in seconds)."""

    @abstractmethod
    def wait_for_release(self, timeout: float | None = None, poll: float = 0.02) -> None:
        """Block until released (optional timeout in seconds)."""


class AbstractLimitSwitch(AbstractButton):
    """An end-stop / limit switch -- a ``Button`` that is CLOSED at rest."""


class AbstractMotionSensor(AbstractDigitalInput):
    """A PIR motion sensor."""

    @property
    @abstractmethod
    def motion_detected(self) -> bool: ...

    @abstractmethod
    def wait_for_motion(self, timeout: float | None = None, poll: float = 0.05) -> None:
        """Block until motion is seen (optional timeout in seconds)."""


# --- other sensors --------------------------------------------------------

class AbstractUltrasonic(ABC):
    """An HC-SR04 ultrasonic distance sensor."""

    @property
    @abstractmethod
    def distance_mm(self) -> int | None:
        """Distance in millimetres, or None if out of range (no echo)."""

    @property
    @abstractmethod
    def distance_cm(self) -> float | None:
        """Distance in centimetres, or None if out of range."""


class AbstractRotaryEncoder(ABC):
    """An incremental (quadrature) rotary encoder."""

    @property
    @abstractmethod
    def position(self) -> int:
        """Signed count since the last reset."""

    @property
    @abstractmethod
    def detents(self) -> int:
        """Whole clicks turned (position / steps_per_detent, toward zero)."""

    @abstractmethod
    def reset(self) -> None:
        """Zero the count."""


class AbstractRGBLED(ABC):
    """A three-channel RGB LED."""

    @abstractmethod
    def color(self, r: int, g: int, b: int) -> None:
        """Set the colour; each of r, g, b is 0..255."""

    @abstractmethod
    def off(self) -> None:
        """All channels off."""
