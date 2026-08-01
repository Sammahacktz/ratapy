"""Pi GPIO output devices (ratapy.devices.PiLED / PiPWM / ...).

No hardware: gpiozero is pointed at its in-memory mock pins (the ``mock_gpio``
fixture), so we drive real device logic and read the pin state back. ``pin(n)`` is
the mock BCM pin n; ``.state`` is its level (0/1 digital, 0..1 PWM duty).
"""

from __future__ import annotations

import pytest

from ratapy.boards import Mega
from ratapy.devices import (
    PiBuzzer,
    PiDCMotor,
    PiDigitalOutput,
    PiDimmableLED,
    PiLED,
    PiMosfet,
    PiPWM,
    PiRelay,
    PiRGBLED,
    PiServo,
    PiSolenoid,
)
from ratapy.devices import PiPin
from ratapy.protocol import RataError
from ratapy.raspberry import Raspberry


@pytest.fixture
def rp() -> Raspberry:
    return Raspberry()


# --- pin labels (PiPin) ---------------------------------------------------

def test_pipin_is_the_bcm_number() -> None:
    assert PiPin.GPIO17 == 17                      # an IntEnum: value IS the BCM pin
    assert int(PiPin.GPIO18) == 18


def test_device_accepts_a_pipin_label(mock_gpio: object, rp: Raspberry) -> None:
    led = PiLED(PiPin.GPIO17, board=rp)
    assert led.pin == 17                           # resolved to the BCM number
    led.on()
    assert mock_gpio.pin(17).state == 1            # type: ignore[attr-defined]  same pin as PiLED(17)


def test_pipin_label_and_int_are_the_same_pin(mock_gpio: object, rp: Raspberry) -> None:
    assert PiServo(PiPin.GPIO18, board=rp).pin == PiServo(18, board=rp).pin


# --- digital outputs ------------------------------------------------------

def test_led_on_off_toggle(mock_gpio: object, rp: Raspberry) -> None:
    led = PiLED(17, board=rp)
    led.on()
    assert led.is_on is True
    assert mock_gpio.pin(17).state == 1          # type: ignore[attr-defined]
    led.off()
    assert led.is_on is False
    assert mock_gpio.pin(17).state == 0          # type: ignore[attr-defined]
    led.toggle()
    assert led.is_on is True


def test_relay_active_low_inverts_the_physical_pin(
        mock_gpio: object, rp: Raspberry) -> None:
    r = PiRelay(23, active_low=True, board=rp)
    r.on()                                        # energised
    assert r.is_on is True
    assert mock_gpio.pin(23).state == 0          # type: ignore[attr-defined]  LOW energises
    r.off()
    assert mock_gpio.pin(23).state == 1          # type: ignore[attr-defined]


def test_active_low_relay_can_blink_unlike_the_arduino(
        mock_gpio: object, rp: Raspberry) -> None:
    # The Arduino Relay refuses blink() when active_low (firmware can't invert);
    # on the Pi gpiozero runs it and honours the inversion, so it is allowed.
    r = PiRelay(23, active_low=True, board=rp)
    r.blink(2, on=0.01, off=0.01)                 # must NOT raise
    assert r.is_busy() is True
    r.wait(1.0)


def test_buzzer_beep_is_non_blocking(mock_gpio: object, rp: Raspberry) -> None:
    buz = PiBuzzer(24, board=rp)
    buz.beep(0.02, times=2)
    assert buz.is_busy() is True                  # returned at once, still beeping
    buz.wait(1.0)
    assert buz.is_busy() is False


def test_solenoid_energize_and_pulse(mock_gpio: object, rp: Raspberry) -> None:
    sol = PiSolenoid(25, board=rp)
    sol.energize()
    assert sol.is_energized is True
    assert mock_gpio.pin(25).state == 1          # type: ignore[attr-defined]
    sol.deenergize()
    assert sol.is_energized is False
    sol.pulse(0.03)
    assert sol.is_busy() is True                  # board/gpiozero times the release
    sol.wait(1.0)
    assert sol.is_busy() is False


def test_solenoid_pulse_rejects_nonpositive(mock_gpio: object, rp: Raspberry) -> None:
    sol = PiSolenoid(25, board=rp)
    with pytest.raises(ValueError, match="pulse seconds must be positive"):
        sol.pulse(0)


def test_blink_is_busy_then_idle(mock_gpio: object, rp: Raspberry) -> None:
    led = PiLED(17, board=rp)
    led.blink(2, on=0.01, off=0.01)
    assert led.is_busy() is True
    led.wait(1.0)
    assert led.is_busy() is False
    assert led.is_on is False


