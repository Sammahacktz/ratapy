"""Components 

These add no new firmware: each one *inherits* a primitive device (`PWM`,
`AnalogInput`, `DigitalInput`) and just wraps it in intention-revealing methods.
A `DimmableLED` is a `PWM` that knows about brightness and fades; a `Button` is a
`DigitalInput` that knows about pull-ups. Reach for these first; drop to the raw
primitive when you need something they don't cover.

    light = DimmableLED(pin=9)
    light.on(); light.fade_to(30); light.pulse()

    knob = Potentiometer(channel=0)
    print(knob.percent)

    button = Button(pin=4)
    if button.is_pressed: ...
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from ..boards import Arduino, PinLike
from .complex_devices import AnalogInput, DigitalInput, DigitalOutput, PWM, Servo
from ..protocol import RataError


class _PercentPWM(PWM):
    """Shared guts of the PWM conveniences: a duty cycle you set in percent.

    `DimmableLED`, `DCMotor` and `Mosfet` are one mechanism under three domain
    words -- brightness, speed, level. The percentage lives here (validate,
    scale to a duty, remember it) so the three cannot drift apart; each subclass
    only names it. Not public: use one of those three.
    """

    def __init__(self, pin: PinLike, board: Arduino | None = None) -> None:
        super().__init__(pin, board)
        self._percent: float = 0.0

    @property
    def percent(self) -> float:
        """The duty this was last set to, 0..100 (what YOU asked for, not a read
        of the pin -- a PWM output cannot be read back)."""
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


class DimmableLED(_PercentPWM):
    """An LED on a PWM pin -- like `LED`, but with brightness and fades.

        led = DimmableLED(pin=9)
        led.on()               # full brightness
        led.brightness(30)     # 30 %
        led.fade_to(0, 1.5)    # fade to off over 1.5 s
        led.blink(3)
        led.pulse(2)           # "breathe" twice

    `brightness` is a percentage, 0..100. (Use plain `LED` for a simple on/off
    output on any digital pin; this one needs a PWM-capable pin.)
    """

    @property
    def is_on(self) -> bool:
        return self._percent > 0

    def brightness(self, percent: float) -> None:
        """Set brightness to `percent` (0..100)."""
        self._set_percent(percent, "brightness")

    def on(self) -> None:
        self.brightness(100)

    def off(self) -> None:
        self.brightness(0)

    def toggle(self) -> None:
        self.off() if self.is_on else self.on()

    def fade_to(self, percent: float, duration: float = 1.0) -> None:
        """Smoothly change brightness to `percent` over `duration` seconds.

        Non-blocking: the board runs the ramp. Call `wait()` to block until done.
        """
        self._fade_percent(percent, duration, "brightness")

    def pulse(self, cycles: int = 1, period: float = 2.0, peak: int = 255) -> None:
        """Smoothly 'breathe' up and down `cycles` times (0 = forever).

        Non-blocking (the board runs it); `wait()` blocks until it ends.
        """
        super().pulse(cycles, period, peak)
        self._percent = 0.0


class DCMotor(_PercentPWM):
    """A DC motor driven through a driver board's PWM/enable pin (one direction).

        motor = DCMotor(pin=9)
        motor.speed(70)        # 70 % power
        motor.stop()

    Speed is 0..100 %. For forward/reverse you also need a direction pin (an
    H-bridge) -- not covered here yet.
    """

    @property
    def is_running(self) -> bool:
        return self._percent > 0

    def speed(self, percent: float) -> None:
        """Run at `percent` power (0..100)."""
        self._set_percent(percent, "speed")

    def stop(self) -> None:
        self.speed(0)


class Mosfet(_PercentPWM):
    """A MOSFET switching a DC load -- a silent `Relay` that can also do
    anything in between.

        pump = Mosfet(pin=9)
        pump.on()                  # gate high: full power
        pump.level(40)             # ...or 40 % of it
        pump.fade_to(0, 2)         # ramp down over 2 s
        pump.off()

    For LED strips, pumps, fans, heaters, solenoids: the load sits between V+
    and the drain, the gate goes to this pin, and the grounds are common. Being
    solid-state it switches fast enough to be driven by PWM, which is the whole
    reason to reach for one over a relay -- so this needs a **PWM-capable pin**.
    A MOSFET you only ever slam fully on and off is a plain `DigitalOutput` (or
    `Relay`) on any pin.

    Use a **logic-level** MOSFET: an ordinary one won't turn fully on from 5 V
    (let alone 3.3 V) and will cook itself half-open.
    """

    @property
    def is_on(self) -> bool:
        return self._percent > 0

    def level(self, percent: float) -> None:
        """Drive the load at `percent` power (0..100)."""
        self._set_percent(percent, "level")

    def on(self) -> None:
        self.level(100)

    def off(self) -> None:
        self.level(0)

    def toggle(self) -> None:
        self.off() if self.is_on else self.on()

    def fade_to(self, percent: float, duration: float = 1.0) -> None:
        """Ramp to `percent` power over `duration` seconds.

        Non-blocking: the board runs the ramp. Call `wait()` to block until done.
        """
        self._fade_percent(percent, duration, "level")

    def __repr__(self) -> str:
        return f"Mosfet(pin={self.pin})"



class Potentiometer(AnalogInput):
    """A rotary/slide potentiometer (or any 0..Vcc knob).

        knob = Potentiometer(channel=0)
        knob.percent           # 0..100
        knob.map_to(0, 180)    # e.g. drive a servo angle
    """

    @property
    def percent(self) -> float:
        """Position as 0..100 %."""
        return self.fraction * 100

    def map_to(self, low: float, high: float) -> float:
        """Map the current position onto the range [low, high]."""
        return low + self.fraction * (high - low)


class LightSensor(AnalogInput):
    """A light-dependent resistor (LDR) / photocell on an analog channel.

        ldr = LightSensor(channel=1)
        ldr.level              # 0..100 (higher = more light, with the usual
                               #          LDR-to-GND + pull-up-to-Vcc wiring)
        ldr.is_dark()

    Which direction means "bright" depends on your voltage divider -- flip the
    threshold logic if yours reads the other way.
    """

    @property
    def level(self) -> float:
        """Brightness as 0..100."""
        return self.fraction * 100

    def is_dark(self, below: float = 20) -> bool:
        return self.level < below

    def is_bright(self, above: float = 80) -> bool:
        return self.level > above


class TMP36(AnalogInput):
    """A TMP36 analog temperature sensor (also works for LM35-style parts by
    adjusting the formula).

        temp = TMP36(channel=2)
        temp.celsius
        temp.fahrenheit

    TMP36: output is 0.5 V at 0 degC and 10 mV/degC. Pass the board's real
    supply voltage as `vref` for accuracy.
    """

    def __init__(self, channel: PinLike, vref: float = 5.0,
                 board: Arduino | None = None) -> None:
        self.vref: float = vref
        super().__init__(channel, board)

    @property
    def celsius(self) -> float:
        return (self.voltage(self.vref) - 0.5) * 100

    @property
    def fahrenheit(self) -> float:
        return self.celsius * 9 / 5 + 32



class Button(DigitalInput):
    """A push button or switch.

        button = Button(pin=4)          # internal pull-up on by default
        if button.is_pressed: ...
        button.wait_for_press()

    With the default `pull_up=True`, wire the button between the pin and GND:
    released reads HIGH, pressed reads LOW -- `is_pressed` accounts for that.
    `is_pressed` is true for *every* poll while a finger is down,
    so a loop acting on it fires 50 times a second. `was_pressed` is true once
    per press -- almost always what you want in a loop:

        if button.was_pressed:          # once, however long they hold it
            gripper.close()

    For a *long* press there are two shapes, and which you want depends on who
    does the waiting:

        if button.pressed_for(4):       # asks about NOW -- call it in your loop
            ...
        if button.wait_pressed_for(4):  # sits and watches for up to 4 s
            ...

    `normally_closed=True` is for a switch that conducts at rest and OPENS when
    actuated -- limit switches, e-stops, reed switches. See `LimitSwitch`.
    """

    def __init__(self, pin: PinLike, pull_up: bool = True,
                 normally_closed: bool = False,
                 board: Arduino | None = None) -> None:
        
        self.normally_closed: bool = normally_closed
        self._pressed_since: float | None = None
        self._released_at: float | None = None       # None while still down
        self._reported_press: float | None = None
        self._reported_release: float | None = None
        super().__init__(pin, pull_up, board)

    @property
    def is_pressed(self) -> bool:
        # pull-up: pressed pulls the pin LOW; otherwise pressed drives it HIGH.
        down = (not self.value) if self.pull_up else self.value
        if self.normally_closed:
            down = not down
        # Track the edges here, so ANY read maintains them -- your own
        # `if button.is_pressed` loop feeds pressed_for() without knowing it.
        now = time.monotonic()
        if down:
            # A new press: the first ever, or the previous one has ended. (Down
            # with _released_at still None just means the same press, going on.)
            if self._pressed_since is None or self._released_at is not None:
                self._pressed_since = now
                self._released_at = None
        elif self._pressed_since is not None and self._released_at is None:
            self._released_at = now      # just let go -- freeze the duration here
        return down

    def _hold(self) -> float | None:
        """Seconds this button has been down *now*, or None if it is up. One read.

        The None matters: a button that is up and a button pressed this instant
        are both "0.0 seconds", and `pressed_for(0)` has to tell them apart.
        """
        if not self.is_pressed:                  # reads the pin; tracks the edges
            return None
        since = self._pressed_since
        return 0.0 if since is None else time.monotonic() - since

    @property
    def held_seconds(self) -> float:
        """How long the button has been down -- or, once let go, how long that
        press lasted. 0.0 only until it has ever been pressed.

        The number survives the release and stands until the next press, so you
        can act on the release rather than on a threshold::

            button.wait_for_press()
            button.wait_for_release()
            if button.held_seconds > 2:
                factory_reset()          # it was a long press

        While the button is down this grows; the moment it comes up it freezes
        at the length of that press. Like `pressed_for`, it counts from the
        first read that *saw* the button down.
        """
        held = self._hold()
        if held is not None:
            return held                          # still down: growing
        since, until = self._pressed_since, self._released_at
        if since is None or until is None:
            return 0.0                           # never pressed
        return until - since                     # let go: the press it just was

    @property
    def is_released(self) -> bool:
        return not self.is_pressed

    @property
    def was_pressed(self) -> bool:
        """True **once** per press, then False until the next one.

        `is_pressed` is a level -- true for every poll while a finger is down, so
        a loop acting on it fires the same action 50 times a second. This is the
        *edge*: it reports a press once, and reading it consumes that press::

            while True:
                if button.was_pressed:      # once per press, however long it is held
                    gripper.close()
                time.sleep(0.02)

        """
        self.is_pressed                     # one read; refreshes the edge state
        since = self._pressed_since
        if since is None or since == self._reported_press:
            return False
        self._reported_press = since
        return True

    @property
    def was_released(self) -> bool:
        """True **once** per release, then False until the next one.

        The pair to `was_pressed`, for acting when the finger comes off. Reads
        well with `held_seconds`, which freezes at the length of that press::

            if button.was_released:
                if button.held_seconds > 2:
                    factory_reset()         # it was a long press
                else:
                    next_channel()          # a tap
        """
        self.is_pressed                     # one read; refreshes the edge state
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

        Asks about this instant and returns immediately -- nothing waits, so
        thresholds stack naturally and the rest of your loop keeps running::

            while True:
                if button.pressed_for(6):
                    power_off()
                elif button.pressed_for(4):
                    reboot()
                camera.update()          # not held up by the button

        It times the hold from the first read that *saw* the button down, which
        is what you want in a loop like the above. The flip side: it only knows
        about presses it was watching. Ask once, out of the blue, and the answer
        is False however long the button has really been down -- the first read
        is when the clock starts. Poll it, or use `wait_pressed_for` to watch a
        press you already have.
        """
        if seconds < 0:
            raise ValueError(f"pressed_for() takes a positive time, got {seconds}")
        held = self._hold()
        return held is not None and held >= seconds

    def wait_pressed_for(self, seconds: float, poll: float = 0.02) -> bool:
        """Watch the button for `seconds`: True if it is held that whole time.

        The blocking half of `pressed_for` -- for when you have a press in your
        hands and want to know which kind it is::

            button.wait_for_press()
            if button.wait_pressed_for(2):
                factory_reset()          # held 2 s
            else:
                next_channel()           # let go early -- an ordinary tap

        Returns as soon as the answer is known: False the moment the button
        comes up, True once `seconds` have passed with it still down. It counts
        from *now*, so it answers False at once if the button is not already
        down. `poll` is how often it looks, each look being one round-trip.
        """
        if seconds < 0:
            raise ValueError(f"wait_pressed_for() takes a positive time, got {seconds}")
        deadline = time.monotonic() + seconds
        while True:
            if not self.is_pressed:
                return False              # let go early -- done, no need to wait
            now = time.monotonic()
            if now >= deadline:
                return True              # still down, and the time is up
            # Never overshoot the deadline: the last look must land ON it, or a
            # release in the final gap would go unnoticed and we'd answer True.
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
        return f"Button(pin={self.pin}{nc})"


