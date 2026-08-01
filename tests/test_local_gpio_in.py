"""Pi GPIO input devices (ratapy.devices.PiButton / PiUltrasonic / ...).

No hardware: gpiozero's mock pins for the digital reads (``mock_gpio.pin(n)`` --
``drive_low()`` / ``drive_high()`` to simulate wiring), and injected fakes for the
sensors whose real reading needs echo/quadrature timing (as test_local_radar.py
injects a fake serial).
"""

from __future__ import annotations

import pytest

from ratapy.boards import Mega
from ratapy.devices import (
    PiButton,
    PiDigitalInput,
    PiLimitSwitch,
    PiMotionSensor,
    PiRotaryEncoder,
    PiUltrasonic,
)
from ratapy.protocol import RataError
from ratapy.raspberry import Raspberry


@pytest.fixture
def rp() -> Raspberry:
    return Raspberry()


# --- digital input / button ----------------------------------------------

def test_digital_input_reads_raw_level(mock_gpio: object, rp: Raspberry) -> None:
    di = PiDigitalInput(4, pull_up=True, board=rp)
    _ = di.value                                  # open the pin
    mock_gpio.pin(4).drive_high()                 # type: ignore[attr-defined]
    assert di.value is True and di.read() is True
    mock_gpio.pin(4).drive_low()                  # type: ignore[attr-defined]
    assert di.value is False


def test_button_is_pressed_pull_up(mock_gpio: object, rp: Raspberry) -> None:
    btn = PiButton(5, board=rp)                   # pull_up=True default
    _ = btn.is_pressed
    pin = mock_gpio.pin(5)                         # type: ignore[attr-defined]
    pin.drive_high()                              # released (rests HIGH)
    assert btn.is_pressed is False and btn.is_released is True
    pin.drive_low()                               # pressed (pulled LOW)
    assert btn.is_pressed is True


def test_button_edges_fire_once(mock_gpio: object, rp: Raspberry) -> None:
    btn = PiButton(5, board=rp)
    _ = btn.is_pressed
    pin = mock_gpio.pin(5)                         # type: ignore[attr-defined]
    pin.drive_high()
    pin.drive_low()                               # a press
    assert btn.was_pressed is True
    assert btn.was_pressed is False               # consumed
    pin.drive_high()                              # a release
    assert btn.was_released is True
    assert btn.was_released is False


def test_button_pressed_for(mock_gpio: object, rp: Raspberry) -> None:
    btn = PiButton(5, board=rp)
    _ = btn.is_pressed
    pin = mock_gpio.pin(5)                         # type: ignore[attr-defined]
    pin.drive_high()
    assert btn.pressed_for(0) is False            # not down at all
    pin.drive_low()
    assert btn.pressed_for(0) is True             # down now
    assert btn.pressed_for(10) is False           # but not for 10 s


def test_normally_closed_button_inverts(mock_gpio: object, rp: Raspberry) -> None:
    btn = PiButton(5, normally_closed=True, board=rp)
    _ = btn.is_pressed
    pin = mock_gpio.pin(5)                         # type: ignore[attr-defined]
    pin.drive_low()                               # NC: LOW (pull-up rest) => not actuated
    assert btn.is_pressed is False
    pin.drive_high()                              # opened => actuated
    assert btn.is_pressed is True


def test_limit_switch_is_normally_closed(mock_gpio: object, rp: Raspberry) -> None:
    stop = PiLimitSwitch(5, board=rp)
    assert stop.normally_closed is True


# --- motion ---------------------------------------------------------------

def test_motion_sensor(mock_gpio: object, rp: Raspberry) -> None:
    pir = PiMotionSensor(6, board=rp)
    _ = pir.motion_detected
    mock_gpio.pin(6).drive_high()                 # type: ignore[attr-defined]  PIR HIGH on motion
    assert pir.motion_detected is True
    mock_gpio.pin(6).drive_low()                  # type: ignore[attr-defined]
    assert pir.motion_detected is False


# --- ultrasonic (injected fake, echo timing can't be mocked simply) -------

class _FakeDistanceSensor:
    def __init__(self, metres: float) -> None:
        self.distance = metres
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_ultrasonic_converts_metres_to_mm(rp: Raspberry) -> None:
    sonar = PiUltrasonic(23, 24, max_distance_m=4.0, board=rp)
    sonar._dev = _FakeDistanceSensor(0.5)         # 0.5 m
    assert sonar.distance_mm == 500
    assert sonar.distance_cm == 50.0


def test_ultrasonic_out_of_range_is_none(rp: Raspberry) -> None:
    sonar = PiUltrasonic(23, 24, max_distance_m=4.0, board=rp)
    sonar._dev = _FakeDistanceSensor(4.0)         # clamped at max => nothing echoed
    assert sonar.distance_mm is None
    assert sonar.distance_cm is None


# --- rotary encoder (injected fake) ---------------------------------------

class _FakeEncoder:
    def __init__(self) -> None:
        self.steps = 0

    def close(self) -> None:
        pass


def test_rotary_encoder_position_and_reset(rp: Raspberry) -> None:
    enc = PiRotaryEncoder(5, 6, board=rp)
    enc._dev = _FakeEncoder()
    enc._dev.steps = 12
    assert enc.position == 12
    enc.reset()                                   # zero here
    assert enc.position == 0
    enc._dev.steps = 20
    assert enc.position == 8


def test_rotary_encoder_detents(rp: Raspberry) -> None:
    enc = PiRotaryEncoder(5, 6, steps_per_detent=4, board=rp)
    enc._dev = _FakeEncoder()
    enc._dev.steps = 8
    assert enc.detents == 2


# --- attachment -----------------------------------------------------------

def test_rejects_an_arduino_board(mock_gpio: object) -> None:
    with pytest.raises(RataError, match="attaches to the Raspberry"):
        PiButton(5, board=Mega("A"))
