"""Links -- framed transports from the master to boards.

`Link` is the abstract transport: `request()` builds a command frame, hands it to
the transport-specific `_exchange()`, and turns a NACK reply into a `RataError`.
Two concrete transports, chosen per board:

- `SerialLink` -- one Arduino over USB serial (one cable per board).
- `I2CLink`    -- an I2C bus shared by many Arduinos, each at its own address.

A single `Raspberry` can use both at once: each `Arduino` is created with the
link it lives on (see board.py).
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import cast

import serial

from . import protocol as p
from .protocol import Address, Frame, RataError, build_frame


class Link(ABC):
    def __init__(self) -> None:
        # One exchange at a time. A request is write-then-read, so two threads
        # sending at once would interleave their bytes on the wire and both
        # would read the other's reply. Background senders are real: a device's
        # sleep() runs its later commands on the scheduler thread, and Gamepad
        # polls its inputs on another. Subclasses MUST call super().__init__().
        self._io_lock = threading.RLock()

    def request(self, address: Address, cmd: int, payload: bytes = b"") -> Frame:
        """Send a command to `address` and return the (non-NACK) response frame."""
        with self._io_lock:
            resp = self._exchange(address, build_frame(cmd, payload))
        if resp.cmd == p.RSP_NACK:
            code = resp.payload[0] if resp.payload else 0
            raise RataError(f"NACK: {p.ERRORS.get(code, f'error 0x{code:02x}')}")
        return resp

    @abstractmethod
    def _exchange(self, address: Address, frame: bytes) -> Frame:
        """Transmit a complete command frame, return the parsed response frame."""

    @abstractmethod
    def close(self) -> None: ...


def parse_frame(buf: bytes) -> Frame:
    """Parse (and checksum-verify) one frame out of a raw byte buffer.

    Used where a whole response arrives at once (I2C block read). Skips anything
    before the START byte, so trailing pad bytes from an over-long read are fine.
    """
    start = buf.find(p.START_BYTE)
    if start < 0:
        raise RataError("no frame in response")
    if len(buf) < start + 4:
        raise RataError("truncated response frame")
    cmd = buf[start + 1]
    length = buf[start + 2]
    end = start + 3 + length
    if len(buf) < end + 1:
        raise RataError("truncated response frame")
    payload = buf[start + 3:end]
    if buf[end] != p.checksum(cmd, payload):
        raise RataError("bad checksum on response")
    return Frame(cmd, payload)


class SerialLink(Link):
    """One Arduino over USB serial. `address` is ignored (a single board)."""

    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 115200, timeout: float = 1.0,
                 reset: bool = True, exclusive: bool = True) -> None:
        super().__init__()
        # exclusive=True takes an OS lock on the port, so a second opener (another
        # script, or the ratapyUI scan) fails cleanly with "busy". 
        # Two processes on one port corrupt each other's
        # framing (and one would reset the board the other is driving).
        try:
            if reset:
                # Opening toggles DTR and resets most Arduinos; wait for boot.
                self._ser: serial.Serial = serial.Serial(
                    port, baud, timeout=timeout, exclusive=exclusive)
                time.sleep(2.0)
            else:
                # Open WITHOUT pulsing DTR, so an auto-reset board keeps running
                # (and keeps its registered devices). Used for read-only
                # discovery, where resetting the user's board would be rude.
                ser = serial.Serial()
                ser.port = port
                ser.baudrate = baud
                ser.timeout = timeout
                ser.exclusive = exclusive
                ser.dtr = False
                ser.rts = False
                ser.open()
                time.sleep(0.2)
                self._ser = ser
        except serial.SerialException as e:
            # Most often: the port is already open by another program.
            raise RataError(f"could not open {port}: {e}") from e
        self._ser.reset_input_buffer()

    def _read(self, n: int) -> bytes:
        # pyserial is untyped; read() returns Any, so pin it to bytes explicitly.
        return cast(bytes, self._ser.read(n))

    def _exchange(self, address: Address, frame: bytes) -> Frame:
        self._ser.write(frame)
        return self._read_frame()

    def _read_frame(self) -> Frame:
        # Resync on START, then read cmd / len / payload / checksum from the stream.
        while True:
            b = self._read(1)
            if not b:
                raise RataError("timeout waiting for response")
            if b[0] == p.START_BYTE:
                break
        header = self._read(2)
        if len(header) < 2:
            raise RataError("timeout reading frame header")
        cmd, length = header[0], header[1]
        payload = self._read(length) if length else b""
        chk = self._read(1)
        if len(payload) < length or len(chk) < 1:
            raise RataError("timeout reading frame body")
        if chk[0] != p.checksum(cmd, payload):
            raise RataError("bad checksum on response")
        return Frame(cmd, payload)

    def close(self) -> None:
        self._ser.close()


class I2CLink(Link):
    """An I2C bus shared by many Arduinos. `address` is each board's 7-bit slave
    address (0x08..0x77). Share ONE I2CLink across all boards on the same bus.

    Each request is a write transaction (the command) followed by a read
    transaction (the reply the slave prepared for onRequest). Frames must fit the
    AVR I2C buffer (32 bytes), so keep payloads small.

    The slave can only prepare that reply from its loop(), so it may not be ready
    when the first read lands: a device whose update() blocks for milliseconds
    (a DS18B20 reading its scratchpad, an ultrasonic waiting for an echo) delays
    the whole loop, and bringing such a sensor up on ADD_DEVICE is slower still.
    A fixed settle would therefore be a race, so the read is RETRIED until the
    board answers or `timeout` runs out. The firmware replies RSP_BUSY while it
    has nothing ready, which is what makes this cheap: only the command is
    written once, and re-reading a not-ready board is free of side effects.

    Needs the `smbus2` package and a real I2C bus (e.g. /dev/i2c-1 on a Pi).
    """

    #: Cap on the retry backoff -- reads stay frequent enough to catch a reply
    #: as soon as a slow update() finishes.
    _MAX_RETRY_DELAY = 0.01

    def __init__(self, bus: int = 1, *, response_size: int | None = None,
                 settle: float = 0.002, timeout: float = 1.0) -> None:
        super().__init__()
        try:
            from smbus2 import SMBus, i2c_msg
        except ImportError as e:  # pragma: no cover - depends on the target
            raise RataError("I2C support requires smbus2 -- run `uv add smbus2`") from e
        self._i2c_msg = i2c_msg
        self._bus = SMBus(bus)
        # How many bytes to read back; a full frame is START+cmd+len+payload+chk.
        self._response_size = response_size if response_size is not None else 3 + p.MAX_PAYLOAD + 1
        self._settle = settle       # seconds to wait before the first read-back
        self._timeout = timeout     # give up on a silent/busy board after this

    def _read_reply(self, addr: int) -> Frame:
        """One read transaction. Raises RataError if the reply is not usable yet."""
        read = self._i2c_msg.read(addr, self._response_size)
        try:
            self._bus.i2c_rdwr(read)
        except OSError as e:
            # Nobody acknowledged (unplugged board, wrong address), or the bus
            # glitched. Both are worth another try inside the timeout.
            raise RataError(f"I2C read from {addr:#04x} failed: {e}") from e
        resp = parse_frame(bytes(read))
        if resp.cmd == p.RSP_BUSY:
            raise RataError("board busy: reply not ready yet")
        return resp

    def _exchange(self, address: Address, frame: bytes) -> Frame:
        addr = int(address)
        if not 0x08 <= addr <= 0x77:
            raise RataError(f"I2C address {addr:#04x} out of range (0x08..0x77)")
        self._bus.i2c_rdwr(self._i2c_msg.write(addr, frame)) # send command
        deadline = time.monotonic() + self._timeout
        delay = self._settle
        while True:
            if delay:
                time.sleep(delay) # let the slave prepare
            try:
                return self._read_reply(addr)
            except RataError as e:
                if time.monotonic() >= deadline:
                    # Drain one late reply, so a board that finishes after we gave
                    # up cannot hand its stale answer to the *next* command.
                    self._drain(addr)
                    raise RataError(
                        f"no reply from board {addr:#04x} within {self._timeout:g}s "
                        f"({e}) -- check wiring, the address, and that the board "
                        "runs the I2C firmware build"
                    ) from e
            delay = min(delay * 2, self._MAX_RETRY_DELAY) if delay else self._MAX_RETRY_DELAY

    def _drain(self, addr: int) -> None:
        try:
            self._bus.i2c_rdwr(self._i2c_msg.read(addr, self._response_size))
        except OSError:
            pass                    # nothing there to drain; the caller is already failing

    def close(self) -> None:
        self._bus.close()