class LimitSwitch(Button):
    """An end-stop / limit switch -- a `Button` that is CLOSED at rest.

        stop = LimitSwitch(pin=5)
        if stop.is_pressed:            # the axis has reached the end
            stepper.stop()

    Same class, one default flipped: a limit switch (like an e-stop or a reed
    switch) conducts until something actuates it, the opposite of a push button.
    Everything Button offers works unchanged -- `was_pressed` for the edge,
    `held_seconds`, `wait_for_press`.
    """

    def __init__(self, pin: PinLike, pull_up: bool = True,
                 normally_closed: bool = True,
                 board: Arduino | None = None) -> None:
        super().__init__(pin, pull_up, normally_closed, board)

    def __repr__(self) -> str:
        return f"LimitSwitch(pin={self.pin})"


class MotionSensor(DigitalInput):
    """A PIR motion sensor.

        pir = MotionSensor(pin=3)
        if pir.motion_detected: ...
        pir.wait_for_motion()

    A PIR drives its output HIGH when it sees motion, so no pull-up is used.
    """

    def __init__(self, pin: PinLike, board: Arduino | None = None) -> None:
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
        return f"MotionSensor(pin={self.pin})"



class LED(DigitalOutput):
    """An LED on a digital pin -- the friendly name for a plain on/off output.

        led = LED(pin=2)
        led.on(); led.off(); led.toggle(); led.blink(3)

    Same as `DigitalOutput`, just named for the most common use. For brightness
    use `DimmableLED` (needs a PWM pin).
    """

    def __repr__(self) -> str:
        return f"LED(pin={self.pin})"


