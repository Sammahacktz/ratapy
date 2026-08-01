"""Pi GPIO servos (ratapy.devices.PiServo / PiContinuousServo), plus a check that
a Pi device drives inside a BackgroundTasks block exactly like an Arduino one.

No hardware: gpiozero's mock pins (``mock_gpio``).
"""

from __future__ import annotations

import pytest

from ratapy.boards import Mega
from ratapy.devices import PiContinuousServo, PiLED, PiServo
from ratapy.protocol import RataError
from ratapy.raspberry import Raspberry
from ratapy.tasks import BackgroundTasks


@pytest.fixture
def rp() -> Raspberry:
    return Raspberry()


def test_servo_angle(mock_gpio: object, rp: Raspberry) -> None:
    sv = PiServo(18, board=rp)
    sv.angle(90)
    assert sv._angle == 90.0
    assert sv.is_busy() is False                  # instant


def test_servo_angle_rejects_out_of_range(mock_gpio: object, rp: Raspberry) -> None:
    sv = PiServo(18, board=rp)
    for bad in (-1, 181):
        with pytest.raises(ValueError, match="servo angle must be 0..180"):
            sv.angle(bad)


def test_servo_move_is_non_blocking(mock_gpio: object, rp: Raspberry) -> None:
    sv = PiServo(18, board=rp)
    sv.angle(0)
    sv.move(180, duration=0.05)
    assert sv.is_busy() is True                   # returned at once, still sweeping
    sv.wait(1.0)
    assert sv.is_busy() is False
    assert sv._angle == 180.0                      # ended at the target


def test_servo_move_zero_duration_is_instant(mock_gpio: object, rp: Raspberry) -> None:
    sv = PiServo(18, board=rp)
    sv.move(45, duration=0)
    assert sv._angle == 45.0
    assert sv.is_busy() is False


def test_continuous_servo_speed_maps_to_angle(mock_gpio: object, rp: Raspberry) -> None:
    wheel = PiContinuousServo(18, board=rp)
    wheel.speed(100)
    assert wheel._angle == 180.0                   # 90 + 100*0.9
    wheel.speed(-100)
    assert wheel._angle == 0.0
    wheel.stop()
    assert wheel._angle == 90.0


def test_continuous_servo_rejects_out_of_range(mock_gpio: object, rp: Raspberry) -> None:
    wheel = PiContinuousServo(18, board=rp)
    with pytest.raises(ValueError, match="speed must be -100..100"):
        wheel.speed(150)


def test_rejects_an_arduino_board(mock_gpio: object) -> None:
    with pytest.raises(RataError, match="attaches to the Raspberry"):
        PiServo(18, board=Mega("A"))


# --- the whole point: driven exactly like an Arduino device --------------

def test_drives_inside_background_tasks(mock_gpio: object, rp: Raspberry) -> None:
    """A Pi device slots into the same `BackgroundTasks` pattern as an Arduino one:
    a task runs a blocking `move(); wait()` sequence while the main thread does its
    own thing. Nothing device-specific -- same code shape either transport."""
    servo = PiServo(18, board=rp)
    led = PiLED(17, board=rp)

    with BackgroundTasks() as tasks:

        @tasks.run
        def sweep() -> None:
            while not tasks.stopping:
                servo.move(0, duration=0.02)
                servo.wait()
                servo.move(180, duration=0.02)
                servo.wait()

        led.on()                                  # main thread stays live
        tasks.sleep(0.1)                          # let the sweeper run a few cycles
        tasks.stop()

    # Block exited cleanly (a task error would re-raise here). Both devices worked.
    assert led.is_on is True
    assert servo._angle in (0.0, 180.0)
