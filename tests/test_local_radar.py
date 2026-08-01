"""PiRadar (RD-03D) frame parsing.

No radar and no serial port: a fake serial feeds canned bytes, so the framing
(sync on header, verify footer, resync on junk) and the target decode are tested
in Python. This verifies the parser matches the RD-03D spec *as coded* -- it does
NOT prove the spec itself; that needs a real module (see raw_frame()).
"""

from __future__ import annotations

import pytest

from ratapy.devices import PiRadar, RadarTarget
from ratapy.devices.local.radar import _FOOTER, _HEADER
from ratapy.protocol import RataError
from ratapy.raspberry import Raspberry


def _target_bytes(x: int, y: int, speed: int, distance: int) -> bytes:
    """Encode one target the way the RD-03D does: 15-bit magnitude + sign flag."""
    def enc(v: int) -> bytes:
        raw = (abs(v) & 0x7FFF) | (0x8000 if v >= 0 else 0)
        return bytes([raw & 0xFF, (raw >> 8) & 0xFF])
    return enc(x) + enc(y) + enc(speed) + bytes([distance & 0xFF, (distance >> 8) & 0xFF])


def _frame(*targets: bytes) -> bytes:
    slots = list(targets) + [bytes(8)] * (3 - len(targets))   # pad to 3 slots
    return _HEADER + b"".join(slots) + _FOOTER


class FakeSerial:
    """Hands out `data` one .read(n) at a time; empty read == timeout."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.closed = False

    def read(self, n: int) -> bytes:
        chunk = self.data[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def rp() -> Raspberry:
    return Raspberry()


def _radar(rp: Raspberry, data: bytes) -> PiRadar:
    r = PiRadar(board=rp)
    r._ser = FakeSerial(data)          # inject the fake, skip opening a real port
    return r


def test_decodes_one_target(rp: Raspberry) -> None:
    radar = _radar(rp, _frame(_target_bytes(300, 1200, -20, 1237)))
    (t,) = radar.read()
    assert (t.x, t.y, t.speed, t.distance) == (300, 1200, -20, 1237)


def test_negative_x_is_left(rp: Raspberry) -> None:
    radar = _radar(rp, _frame(_target_bytes(-500, 800, 15, 943)))
    (t,) = radar.read()
    assert t.x == -500 and t.y == 800 and t.speed == 15


def test_multiple_targets(rp: Raspberry) -> None:
    radar = _radar(rp, _frame(
        _target_bytes(100, 500, 0, 510),
        _target_bytes(-200, 900, -30, 922),
    ))
    ts = radar.read()
    assert len(ts) == 2
    assert ts[0].x == 100 and ts[1].x == -200


def test_empty_slots_are_dropped(rp: Raspberry) -> None:
    radar = _radar(rp, _frame())               # a frame with nobody in view
    assert radar.read() == []


def test_derived_range_and_angle() -> None:
    t = RadarTarget(x=0, y=1000, speed=0, distance=1000)
    assert t.range_mm == 1000.0
    assert t.angle_deg == 0.0                   # straight ahead
    right = RadarTarget(x=1000, y=1000, speed=0, distance=1414)
    assert 44.0 < right.angle_deg < 46.0        # 45 deg to the right


def test_resyncs_past_leading_junk(rp: Raspberry) -> None:
    junk = b"\x11\x22\x33"
    radar = _radar(rp, junk + _frame(_target_bytes(10, 20, 0, 30)))
    (t,) = radar.read()
    assert (t.x, t.y) == (10, 20)


def test_bad_footer_then_a_good_frame(rp: Raspberry) -> None:
    bad = _HEADER + bytes(24) + b"\x00\x00"     # right length, wrong footer
    radar = _radar(rp, bad + _frame(_target_bytes(7, 8, 0, 9)))
    (t,) = radar.read()
    assert (t.x, t.y) == (7, 8)


def test_no_frame_raises(rp: Raspberry) -> None:
    radar = _radar(rp, b"\x00\x01\x02\x03")     # never a header
    with pytest.raises(RataError, match="no radar frame"):
        radar.read(timeout=0.1)


def test_raw_frame_returns_whole_frame(rp: Raspberry) -> None:
    frame = _frame(_target_bytes(1, 2, 3, 4))
    radar = _radar(rp, frame)
    raw = radar.raw_frame()
    assert raw.startswith(_HEADER) and raw.endswith(_FOOTER)
    assert len(raw) == 30


def test_close_releases_the_port(rp: Raspberry) -> None:
    radar = _radar(rp, _frame())
    ser = radar._ser
    radar.close()
    assert ser.closed is True
    assert radar._ser is None


def test_rejects_an_arduino_board() -> None:
    from ratapy.boards import Mega
    with pytest.raises(RataError, match="attaches to the Raspberry"):
        PiRadar(board=Mega("A"))
