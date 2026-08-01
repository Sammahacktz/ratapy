"""The abstract contract holds: every device has the same methods on both transports.

This is the point of ``ratapy.devices.abstract_devices``. For each ``Abstract*``,
the Arduino class and its ``Pi*`` twin must BOTH inherit it and BOTH fully implement
it -- so the two can never drift apart. If someone adds a method to one side and
forgets the other, or a concrete stops implementing part of the contract, a case
here fails (a partly-abstract class can't even be constructed).

No hardware and no board: this is pure class-structure inspection.
"""

from __future__ import annotations

import pytest

from ratapy import devices as d
from ratapy.devices import abstract_devices as A

# (abstract contract, Arduino concrete, Pi concrete)
PAIRS = [
    (A.AbstractDigitalOutput, d.DigitalOutput, d.PiDigitalOutput),
    (A.AbstractLED, d.LED, d.PiLED),
    (A.AbstractRelay, d.Relay, d.PiRelay),
    (A.AbstractBuzzer, d.Buzzer, d.PiBuzzer),
    (A.AbstractSolenoid, d.Solenoid, d.PiSolenoid),
    (A.AbstractPWM, d.PWM, d.PiPWM),
    (A.AbstractDimmableLED, d.DimmableLED, d.PiDimmableLED),
    (A.AbstractDCMotor, d.DCMotor, d.PiDCMotor),
    (A.AbstractMosfet, d.Mosfet, d.PiMosfet),
    (A.AbstractRGBLED, d.RGBLED, d.PiRGBLED),
    (A.AbstractServo, d.Servo, d.PiServo),
    (A.AbstractContinuousServo, d.ContinuousServo, d.PiContinuousServo),
    (A.AbstractDigitalInput, d.DigitalInput, d.PiDigitalInput),
    (A.AbstractButton, d.Button, d.PiButton),
    (A.AbstractLimitSwitch, d.LimitSwitch, d.PiLimitSwitch),
    (A.AbstractMotionSensor, d.MotionSensor, d.PiMotionSensor),
    (A.AbstractUltrasonic, d.Ultrasonic, d.PiUltrasonic),
    (A.AbstractRotaryEncoder, d.RotaryEncoder, d.PiRotaryEncoder),
]

_IDS = [abstract.__name__ for abstract, _, _ in PAIRS]


@pytest.mark.parametrize("abstract, arduino, pi", PAIRS, ids=_IDS)
def test_both_transports_inherit_the_contract(
        abstract: type, arduino: type, pi: type) -> None:
    assert issubclass(arduino, abstract), f"{arduino.__name__} is not a {abstract.__name__}"
    assert issubclass(pi, abstract), f"{pi.__name__} is not a {abstract.__name__}"


@pytest.mark.parametrize("abstract, arduino, pi", PAIRS, ids=_IDS)
def test_the_two_are_separate_classes(abstract: type, arduino: type, pi: type) -> None:
    # Separate implementations -- no shared logic, per the design.
    assert pi is not arduino
    assert not issubclass(pi, arduino)
    assert not issubclass(arduino, pi)


@pytest.mark.parametrize("abstract, arduino, pi", PAIRS, ids=_IDS)
def test_both_fully_implement_the_contract(
        abstract: type, arduino: type, pi: type) -> None:
    # A class with a left-over abstractmethod cannot be instantiated -- so an
    # empty set here is exactly "implements every method the contract names".
    assert not getattr(arduino, "__abstractmethods__", frozenset()), (
        f"{arduino.__name__} still abstract: "
        f"{sorted(getattr(arduino, '__abstractmethods__'))}")
    assert not getattr(pi, "__abstractmethods__", frozenset()), (
        f"{pi.__name__} still abstract: "
        f"{sorted(getattr(pi, '__abstractmethods__'))}")


@pytest.mark.parametrize("abstract, arduino, pi", PAIRS, ids=_IDS)
def test_every_contract_method_is_present_on_both(
        abstract: type, arduino: type, pi: type) -> None:
    # Belt-and-braces: each name the contract declares resolves on both sides.
    for name in _contract_names(abstract):
        assert hasattr(arduino, name), f"{arduino.__name__} is missing {name}"
        assert hasattr(pi, name), f"{pi.__name__} is missing {name}"


def _contract_names(abstract: type) -> set[str]:
    """Every abstractmethod declared anywhere up this abstract's chain."""
    names: set[str] = set()
    for base in abstract.__mro__:
        for n, v in vars(base).items():
            if getattr(v, "__isabstractmethod__", False):
                names.add(n)
    return names


def test_the_abstracts_cannot_be_instantiated() -> None:
    for abstract, _, _ in PAIRS:
        with pytest.raises(TypeError):
            abstract()  # type: ignore[abstract]


def test_the_contracts_are_exported_from_ratapy_devices() -> None:
    for abstract, _, _ in PAIRS:
        assert getattr(d, abstract.__name__) is abstract
        assert abstract.__name__ in d.__all__
