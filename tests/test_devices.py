"""Device behaviour against a mock link: registration, encoding, validation."""

from __future__ import annotations

import pytest

from ratapy import protocol as p
from ratapy.protocol import RataError
from ratapy.devices import (
    AnalogInput,
    DHT,
    DigitalOutput,
    PWM,
    RotaryEncoder,
    Servo,
    StepperWithDriver,
)
from tests.conftest import MockLink

from ratapy.boards import AnalogPin, Mega


def test_registration_sends_add_device_with_params(board: Mega, link: MockLink) -> None:
    DigitalOutput(pin=7, board=board)
    add = [f for f in link.sent if f.cmd == p.CMD_ADD_DEVICE][-1]
    # payload: [id, type, params...]
    assert add.payload[1] == p.DEV_DIGITAL_OUT
    assert add.payload[2] == 7                       # the pin


def test_digital_output_on_off_toggle(board: Mega, link: MockLink) -> None:
    out = DigitalOutput(pin=7, board=board)
    out.on()
    assert link.last_write_payload() == b"\x01"
    out.off()
    assert link.last_write_payload() == b"\x00"
    assert out.is_on is False
    out.toggle()
    assert link.last_write_payload() == b"\x01" and out.is_on is True


def test_pwm_range_validation(board: Mega) -> None:
    led = PWM(pin=9, board=board)
    led.set(255)
    with pytest.raises(ValueError):
        led.set(256)
    with pytest.raises(ValueError):
        led.fraction(1.5)


def test_pwm_requires_pwm_pin(board: Mega) -> None:
    with pytest.raises(ValueError, match="not PWM-capable"):
        PWM(pin=22, board=board)                     # 22 is not a Mega PWM pin


def test_servo_angle_bounds(board: Mega, link: MockLink) -> None:
    servo = Servo(pin=9, board=board)
    servo.angle(180)
    assert link.last_write_payload() == bytes([180])
    with pytest.raises(ValueError):
        servo.angle(181)


def test_stepper_needs_four_pins(board: Mega) -> None:
    with pytest.raises(ValueError, match="4 pins"):
        StepperWithDriver(pins=[1, 2, 3], board=board)


def test_stepper_encodes_steps_and_speed(board: Mega, link: MockLink) -> None:
    st = StepperWithDriver(pins=[8, 10, 9, 11], board=board)
    st.step(-200, speed=300)
    payload = link.last_write_payload()
    assert payload[0:2] == (-200).to_bytes(2, "big", signed=True)
    assert payload[2:4] == (300).to_bytes(2, "big")


def test_stepper_run_and_stop_encoding(board: Mega, link: MockLink) -> None:
    st = StepperWithDriver(pins=[8, 10, 9, 11], board=board)
    st.run(-150)
    pl = link.last_write_payload()
    assert pl[0] == 1 and pl[1:3] == (-150).to_bytes(2, "big", signed=True)
    st.stop()
    assert link.last_write_payload() == b"\x00"
    with pytest.raises(ValueError):
        st.run(0)                                     # zero speed is not a run


def test_servo_move_encoding(board: Mega, link: MockLink) -> None:
    servo = Servo(pin=9, board=board)
    servo.angle(90)
    assert link.last_write_payload() == bytes([90])   # instant = one byte
    servo.move(180, duration=1.5)
    pl = link.last_write_payload()
    assert pl[0] == 1 and pl[1] == 180 and int.from_bytes(pl[2:4], "big") == 1500
    servo.move(45, duration=0)                         # duration 0 -> instant angle
    assert link.last_write_payload() == bytes([45])
    with pytest.raises(ValueError):
        servo.move(200)                               # angle out of range


def test_analog_input_reads_value_and_fraction(board: Mega, link: MockLink) -> None:
    pot = AnalogInput(channel=0, board=board)
    link.value = 512
    assert pot.value == 512
    assert abs(pot.fraction - 512 / 1023) < 1e-6
    assert abs(pot.voltage(vref=5.0) - 512 / 1023 * 5.0) < 1e-6


