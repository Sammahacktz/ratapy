"""MQ2 gas/smoke sensor -- a composite of AnalogInput (AO) + DigitalInput (DO)."""

from __future__ import annotations

import pytest

from ratapy.boards import Mega
from ratapy.devices import MQ2
from ratapy.protocol import RataError
from ratapy.raspberry import Raspberry
from tests.conftest import MockLink


@pytest.fixture
def rig() -> tuple[Raspberry, Mega, MockLink]:
    link = MockLink()
    rp = Raspberry(link=link)
    board = Mega("A", link=link)
    rp.register_arduino(board, verify=False)
    return rp, board, link


def test_ao_gives_value_and_level(rig: tuple[Raspberry, Mega, MockLink]) -> None:
    _, board, link = rig
    gas = MQ2(channel=0, board=board)
    link.values[gas.ao._id] = 700
    assert gas.value == 700
    assert abs(gas.level - 700 / 1023 * 100) < 1e-6


def test_ao_only_needs_no_digital_pin(rig: tuple[Raspberry, Mega, MockLink]) -> None:
    _, board, link = rig
    gas = MQ2(channel=0, board=board)          # DO not wired
    assert gas.do is None
    link.values[gas.ao._id] = 512
    assert gas.value == 512                    # analog still works


def test_alarm_without_a_digital_pin_is_a_clear_error(
        rig: tuple[Raspberry, Mega, MockLink]) -> None:
    _, board, _ = rig
    gas = MQ2(channel=0, board=board)
    with pytest.raises(RataError, match="alarm needs the DO pin"):
        _ = gas.alarm


def test_alarm_default_polarity_is_active_low(
        rig: tuple[Raspberry, Mega, MockLink]) -> None:
    # Most MQ modules drive DO LOW once the level passes the trim-pot threshold.
    _, board, link = rig
    gas = MQ2(channel=0, digital_pin=4, board=board)
    link.values[gas.do._id] = 0                # LOW == gas detected
    assert gas.alarm is True
    link.values[gas.do._id] = 1                # HIGH == below threshold
    assert gas.alarm is False


def test_alarm_when_high_flips_the_polarity(
        rig: tuple[Raspberry, Mega, MockLink]) -> None:
    _, board, link = rig
    gas = MQ2(channel=0, digital_pin=4, board=board, alarm_when_high=True)
    link.values[gas.do._id] = 1                # HIGH == gas detected now
    assert gas.alarm is True
    link.values[gas.do._id] = 0
    assert gas.alarm is False


def test_ao_and_do_are_independent_devices(
        rig: tuple[Raspberry, Mega, MockLink]) -> None:
    # Two separate registrations, two ids -- the analog level and the alarm
    # threshold don't interfere.
    _, board, link = rig
    gas = MQ2(channel=0, digital_pin=4, board=board)
    assert gas.ao._id != gas.do._id
    link.values[gas.ao._id] = 900              # high analog level...
    link.values[gas.do._id] = 1                # ...but DO says below threshold
    assert gas.value == 900
    assert gas.alarm is False


def test_a_label_works_for_the_analog_channel(
        rig: tuple[Raspberry, Mega, MockLink]) -> None:
    from ratapy.boards import AnalogPin
    _, board, link = rig
    gas = MQ2(channel=AnalogPin.A3, board=board)
    link.values[gas.ao._id] = 100
    assert gas.value == 100                    # channel label resolved fine
