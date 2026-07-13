"""Board profiles + pin validation (no hardware, no link)."""

from __future__ import annotations

import pytest

from ratapy.boards import AnalogPin, Leonardo, Mega, Micro, Nano, Uno


def test_model_profiles() -> None:
    assert Uno.MODEL == "uno" and Uno.NUM_DIGITAL_PINS == 20
    assert Nano.MODEL == "nano" and Nano.NUM_ANALOG_INPUTS == 8
    assert Mega.MODEL == "mega" and Mega.NUM_DIGITAL_PINS == 70
    assert Mega.MAX_DEVICES == 32 and Uno.MAX_DEVICES == 12


def test_pin_counts_match_the_arduino_core() -> None:
    """These are the core's NUM_DIGITAL_PINS/NUM_ANALOG_INPUTS, not our guesses.

    The firmware reports them straight from the core (BoardConfig.h), and
    Arduino.verify() warns when they disagree with the profile -- so a wrong
    number here means every user of that board gets a spurious "wrong board or
    FQBN?" warning. Compile-verified against arduino:avr 1.8.6.

    The Nano is the trap: it looks like it should have 22 (A6/A7 exist), but its
    `eightanaloginputs` variant is the Uno's `standard` variant with ONLY
    NUM_ANALOG_INPUTS overridden -- A6/A7 are ADC-only and have no pin number.
    """
    expected = {                      # model: (digital, analog)
        Uno: (20, 6),
        Nano: (20, 8),                # NOT (22, 8)
        Mega: (70, 16),
        Leonardo: (31, 12),
        Micro: (31, 12),
    }
    actual = {b: (b.NUM_DIGITAL_PINS, b.NUM_ANALOG_INPUTS) for b in expected}
    assert actual == expected


def test_nano_analog_only_pins_are_channels_not_pins() -> None:
    # A6/A7 are reachable as AnalogInput(channel=6/7); they are not digital pins,
    # so the digital gate must reject them (the core cannot digitalWrite them).
    nano = Nano("A")
    nano.check_pin(19)                              
    for pin in (20, 21):                            
        with pytest.raises(ValueError, match="has no pin"):
            nano.check_pin(pin)


def test_leonardo_micro_profiles() -> None:
    # Both are the ATmega32U4 variant -- identical pin map (Micro includes
    # Leonardo's pins_arduino.h), so only the model name differs.
    assert Leonardo.MODEL == "leonardo" and Leonardo.NUM_DIGITAL_PINS == 31
    assert Leonardo.NUM_ANALOG_INPUTS == 12 and Leonardo.MAX_DEVICES == 12
    assert Micro.MODEL == "micro"
    assert Micro.NUM_DIGITAL_PINS == Leonardo.NUM_DIGITAL_PINS
    assert Micro.PWM_PINS == Leonardo.PWM_PINS
    leo = Leonardo("A")
    leo.check_pin(13, pwm=True)                     # 13 is PWM on the 32U4
    with pytest.raises(ValueError, match="not PWM-capable"):
        leo.check_pin(2, pwm=True)                  # 2 is not


def test_resolve_pin_maps_labels_per_board() -> None:
    # The same label is a different pin number on each model -- that mapping is
    # the whole point of resolving against the board.
    assert Uno("A").resolve_pin(AnalogPin.A0) == 14
    assert Nano("A").resolve_pin(AnalogPin.A1) == 15
    assert Mega("A").resolve_pin(AnalogPin.A0) == 54
    assert Mega("A").resolve_pin(AnalogPin.A15) == 69
    assert Leonardo("A").resolve_pin(AnalogPin.A0) == 18


def test_resolve_pin_accepts_numbers_and_labels() -> None:
    uno = Uno("A")
    assert uno.resolve_pin(13) == 13                 # numbers pass through
    assert uno.resolve_pin(AnalogPin.A1) == 15


def test_one_enum_member_resolves_per_board() -> None:
    """AnalogPin.A0 is a *label*: the same member is A0 on whichever board it
    reaches.

    This is why the members carry a label and not a pin number -- a number would
    have to come from a specific model, and handing a Mega's 54 to an Uno device
    (or an Uno's 14 to a Mega one, which is a valid Mega pin) would be wrong in
    the quiet way.
    """
    assert Uno("A").resolve_pin(AnalogPin.A0) == 14
    assert Nano("A").resolve_pin(AnalogPin.A0) == 14
    assert Mega("A").resolve_pin(AnalogPin.A0) == 54
    assert Leonardo("A").resolve_pin(AnalogPin.A0) == 18


def test_resolve_pin_rejects_labels_the_board_lacks() -> None:
    with pytest.raises(ValueError, match=r"uno has no A6 \(it has A0\.\.A5\)"):
        Uno("A").resolve_pin(AnalogPin.A6)


def test_anything_that_is_not_a_number_or_a_label_says_so() -> None:
    # mypy rejects these outright; this is the runtime net for an untyped caller
    # or a REPL, where the alternative is an AttributeError from inside resolve.
    for junk in ("A0", "D3", None, 1.5):
        with pytest.raises(TypeError, match="is not a pin"):
            Uno("A").resolve_pin(junk)              # type: ignore[arg-type]


def test_resolve_pin_explains_the_nanos_analog_only_pins() -> None:
    # A6/A7 exist on a Nano but are ADC-only: no digital pin number. The error
    # must say so in terms of the label the user typed, not "no pin 20".
    with pytest.raises(ValueError, match=r"A6 is analog-only.*channel=6"):
        Nano("A").resolve_pin(AnalogPin.A6)
    # ...but they are perfectly good analog channels.
    assert Nano("A").resolve_channel(AnalogPin.A6) == 6


def test_resolve_channel_is_label_identity_on_every_board() -> None:
    for board in (Uno("A"), Nano("A"), Mega("A"), Leonardo("A")):
        assert board.resolve_channel(AnalogPin.A2) == 2
        assert board.resolve_channel(2) == 2


def test_check_pin_accepts_valid_and_rejects_out_of_range() -> None:
    uno = Uno("A")
    uno.check_pin(0)
    uno.check_pin(13)
    with pytest.raises(ValueError, match="no pin 99"):
        uno.check_pin(99)


def test_check_pin_pwm_capability() -> None:
    uno = Uno("A")
    uno.check_pin(9, pwm=True)                      # 9 is PWM on the Uno
    with pytest.raises(ValueError, match="not PWM-capable"):
        uno.check_pin(7, pwm=True)                  # 7 is not


def test_check_pin_analog_capability() -> None:
    mega = Mega("A")
    mega.check_pin(54, analog=True)                 # A0 on the Mega
    with pytest.raises(ValueError, match="not an analog input"):
        mega.check_pin(2, analog=True)


def test_nano_inherits_uno_pins_but_has_two_more_channels() -> None:
    # The Nano IS the Uno's pin map (same variant); its only extra is two ADC
    # channels, which exist as channels 6/7 and not as pins -- see
    # test_nano_analog_only_pins_are_channels_not_pins.
    assert Nano.PWM_PINS == Uno.PWM_PINS
    assert Nano.ANALOG_PINS == Uno.ANALOG_PINS
    assert Nano.NUM_ANALOG_INPUTS == Uno.NUM_ANALOG_INPUTS + 2
