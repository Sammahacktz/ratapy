"""ADXL345 accelerometer wired straight to the Raspberry Pi's I2C bus.

This is the master-attached twin of ``ratapy.devices.ADXL345`` (which sits behind
an Arduino). Same sensor, same reading API -- here the Pi is I2C master to it, so
there is no Arduino, no firmware and no wire protocol; RATA talks to the chip in
Python via smbus2::

    rp = Raspberry()
    accel = PiADXL345(board=rp)        # the Pi is the board
    accel.x, accel.y, accel.z          # g
    accel.magnitude                    # ~1.0 held still

Wiring: the ADXL345 goes on the Pi's I2C-1 pins -- SDA = GPIO2 (pin 3), SCL =
GPIO3 (pin 5) -- plus 3.3 V and GND. Enable the bus first (``rata i2c``, then
reboot), exactly as for driving Arduinos over I2C. ``address`` is 0x53 (SDO->GND,
the default) or 0x1D (SDO->VCC); ``bus`` is the /dev/i2c-N number (1 on a modern
Pi).

Named ``PiADXL345`` (the ``Pi`` prefix all master-attached devices carry) so it
never gets confused with the Arduino-side ``ADXL345``. The g-scaling is shared
between them (`AccelReadout`), so a reading means the same thing either way.
"""

from __future__ import annotations

from ..complex_devices import AccelReadout
from .base import LocalDevice

# Registers (same as the firmware side).
_POWER_CTL = 0x2D
_DATA_FORMAT = 0x31
_DATAX0 = 0x32
_MEASURE = 0x08          # POWER_CTL: leave standby, start measuring
_FULL_RES_2G = 0x08      # DATA_FORMAT: full resolution (3.9 mg/LSB), +/-2 g


def _s16(lo: int, hi: int) -> int:
    """Two little-endian bytes -> signed 16-bit (the ADXL's axis format)."""
    v = lo | (hi << 8)
    return v - 65536 if v >= 0x8000 else v


class PiADXL345(AccelReadout, LocalDevice):
    """An ADXL345 on the Raspberry Pi's own I2C bus. See the module docstring."""

    def __init__(self, address: int = 0x53, bus: int = 1,
                 board: "object | None" = None) -> None:
        if not 0x08 <= address <= 0x77:
            raise ValueError(f"I2C address {address:#04x} out of range (0x08..0x77)")
        super().__init__(board)   # type: ignore[arg-type]  # LocalDevice checks it's a Raspberry
        self.address: int = address
        self.bus_num: int = bus
        self._bus: object | None = None

    def _open(self) -> object:
        """Open the bus and put the chip in measure mode, on first use.

        Lazy on purpose: constructing the device off a real Pi (no /dev/i2c-N)
        must not fail -- only actually reading it does.
        """
        if self._bus is None:
            try:
                from smbus2 import SMBus
            except ImportError as e:  # pragma: no cover - smbus2 is a core dep
                raise RuntimeError("ADXL345 needs smbus2 (a RATA dependency)") from e
            bus = SMBus(self.bus_num)
            bus.write_byte_data(self.address, _POWER_CTL, _MEASURE)
            bus.write_byte_data(self.address, _DATA_FORMAT, _FULL_RES_2G)
            self._bus = bus
        return self._bus

    @property
    def raw(self) -> tuple[int, int, int]:
        """The three axes as raw signed counts (x, y, z). See AccelReadout for g."""
        bus = self._open()
        # read_i2c_block_data(addr, DATAX0, 6) -> [x0,x1, y0,y1, z0,z1]
        d = bus.read_i2c_block_data(self.address, _DATAX0, 6)  # type: ignore[attr-defined]
        return _s16(d[0], d[1]), _s16(d[2], d[3]), _s16(d[4], d[5])

    def _release(self) -> None:
        if self._bus is not None:
            self._bus.close()  # type: ignore[attr-defined]
            self._bus = None

    def __repr__(self) -> str:
        return f"PiADXL345(address={self.address:#04x}, bus={self.bus_num})"