class Relay(DigitalOutput):
    """A relay -- a mechanical on/off switch on any digital pin.

        relay = Relay(pin=7)
        relay.on()
        relay.off()
        relay.toggle()

    Many relay modules are ACTIVE-LOW (a LOW pin energises the relay). Pass
    `active_low=True` so `on()` always means "energised", whatever the wiring.

    For a silent, solid-state switch that can also do partial power, see
    `Mosfet` (needs a PWM pin).
    """

    def __init__(self, pin: PinLike, active_low: bool = False,
                 board: Arduino | None = None) -> None:
        self.active_low: bool = active_low
        super().__init__(pin, board)

    def on(self) -> None:
        self._send(b"\x00" if self.active_low else b"\x01")
        self._on = True

    def off(self) -> None:
        self._send(b"\x01" if self.active_low else b"\x00")
        self._on = False

    def blink(self, times: int = 1, on: float = 0.5, off: float = 0.5) -> None:
        """Cycle the relay `times` times. Not available on an active-low module.

        `active_low` is a Python-side inversion: `on()`/`off()` flip the byte
        before sending. A blink is run by the *firmware*, which toggles the pin
        itself and knows nothing of the inversion -- so on an active-low module
        every phase would come out backwards AND it would finish ENERGISED
        (the firmware ends a blink with the pin LOW, which is 'on' here). That
        is a bad surprise when the relay is holding a pump, so it is refused
        rather than quietly wrong.
        """
        if self.active_low:
            raise RataError(
                f"{self!r}: blink() would be inverted on an active-low relay, and "
                "would leave it ENERGISED -- the board runs the blink and does not "
                "know about active_low. Drive it with on()/off() (each honours the "
                "inversion), or wire it active-high."
            )
        super().blink(times, on, off)

    def __repr__(self) -> str:
        return f"Relay(pin={self.pin})"