# --- PWM outputs ----------------------------------------------------------

def test_pwm_set_and_fraction(mock_gpio: object, rp: Raspberry) -> None:
    pwm = PiPWM(18, board=rp)
    pwm.set(128)
    assert abs(mock_gpio.pin(18).state - 128 / 255) < 1e-6   # type: ignore[attr-defined]
    pwm.fraction(0.25)
    assert abs(mock_gpio.pin(18).state - 0.25) < 1e-6        # type: ignore[attr-defined]
    pwm.off()
    assert mock_gpio.pin(18).state == 0                      # type: ignore[attr-defined]


def test_pwm_rejects_out_of_range(mock_gpio: object, rp: Raspberry) -> None:
    pwm = PiPWM(18, board=rp)
    for bad in (-1, 256):
        with pytest.raises(ValueError, match="PWM value must be 0..255"):
            pwm.set(bad)


def test_pwm_fade_is_non_blocking(mock_gpio: object, rp: Raspberry) -> None:
    pwm = PiPWM(18, board=rp)
    pwm.fade(255, duration=0.05)
    assert pwm.is_busy() is True
    assert abs(pwm._value - 1.0) < 1e-9           # lands at the target
    pwm.wait(1.0)
    assert pwm.is_busy() is False


def test_dimmable_led_brightness_percent(mock_gpio: object, rp: Raspberry) -> None:
    led = PiDimmableLED(18, board=rp)
    led.brightness(40)
    assert led.percent == 40
    assert led.is_on is True
    assert abs(mock_gpio.pin(18).state - 0.4) < 1e-6         # type: ignore[attr-defined]
    led.off()
    assert led.percent == 0
    assert led.is_on is False


def test_dc_motor_speed_stop(mock_gpio: object, rp: Raspberry) -> None:
    m = PiDCMotor(18, board=rp)
    m.speed(70)
    assert m.percent == 70 and m.is_running is True
    m.stop()
    assert m.is_running is False


def test_mosfet_level_and_on_off(mock_gpio: object, rp: Raspberry) -> None:
    mos = PiMosfet(18, board=rp)
    mos.level(40)
    assert mos.percent == 40 and mos.is_on is True
    mos.on()
    assert mos.percent == 100
    mos.off()
    assert mos.is_on is False


def test_percent_devices_reject_bad_percent(mock_gpio: object, rp: Raspberry) -> None:
    for cls, verb, word in ((PiDimmableLED, "brightness", "brightness"),
                            (PiDCMotor, "speed", "speed"),
                            (PiMosfet, "level", "level")):
        dev = cls(18, board=rp)
        with pytest.raises(ValueError, match=f"{word} must be 0..100"):
            getattr(dev, verb)(101)


def test_rgbled_color(mock_gpio: object, rp: Raspberry) -> None:
    rgb = PiRGBLED(17, 27, 22, board=rp)
    rgb.color(255, 0, 0)
    assert mock_gpio.pin(17).state == 1.0         # type: ignore[attr-defined]  red full
    assert mock_gpio.pin(27).state == 0.0         # type: ignore[attr-defined]
    rgb.off()
    assert mock_gpio.pin(17).state == 0.0         # type: ignore[attr-defined]


def test_rgbled_rejects_bad_channel(mock_gpio: object, rp: Raspberry) -> None:
    rgb = PiRGBLED(17, 27, 22, board=rp)
    with pytest.raises(ValueError, match="colour channels must be 0..255"):
        rgb.color(300, 0, 0)


# --- attachment + cleanup (shared LocalDevice behaviour) ------------------

def test_rejects_an_arduino_board(mock_gpio: object) -> None:
    with pytest.raises(RataError, match="attaches to the Raspberry"):
        PiLED(17, board=Mega("A"))


def test_hardware_is_opened_lazily(mock_gpio: object, rp: Raspberry) -> None:
    led = PiLED(17, board=rp)
    assert led._dev is None                       # nothing opened at construction
    led.on()
    assert led._dev is not None


def test_close_releases_the_pin(mock_gpio: object, rp: Raspberry) -> None:
    led = PiLED(17, board=rp)
    led.on()
    led.close()
    assert led._dev is None


def test_raspberry_close_releases_it(mock_gpio: object, rp: Raspberry) -> None:
    led = PiLED(17, board=rp)
    led.on()
    rp.close()
    assert led._dev is None
