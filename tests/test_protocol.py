"""Wire-protocol framing: checksum, build_frame, parse_frame round-trips."""

from __future__ import annotations

import pytest

from ratapy import protocol as p
from ratapy.link import parse_frame
from ratapy.protocol import RataError


def test_checksum_is_xor_of_cmd_len_and_payload() -> None:
    assert p.checksum(p.CMD_PING, b"") == (p.CMD_PING ^ 0)
    assert p.checksum(0x20, b"\x01\x02") == (0x20 ^ 2 ^ 0x01 ^ 0x02)


def test_build_frame_layout() -> None:
    frame = p.build_frame(p.CMD_WRITE, b"\x05\x01")
    assert frame[0] == p.START_BYTE
    assert frame[1] == p.CMD_WRITE
    assert frame[2] == 2                      # length
    assert frame[3:5] == b"\x05\x01"          # payload
    assert frame[5] == p.checksum(p.CMD_WRITE, b"\x05\x01")


def test_build_then_parse_round_trips() -> None:
    frame = p.build_frame(p.RSP_PONG, b"\x02\x00\x20\x46")
    parsed = parse_frame(frame)
    assert parsed.cmd == p.RSP_PONG
    assert parsed.payload == b"\x02\x00\x20\x46"


def test_parse_skips_leading_noise_and_trailing_pad() -> None:
    frame = p.build_frame(p.RSP_ACK, b"")
    noisy = b"\x00\xff" + frame + b"\x00\x00"   # I2C reads over-fetch
    assert parse_frame(noisy).cmd == p.RSP_ACK


def test_parse_rejects_bad_checksum() -> None:
    frame = bytearray(p.build_frame(p.RSP_VALUE, b"\x01\x02"))
    frame[-1] ^= 0xFF
    with pytest.raises(RataError, match="checksum"):
        parse_frame(bytes(frame))


def test_parse_rejects_no_start_byte() -> None:
    with pytest.raises(RataError, match="no frame"):
        parse_frame(b"\x01\x02\x03")


def test_parse_rejects_truncated_frame() -> None:
    frame = p.build_frame(p.CMD_READ, b"\x05")
    with pytest.raises(RataError, match="truncated"):
        parse_frame(frame[:-2])


def test_error_table_covers_firmware_codes() -> None:
    # every NACK code the firmware can send has a human message
    for code in range(0x01, 0x08):
        assert code in p.ERRORS