class Buzzer(DigitalOutput):
    """An active buzzer (the kind that beeps on its own when powered).

        buzzer = Buzzer(pin=8)
        buzzer.beep()               # one short beep
        buzzer.beep(0.05, times=3)  # three quick beeps

    (A passive buzzer that needs a driven frequency would need a firmware Tone
    device -- not implemented yet.)
    """

    def beep(self, duration: float = 0.1, times: int = 1, gap: float = 0.1) -> None:
        """Beep `times` times, `duration` s each, `gap` s between.

        Non-blocking (the board runs the pattern) -- call `wait()` to block until
        it's done. Built on the firmware blink, so it composes like any other.
        """
        self.blink(times, on=duration, off=gap)

    def __repr__(self) -> str:
        return f"Buzzer(pin={self.pin})"


class ContinuousServo(Servo):
    """A continuous-rotation servo, where the 'angle' controls speed/direction.

        wheel = ContinuousServo(pin=9)
        wheel.speed(100)     # full speed forward
        wheel.speed(-50)     # half speed reverse
        wheel.stop()

    speed is -100..100 (0 = stop). Trim `stop()` if your servo creeps at 90.
    """

    def speed(self, percent: float) -> None:
        if not -100 <= percent <= 100:
            raise ValueError(f"speed must be -100..100, got {percent}")
        self.angle(round(90 + percent * 0.9))   # -100..100 -> 0..180 (90 = stop)

    def stop(self) -> None:
        self.angle(90)


