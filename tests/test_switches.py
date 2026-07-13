"""Mosfet + Relay -- the two ways to switch a load.

Both are pure-Python conveniences over a firmware primitive (PWM / DigitalOutput),
so what we assert is the bytes they put on the wire.
"""

from __future__ import annotations

import pytest

from ratapy import protocol as p
from ratapy.boards import Mega
from ratapy.devices import DCMotor, DimmableLED, Mosfet, Relay
from ratapy.protocol import RataError
from tests.conftest import MockLink


def _last_write(link: MockLink) -> bytes:
    return [f for f in link.sent if f.cmd == p.CMD_WRITE][-1].payload


# --- Mosfet ---------------------------------------------------------------

def test_mosfet_registers_as_a_pwm_device(board: Mega, link: MockLink) -> None:
    # No new firmware: a Mosfet IS the PWM primitive under a domain name.
    Mosfet(pin=9, board=board)
    add = [f for f in link.sent if f.cmd == p.CMD_ADD_DEVICE][-1]
    assert add.payload[1] == p.DEV_PWM
    assert add.payload[2] == 9


def test_mosfet_on_off_are_full_and_zero_duty(board: Mega, link: MockLink) -> None:
    m = Mosfet(pin=9, board=board)
    m.on()
    assert _last_write(link)[-1] == 255
    assert m.is_on is True
    m.off()
    assert _last_write(link)[-1] == 0
    assert m.is_on is False


def test_mosfet_level_scales_percent_to_duty(board: Mega, link: MockLink) -> None:
    m = Mosfet(pin=9, board=board)
    m.level(40)
    assert _last_write(link)[-1] == round(0.4 * 255)
    assert m.percent == 40


def test_mosfet_toggle(board: Mega, link: MockLink) -> None:
    m = Mosfet(pin=9, board=board)
    m.toggle()
    assert m.is_on is True and _last_write(link)[-1] == 255
    m.toggle()
    assert m.is_on is False and _last_write(link)[-1] == 0


def test_mosfet_rejects_a_bad_level(board: Mega) -> None:
    m = Mosfet(pin=9, board=board)
    for bad in (-1, 101):
        with pytest.raises(ValueError, match="level must be 0..100"):
            m.level(bad)


def test_mosfet_fade_to_is_a_firmware_ramp(board: Mega, link: MockLink) -> None:
    m = Mosfet(pin=9, board=board)
    m.fade_to(50, duration=2)
    payload = _last_write(link)
    assert payload[1] == 0x01                    # the PWM fade sub-command
    assert payload[2] == round(0.5 * 255)
    assert m.percent == 50


def test_mosfet_needs_a_pwm_pin(board: Mega) -> None:
    # The point of a MOSFET over a relay is PWM, so a non-PWM pin is an error.
    # (22 is a plain digital pin on a Mega; 2-13 and 44-46 are the PWM ones.)
    with pytest.raises(ValueError, match="not PWM-capable"):
        Mosfet(pin=22, board=board)


# --- the shared percent mechanism ----------------------------------------

def test_the_three_percent_devices_share_one_scale(
        board: Mega, link: MockLink) -> None:
    """DimmableLED/DCMotor/Mosfet name the same thing -- they must agree."""
    duties = []
    for cls, verb in ((DimmableLED, "brightness"), (DCMotor, "speed"), (Mosfet, "level")):
        dev = cls(pin=9, board=board)
        getattr(dev, verb)(40)
        duties.append(_last_write(link)[-1])
        assert dev.percent == 40
    assert duties[0] == duties[1] == duties[2] == round(0.4 * 255)


def test_each_percent_device_names_its_own_error(board: Mega) -> None:
    for cls, verb, word in ((DimmableLED, "brightness", "brightness"),
                            (DCMotor, "speed", "speed"),
                            (Mosfet, "level", "level")):
        dev = cls(pin=9, board=board)
        with pytest.raises(ValueError, match=f"{word} must be 0..100"):
            getattr(dev, verb)(101)


# --- Relay ----------------------------------------------------------------

def test_relay_active_high(board: Mega, link: MockLink) -> None:
    r = Relay(pin=7, board=board)
    r.on()
    assert _last_write(link) == b"\x00\x01"      # [id, HIGH]
    r.off()
    assert _last_write(link) == b"\x00\x00"


def test_relay_active_low_inverts_the_pin(board: Mega, link: MockLink) -> None:
    # on() must mean ENERGISED whatever the module's wiring.
    r = Relay(pin=7, active_low=True, board=board)
    r.on()
    assert _last_write(link)[-1] == 0            # LOW energises this one
    assert r.is_on is True
    r.off()
    assert _last_write(link)[-1] == 1
    assert r.is_on is False


def test_relay_toggle_honours_active_low(board: Mega, link: MockLink) -> None:
    r = Relay(pin=7, active_low=True, board=board)
    r.toggle()
    assert r.is_on is True and _last_write(link)[-1] == 0


def test_active_low_relay_refuses_to_blink(board: Mega) -> None:
    """The firmware runs the blink and cannot know about active_low.

    Every phase would be inverted, and it would END energised (the firmware
    finishes a blink with the pin LOW = 'on' here) -- silently leaving whatever
    the relay holds switched ON.
    """
    r = Relay(pin=7, active_low=True, board=board)
    with pytest.raises(RataError, match="would be inverted"):
        r.blink(3)


def test_active_high_relay_can_still_blink(board: Mega, link: MockLink) -> None:
    r = Relay(pin=7, board=board)
    r.blink(2)
    assert _last_write(link)[1] == 0x02          # the DigitalOutput blink sub-command
