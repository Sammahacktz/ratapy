"""Shared test fixtures: a fake Link so devices can be exercised without hardware."""

from __future__ import annotations

import pytest

from ratapy import protocol as p
from ratapy.link import Link, parse_frame
from ratapy.protocol import Address, Frame
from ratapy.boards import Mega
from ratapy.raspberry import Raspberry


class MockLink(Link):
    """Records every request and answers with a plausible canned response.

    READ returns ``self.value`` (a signed int16); everything else ACKs. Lets us
    assert exactly which frames a device would put on the wire.
    """

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[Frame] = []
        self.value: int = 0
        self.values: dict[int, int] = {}     # per-device override; falls back to self.value
        self.closed = False

    def _value_for(self, dev_id: int) -> int:
        return self.values.get(dev_id, self.value)

    def _exchange(self, address: Address, frame: bytes) -> Frame:
        req = parse_frame(frame)
        self.sent.append(req)
        if req.cmd == p.CMD_READ:
            dev_id = req.payload[0]
            body = self._value_for(dev_id).to_bytes(2, "big", signed=True)
            return Frame(p.RSP_VALUE, bytes([dev_id]) + body)
        if req.cmd == p.CMD_READ_MULTI:
            body = bytearray()
            for dev_id in req.payload:                # [id, nbytes, bytes...] per device
                vb = self._value_for(dev_id).to_bytes(2, "big", signed=True)
                body += bytes([dev_id, len(vb)]) + vb
            return Frame(p.RSP_VALUES, bytes(body))
        if req.cmd == p.CMD_PING:
            return Frame(p.RSP_PONG, bytes([p.PROTO_VERSION, 0, 32, 70]))
        return Frame(p.RSP_ACK, b"")

    def close(self) -> None:
        self.closed = True

    # --- test helpers ---
    def writes(self) -> list[Frame]:
        return [f for f in self.sent if f.cmd == p.CMD_WRITE]

    def last_write_payload(self) -> bytes:
        # a WRITE frame's payload is [device_id, data...]; return just the data
        return self.writes()[-1].payload[1:]


@pytest.fixture
def link() -> MockLink:
    return MockLink()


@pytest.fixture
def board(link: MockLink) -> Mega:
    """A Mega registered on a fresh Raspberry through the mock link (no verify)."""
    rp = Raspberry(link=link)
    b = Mega("A", link=link)
    rp.register_arduino(b, verify=False)
    return b