class SoilMoisture(AnalogInput):
    """A resistive/capacitive soil-moisture probe on an analog channel.

        soil = SoilMoisture(channel=0, dry=850, wet=350)
        soil.moisture       # 0 (dry) .. 100 (wet)

    Calibrate `dry` (raw reading in air) and `wet` (raw in water) for your probe;
    `moisture` interpolates between them.
    """

    def __init__(self, channel: PinLike, dry: int = 1023, wet: int = 0,
                 board: Arduino | None = None) -> None:
        self.dry: int = dry
        self.wet: int = wet
        super().__init__(channel, board)

    @property
    def moisture(self) -> float:
        span = self.wet - self.dry
        if span == 0:
            return 0.0
        pct = (self.value - self.dry) / span * 100
        return max(0.0, min(100.0, pct))


class RGBLED:
    """A common-cathode (default) or common-anode RGB LED on three PWM pins.

        rgb = RGBLED(red=9, green=10, blue=11)
        rgb.color(255, 0, 0)    # red; each channel 0..255
        rgb.off()

    Registers three PWM devices, so it needs three PWM-capable pins.
    """

    def __init__(self, red: int, green: int, blue: int,
                 common_anode: bool = False, board: Arduino | None = None) -> None:
        self.common_anode: bool = common_anode
        self._r = PWM(red, board)
        self._g = PWM(green, board)
        self._b = PWM(blue, board)

    def color(self, r: int, g: int, b: int) -> None:
        """Set the colour; each of r, g, b is 0..255."""
        for channel, v in ((self._r, r), (self._g, g), (self._b, b)):
            if not 0 <= v <= 255:
                raise ValueError(f"colour channels must be 0..255, got {v}")
            channel.set(255 - v if self.common_anode else v)

    def off(self) -> None:
        self.color(0, 0, 0)

    def __repr__(self) -> str:
        return f"RGBLED(red={self._r.pin}, green={self._g.pin}, blue={self._b.pin})"


class Joystick:
    """A 2-axis analog joystick with a push button (e.g. a KY-023 module).

        joy = Joystick(x_channel=0, y_channel=1, button_pin=4)
        joy.x            # -1.0 (left) .. 1.0 (right)
        joy.y            # -1.0 .. 1.0
        joy.is_pressed

    Registers the two axes (and the button, if given) as separate devices.
    """

    def __init__(self, x_channel: PinLike, y_channel: PinLike,
                 button_pin: PinLike | None = None,
                 board: Arduino | None = None) -> None:
        self.x_axis = Potentiometer(x_channel, board)
        self.y_axis = Potentiometer(y_channel, board)
        self.button = Button(button_pin, board=board) if button_pin is not None else None

    @property
    def x(self) -> float:
        return self.x_axis.fraction * 2 - 1

    @property
    def y(self) -> float:
        return self.y_axis.fraction * 2 - 1

    @property
    def position(self) -> tuple[float, float]:
        return (self.x, self.y)

    @property
    def is_pressed(self) -> bool:
        return self.button.is_pressed if self.button is not None else False


class RotarySwitch:
    """A multi-position rotary/selector switch -- one pin per position.

        selector = RotarySwitch(pins=[2, 3, 4, 5])
        selector.position     # index of the selected position (0..n-1), or None

    Wire the switch's common to GND and each position to a pin; the internal
    pull-ups make an unselected pin read HIGH and the selected one LOW. Reads all
    the pins on each `position` query, so it suits a slowly-changing selector
    (for a spinning knob use `RotaryEncoder` instead).
    """

    def __init__(self, pins: Sequence[PinLike], board: Arduino | None = None) -> None:
        if len(pins) < 2:
            raise ValueError(f"a rotary switch needs at least 2 positions, got {len(pins)}")
        self._inputs = [DigitalInput(pin, pull_up=True, board=board) for pin in pins]

    @property
    def count(self) -> int:
        """Number of positions."""
        return len(self._inputs)

    @property
    def position(self) -> int | None:
        """Index of the selected position (the pin reading LOW), or None."""
        for i, inp in enumerate(self._inputs):
            if not inp.value:          # pull-up: selected position reads LOW
                return i
        return None
