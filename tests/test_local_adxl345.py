"""ADXL345 wired directly to the Pi (ratapy.devices.PiADXL345).

No hardware: smbus2.SMBus is replaced with a fake that records register writes
and hands back canned axis bytes, so we test the whole read path in Python.
"""

from __future__ import annotations

import pytest

from ratapy.boards import Mega
from ratapy.devices import PiADXL345
from ratapy.protocol import RataError
from ratapy.raspberry import Raspberry


class FakeSMBus:
    """Stand-in for smbus2.SMBus. `block` is what the next axis read returns."""

    def __init__(self, bus: int) -> None:
        self.bus = bus
        self.writes: list[tuple[int, int, int]] = []
        self.block: list[int] = [0, 0, 0, 0, 0, 0]
        self.closed = False

    def write_byte_data(self, addr: int, reg: int, val: int) -> None:
        self.writes.append((addr, reg, val))

    def read_i2c_block_data(self, addr: int, reg: int, n: int) -> list[int]:
        return self.block[:n]

    def close(self) -> None:
        self.closed = True


def _axes(x: int, y: int, z: int) -> list[int]:
    """Pack three signed counts as the ADXL's little-endian byte order."""
    out: list[int] = []
    for v in (x, y, z):
        u = v & 0xFFFF
        out += [u & 0xFF, (u >> 8) & 0xFF]
    return out


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMBus]:
    monkeypatch.setattr("smbus2.SMBus", FakeSMBus)
    return FakeSMBus


@pytest.fixture
def rp() -> Raspberry:
    return Raspberry()


def test_attaches_to_the_raspberry(patched: object, rp: Raspberry) -> None:
    accel = PiADXL345(board=rp)
    assert accel.board is rp


def test_rejects_an_arduino_board(patched: object) -> None:
    # A LocalDevice runs on the Pi; an Arduino is the wrong board.
    with pytest.raises(RataError, match="attaches to the Raspberry"):
        PiADXL345(board=Mega("A"))


def test_bus_is_opened_lazily_in_measure_mode(
        patched: object, rp: Raspberry) -> None:
    accel = PiADXL345(board=rp)
    assert accel._bus is None                    # nothing opened at construction
    accel.raw                                    # first read opens + configures
    bus = accel._bus
    assert isinstance(bus, FakeSMBus)
    assert (0x53, 0x2D, 0x08) in bus.writes      # POWER_CTL = measure
    assert (0x53, 0x31, 0x08) in bus.writes      # DATA_FORMAT = full-res, 2g


def test_raw_decodes_signed_little_endian(patched: object, rp: Raspberry) -> None:
    accel = PiADXL345(board=rp)
    accel.raw                                    # open
    accel._bus.block = _axes(-128, 512, -256)    # type: ignore[union-attr]
    assert accel.raw == (-128, 512, -256)


def test_scales_counts_to_g(patched: object, rp: Raspberry) -> None:
    accel = PiADXL345(board=rp)
    accel.raw
    accel._bus.block = _axes(0, 0, 256)          # type: ignore[union-attr]  256 = 1 g
    assert accel.acceleration == (0.0, 0.0, 1.0)
    assert accel.z == 1.0
    assert abs(accel.magnitude - 1.0) < 1e-9


def test_bus_number_is_passed_through(patched: object, rp: Raspberry) -> None:
    accel = PiADXL345(bus=3, board=rp)
    accel.raw
    assert accel._bus.bus == 3                   # type: ignore[union-attr]


def test_alternate_address(patched: object, rp: Raspberry) -> None:
    accel = PiADXL345(address=0x1D, board=rp)
    accel.raw
    assert all(w[0] == 0x1D for w in accel._bus.writes)   # type: ignore[union-attr]
    assert "0x1d" in repr(accel)


def test_bad_address_rejected(patched: object, rp: Raspberry) -> None:
    with pytest.raises(ValueError, match="out of range"):
        PiADXL345(address=0x03, board=rp)


def test_close_releases_the_bus(patched: object, rp: Raspberry) -> None:
    accel = PiADXL345(board=rp)
    accel.raw
    bus = accel._bus
    accel.close()
    assert bus.closed is True                    # type: ignore[union-attr]
    assert accel._bus is None


def test_raspberry_close_releases_it(patched: object, rp: Raspberry) -> None:
    # LocalDevice registers for cleanup, so rp.close() tears it down.
    accel = PiADXL345(board=rp)
    accel.raw
    bus = accel._bus
    rp.close()
    assert bus.closed is True                    # type: ignore[union-attr]


def test_shares_the_g_scaling_with_the_arduino_version() -> None:
    # Both ADXL345s derive g the same way -- one AccelReadout, so no drift.
    from ratapy.devices import ADXL345 as ArduinoADXL345
    from ratapy.devices.complex_devices import AccelReadout
    assert issubclass(PiADXL345, AccelReadout)
    assert issubclass(ArduinoADXL345, AccelReadout)
    assert PiADXL345 is not ArduinoADXL345
