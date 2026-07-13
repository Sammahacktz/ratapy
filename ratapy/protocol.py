"""RATA wire protocol -- kept in sync with firmware/rata/Protocol.h.

Internal module: beginners never import from here. The framing lives behind the
Host classes; devices are the only public surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# How a board is addressed on its bus: an int I2C address later, a str label on
# serial today. Every layer that routes a message is annotated with this.
Address = int | str

START_BYTE: Final = 0xAA
PROTO_VERSION: Final = 6
MAX_PAYLOAD: Final = 32

# Commands: master -> Arduino
CMD_PING = 0x01
CMD_RESET = 0x02
CMD_ADD_DEVICE = 0x10
CMD_WRITE = 0x20
CMD_READ = 0x21
CMD_STAGE = 0x22    # buffer a WRITE on the board, applied by CMD_COMMIT
CMD_COMMIT = 0x23   # apply all staged writes in one pass
CMD_DEVICE_INFO = 0x24  # introspect a registered device by index -> RSP_DEVICE
CMD_SAVE = 0x25     # persist the device registry to EEPROM (survives reset)
CMD_READ_MULTI = 0x26   # payload: [id0, id1, ...] -> RSP_VALUES (read many in one frame)

# Responses: Arduino -> master
RSP_ACK = 0x01
RSP_NACK = 0x02
RSP_PONG = 0x03
RSP_VALUE = 0x04
RSP_DEVICE = 0x05   # [index, id, type, nparams, params...] -- device config
RSP_VALUES = 0x06   # [id, nbytes, bytes...] repeated -- batch read reply

# Device types
DEV_DIGITAL_OUT = 0x01
DEV_DIGITAL_IN = 0x02
DEV_PWM = 0x03
DEV_SERVO = 0x04
DEV_STEPPER = 0x05
DEV_ANALOG_IN = 0x06
DEV_ULTRASONIC = 0x07
DEV_DHT = 0x08
DEV_ENCODER = 0x09

ERRORS: dict[int, str] = {
    0x01: "bad checksum",
    0x02: "unknown command",
    0x03: "unknown device type",
    0x04: "unknown device id",
    0x05: "bad params",
    0x06: "no space for device",
    0x07: "stage buffer full",
}


class RataError(Exception):
    """Something went wrong talking to a RATA host (NACK, timeout, bad frame)."""


@dataclass(frozen=True)
class Frame:
    cmd: int
    payload: bytes


def i16(data: bytes, offset: int = 0) -> int:
    """Decode a signed big-endian 16-bit value from the wire (the value encoding)."""
    return int.from_bytes(data[offset:offset + 2], "big", signed=True)


def checksum(cmd: int, payload: bytes) -> int:
    c = cmd ^ len(payload)
    for b in payload:
        c ^= b
    return c & 0xFF


def build_frame(cmd: int, payload: bytes = b"") -> bytes:
    return bytes([START_BYTE, cmd, len(payload)]) + payload + bytes([checksum(cmd, payload)])