def test_analog_input_channel_validation(board: Mega) -> None:
    with pytest.raises(ValueError, match="analog channels"):
        AnalogInput(channel=99, board=board)         # Mega has A0..A15


def test_encoder_position_and_reset(board: Mega, link: MockLink) -> None:
    knob = RotaryEncoder(clk=2, dt=3, board=board)
    link.value = -8
    assert knob.position == -8
    assert knob.detents == -2                         # -8 / 4 steps-per-detent
    knob.reset()
    assert link.last_write_payload() == b"\x00"


def test_dht_parses_two_values(board: Mega, link: MockLink) -> None:
    dht = DHT(pin=4, kind=22, board=board)
    # firmware packs tempC*10, hum%*10 as two big-endian int16s
    t, h = 234, 555
    link.value = 0  # unused; override _exchange payload via a custom frame

    # patch the link to return a 4-byte DHT payload for the next read
    import ratapy.protocol as pr

    def dht_exchange(address: object, frame: bytes) -> pr.Frame:
        req = pr.Frame(frame[1], frame[3:3 + frame[2]])
        if req.cmd == p.CMD_READ:
            body = t.to_bytes(2, "big", signed=True) + h.to_bytes(2, "big", signed=True)
            return pr.Frame(p.RSP_VALUE, bytes([req.payload[0]]) + body)
        return pr.Frame(p.RSP_ACK, b"")

    link._exchange = dht_exchange  # type: ignore[method-assign]
    reading = dht.read()
    assert reading.temperature == 23.4
    assert reading.humidity == 55.5


def test_digital_blink_is_one_nonblocking_write(board: Mega, link: MockLink) -> None:
    led = DigitalOutput(pin=7, board=board)
    led.blink(3, on=0.2, off=0.1)
    assert len(link.writes()) == 1                    # one command, not a sleep loop
    payload = link.last_write_payload()
    assert payload[0] == 2                             # blink opcode
    assert int.from_bytes(payload[1:3], "big") == 3   # times
    assert int.from_bytes(payload[3:5], "big") == 200  # on ms
    assert int.from_bytes(payload[5:7], "big") == 100  # off ms


def test_blink_composes_with_executor(board: Mega, link: MockLink) -> None:
    from ratapy.executor import ParallelExecutor

    led = DigitalOutput(pin=7, board=board)
    with ParallelExecutor():
        led.blink(2, on=0.1, off=0.1)                 # queued, not sent yet
        assert p.CMD_STAGE not in [f.cmd for f in link.sent]
    cmds = [f.cmd for f in link.sent]
    assert p.CMD_STAGE in cmds and p.CMD_COMMIT in cmds   # one staged blink, committed


def test_pwm_fade_pulse_blink_encoding(board: Mega, link: MockLink) -> None:
    led = PWM(pin=9, board=board)
    led.fade(200, duration=1.5)
    pl = link.last_write_payload()
    assert pl[0] == 1 and pl[1] == 200 and int.from_bytes(pl[2:4], "big") == 1500

    led.pulse(4, period=2.0, peak=128)
    pl = link.last_write_payload()
    assert pl[0] == 2 and int.from_bytes(pl[1:3], "big") == 4 and pl[3] == 128

    led.blink(3, on=0.2, off=0.2, peak=255)
    pl = link.last_write_payload()
    assert pl[0] == 3 and int.from_bytes(pl[1:3], "big") == 3 and pl[3] == 255


def test_save_devices_sends_cmd_save(board: Mega, link: MockLink) -> None:
    DigitalOutput(pin=7, board=board)
    board.save_devices()
    assert any(f.cmd == p.CMD_SAVE for f in link.sent)


def test_every_device_has_wait_and_instant_devices_return_at_once(board: Mega) -> None:
    # an LED is never busy: is_busy() is False and wait() returns immediately
    out = DigitalOutput(pin=7, board=board)
    assert out.is_busy() is False
    out.wait(timeout=0.01)                            # must not raise / hang


