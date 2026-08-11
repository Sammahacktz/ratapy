"""I2CLink read-back behaviour: a slave that is not ready yet must not fail.

The board can only prepare its reply from loop(), so the first read after a
command can land too early (a blocking sensor update, or the ~20 ms 1-Wire
bring-up on ADD_DEVICE). These tests drive I2CLink against a fake bus that
answers "not ready" a few times, standing in for that board.
"""

from __future__ import annotations

import sys
import types

import pytest

from ratapy import protocol as p
from ratapy.link import I2CLink, parse_frame
from ratapy.protocol import RataError

# The exact bytes WireTransport::BUSY_FRAME puts on the wire (Transport.h).
BUSY_FRAME = bytes([p.START_BYTE, p.RSP_BUSY, 0x00, p.RSP_BUSY])
# What the master reads when the slave writes nothing at all: pad bytes only.
SILENCE = b"\xff" * 8


class _Msg:
    """Stand-in for smbus2.i2c_msg: a write carries data, a read receives it."""

    def __init__(self, addr: int, data: bytes = b"", length: int = 0) -> None:
        self.addr = addr
        self.data = data
        self.length = length

    def __bytes__(self) -> bytes:
        return self.data


class _i2c_msg:
    @staticmethod
    def write(addr: int, data: bytes) -> _Msg:
        return _Msg(addr, bytes(data))

    @staticmethod
    def read(addr: int, length: int) -> _Msg:
        return _Msg(addr, length=length)


class FakeBus:
    """A fake I2C slave that answers reads from a scripted list of replies.

    `replies` is consumed one read at a time; once empty, `tail` is returned for
    every further read (so "busy forever" is just tail=BUSY_FRAME).
    """

    def __init__(self, replies: list[bytes], tail: bytes = BUSY_FRAME) -> None:
        self.replies = list(replies)
        self.tail = tail
        self.writes: list[bytes] = []
        self.reads = 0
        self.closed = False

    def i2c_rdwr(self, *msgs: _Msg) -> None:
        for msg in msgs:
            if msg.length:                       # a read transaction
                self.reads += 1
                body = self.replies.pop(0) if self.replies else self.tail
                msg.data = body.ljust(msg.length, b"\xff")
            else:
                self.writes.append(msg.data)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_smbus(monkeypatch: pytest.MonkeyPatch) -> list[FakeBus]:
    """Install a fake `smbus2`; returns the list of buses I2CLink opens."""
    opened: list[FakeBus] = []
    script: list[bytes] = []

    def SMBus(bus: int) -> FakeBus:
        opened.append(FakeBus(list(script)))
        return opened[-1]

    module = types.ModuleType("smbus2")
    module.SMBus = SMBus          # type: ignore[attr-defined]
    module.i2c_msg = _i2c_msg     # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "smbus2", module)
    return opened


def link_over(fake_smbus: list[FakeBus], replies: list[bytes], **kw: float) -> I2CLink:
    """An I2CLink whose fake slave answers with `replies`, then stays busy."""
    kw.setdefault("settle", 0.0)          # keep the tests fast
    kw.setdefault("timeout", 0.05)
    link = I2CLink(bus=1, **kw)           # type: ignore[arg-type]
    bus = fake_smbus[-1]
    bus.replies = list(replies)
    return link


def test_busy_frame_matches_the_firmware_bytes() -> None:
    # Guards Transport.h's hand-built BUSY_FRAME against the checksum rule.
    assert BUSY_FRAME == p.build_frame(p.RSP_BUSY, b"")
    assert parse_frame(BUSY_FRAME).cmd == p.RSP_BUSY


def test_retries_while_the_board_reports_busy(fake_smbus: list[FakeBus]) -> None:
    ack = p.build_frame(p.RSP_ACK, b"")
    link = link_over(fake_smbus, [BUSY_FRAME, BUSY_FRAME, BUSY_FRAME, ack])
    assert link.request(0x08, p.CMD_ADD_DEVICE, b"\x01\x0a\x04").cmd == p.RSP_ACK
    assert fake_smbus[-1].reads == 4


def test_the_command_is_written_only_once_across_retries(fake_smbus: list[FakeBus]) -> None:
    # Re-reading is safe; re-writing would run the command twice on the board.
    value = p.build_frame(p.RSP_VALUE, b"\x01\x08\x60")
    link = link_over(fake_smbus, [BUSY_FRAME, BUSY_FRAME, value])
    link.request(0x08, p.CMD_READ, b"\x01")
    assert fake_smbus[-1].writes == [p.build_frame(p.CMD_READ, b"\x01")]


def test_retries_through_a_silent_slave(fake_smbus: list[FakeBus]) -> None:
    # Pre-RSP_BUSY firmware (and a truly mid-transaction slave) writes nothing,
    # so the master reads pad bytes -- the "no frame in response" report.
    value = p.build_frame(p.RSP_VALUE, b"\x01\x08\x60")
    link = link_over(fake_smbus, [SILENCE, SILENCE, value])
    resp = link.request(0x08, p.CMD_READ, b"\x01")
    assert p.i16(resp.payload, 1) == 0x0860


def test_retries_through_a_bus_error(fake_smbus: list[FakeBus]) -> None:
    ack = p.build_frame(p.RSP_ACK, b"")
    link = link_over(fake_smbus, [ack])
    bus = fake_smbus[-1]
    real = bus.i2c_rdwr
    calls = {"n": 0}

    def flaky(*msgs: _Msg) -> None:
        calls["n"] += 1
        if calls["n"] == 2:                       # the first read transaction
            raise OSError(121, "Remote I/O error")
        real(*msgs)

    bus.i2c_rdwr = flaky                          # type: ignore[method-assign]
    assert link.request(0x08, p.CMD_PING).cmd == p.RSP_ACK


def test_gives_up_with_an_actionable_error(fake_smbus: list[FakeBus]) -> None:
    link = link_over(fake_smbus, [])              # busy forever
    with pytest.raises(RataError, match=r"no reply from board 0x08 within 0.05s"):
        link.request(0x08, p.CMD_PING)


def test_a_timeout_drains_the_board(fake_smbus: list[FakeBus],
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    # A board that finishes just after we gave up still holds a buffered reply,
    # which must not reach the next command.
    link = link_over(fake_smbus, [])              # busy forever
    drained: list[int] = []
    monkeypatch.setattr(link, "_drain", drained.append)
    with pytest.raises(RataError):
        link.request(0x08, p.CMD_PING)
    assert drained == [0x08]


def test_draining_consumes_one_stale_reply(fake_smbus: list[FakeBus]) -> None:
    link = link_over(fake_smbus, [p.build_frame(p.RSP_ACK, b"")])
    bus = fake_smbus[-1]
    link._drain(0x08)
    assert bus.reads == 1
    assert bus.replies == []                       # the stale reply is gone


def test_a_drain_survives_an_absent_board(fake_smbus: list[FakeBus]) -> None:
    # The caller is already raising; a dead bus must not mask that with an OSError.
    link = link_over(fake_smbus, [])
    bus = fake_smbus[-1]

    def dead(*msgs: _Msg) -> None:
        raise OSError(121, "Remote I/O error")

    bus.i2c_rdwr = dead                            # type: ignore[method-assign]
    link._drain(0x08)


def test_rejects_an_out_of_range_address(fake_smbus: list[FakeBus]) -> None:
    link = link_over(fake_smbus, [])
    with pytest.raises(RataError, match="out of range"):
        link.request(0x80, p.CMD_PING)
    assert fake_smbus[-1].writes == []             # nothing went on the wire