def test_stepper_is_busy_tracks_moving(board: Mega, link: MockLink) -> None:
    st = StepperWithDriver(pins=[8, 10, 9, 11], board=board)
    link.value = 1                                   # firmware: 1 == still moving
    assert st.is_busy() is True
    link.value = 0                                   # 0 == idle
    assert st.is_busy() is False
    st.wait(timeout=0.5)                             # idle -> returns promptly


def test_wait_times_out_when_stuck_busy(board: Mega, link: MockLink) -> None:
    st = StepperWithDriver(pins=[8, 10, 9, 11], board=board)
    link.value = 1                                   # never reports idle
    with pytest.raises(RataError, match="still busy"):
        st.wait(timeout=0.05, poll=0.01)


def test_dht_read_failure_raises(board: Mega, link: MockLink) -> None:
    dht = DHT(pin=4, kind=22, board=board)
    import ratapy.protocol as pr

    def fail_exchange(address: object, frame: bytes) -> pr.Frame:
        sentinel = (-32768).to_bytes(2, "big", signed=True)
        return pr.Frame(p.RSP_VALUE, b"\x00" + sentinel + sentinel)

    link._exchange = fail_exchange  # type: ignore[method-assign]
    with pytest.raises(RataError, match="DHT read failed"):
        dht.read()


# --- pin labels (AnalogPin.A1) --------------------------------------------

def test_device_accepts_a_pin_label_and_sends_the_resolved_number(
        board: Mega, link: MockLink) -> None:
    # The device must put the BOARD's number on the wire, not the label: A0 is
    # pin 54 on a Mega. The firmware only ever sees numbers.
    led = DigitalOutput(pin=AnalogPin.A0, board=board)
    assert led.pin == 54
    add = [f for f in link.sent if f.cmd == p.CMD_ADD_DEVICE][-1]
    assert add.payload[2] == 54


def test_device_accepts_the_enum(board: Mega, link: MockLink) -> None:
    led = DigitalOutput(pin=AnalogPin.A1, board=board)
    assert led.pin == 55
    add = [f for f in link.sent if f.cmd == p.CMD_ADD_DEVICE][-1]
    assert add.payload[2] == 55


def test_labels_work_for_multi_pin_devices(board: Mega) -> None:
    enc = RotaryEncoder(clk=AnalogPin.A0, dt=AnalogPin.A1, board=board)
    assert (enc.clk, enc.dt) == (54, 55)
    stepper = StepperWithDriver(pins=[AnalogPin.A0, 9, AnalogPin.A2, AnalogPin.A3],
                                board=board)
    assert stepper.pins == (54, 9, 56, 57)


def test_analog_input_accepts_a_label_as_its_channel(board: Mega, link: MockLink) -> None:
    # A label on an analog read means the CHANNEL (2), not the pin number (56).
    pot = AnalogInput(channel=AnalogPin.A2, board=board)
    assert pot.channel == 2
    add = [f for f in link.sent if f.cmd == p.CMD_ADD_DEVICE][-1]
    assert add.payload[2] == 2


def test_a_bad_pin_is_rejected_before_anything_is_sent(
        board: Mega, link: MockLink) -> None:
    before = len(link.sent)
    # A string is the tempting wrong guess -- it must not reach the board.
    with pytest.raises(TypeError, match="is not a pin"):
        DigitalOutput(pin="A0", board=board)      # type: ignore[arg-type]
    with pytest.raises(ValueError, match="has no pin 99"):
        Servo(pin=99, board=board)
    assert len(link.sent) == before               # nothing reached the board


def test_pwm_label_still_checks_pwm_capability(board: Mega) -> None:
    # Resolving must not bypass the capability check: A0 (54) is not PWM.
    with pytest.raises(ValueError, match="not PWM-capable"):
        PWM(pin=AnalogPin.A0, board=board)
