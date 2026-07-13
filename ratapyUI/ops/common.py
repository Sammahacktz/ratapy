"""Shared bits for the RATA ops: repo paths, the board table, device discovery.

Pure logic + subprocess -- no curses. Both the standalone scripts and the TUI
import from here so there is exactly one definition of "where is flash.sh" and
"which boards exist".
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# ratapy is a sibling package in the same repo; used to actually talk to boards.
from ratapy import protocol as p
from ratapy.boards import BoardInfo
from ratapy.protocol import Address, RataError

if TYPE_CHECKING:
    from ratapy.link import Link

# --- repo layout ------------------------------------------------------------

# ratapyUI/ops/common.py -> parents[2] is the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_DIR = REPO_ROOT / "firmware"
ACLI = FIRMWARE_DIR / "acli.sh"
FLASH_SH = FIRMWARE_DIR / "flash.sh"
SKETCH = FIRMWARE_DIR / "rata"
INSTALL_SH = REPO_ROOT / "install.sh"
SETUP_USB_GADGET_SH = REPO_ROOT / "scripts" / "setup-usb-gadget.sh"
SETUP_I2C_SH = REPO_ROOT / "scripts" / "setup-i2c.sh"


# --- board table (the one true copy) ----------------------------------------

@dataclass(frozen=True)
class Board:
    key: str            # cli name: mega / uno / nano
    name: str           # human name
    fqbn: str           # arduino-cli fully-qualified board name
    num_digital_pins: int   # used to recognise a board from its PING reply


BOARDS: dict[str, Board] = {
    "mega":     Board("mega",     "Mega 2560", "arduino:avr:mega",     70),
    "uno":      Board("uno",      "Uno",       "arduino:avr:uno",      20),
    "nano":     Board("nano",     "Nano",      "arduino:avr:nano",     20),
    "leonardo": Board("leonardo", "Leonardo",  "arduino:avr:leonardo", 31),
    "micro":    Board("micro",    "Micro",     "arduino:avr:micro",    31),
}


def board_from_pins(num_digital_pins: int | None) -> Board | None:
    """Best-effort recognise a connected board from what it reports on PING.

    Boards that share an MCU/pin count can't be told apart by PING alone, so this
    returns the first match -- fine for display; flash the specific one
    explicitly. Two pairs collide: Leonardo/Micro (the same 32U4 variant, 31
    pins) and Uno/Nano (the Nano is the Uno's `standard` pin map with two extra
    ADC channels, so both report 20). A Nano therefore shows up as "Uno".
    """
    if num_digital_pins is None:
        return None
    for b in BOARDS.values():
        if b.num_digital_pins == num_digital_pins:
            return b
    return None


# --- serial discovery -------------------------------------------------------

@dataclass
class Detected:
    """One probed connection -- present whether or not it answered RATA."""
    transport: str                       # "serial" or "i2c"
    address: str                         # port path, or "0x08" for i2c
    board: Board | None = None           # recognised model, if any
    info: BoardInfo | None = None        # PING reply, if it answered
    error: str | None = None             # why it did not answer, if it didn't

    @property
    def responds(self) -> bool:
        return self.info is not None

    @property
    def label(self) -> str:
        name = self.board.name if self.board else "unknown"
        return f"{self.address}  ·  {name}"


def ping_via_link(link: "Link", address: Address) -> BoardInfo:
    """PING a board straight over a Link (no Raspberry registration needed).

    Probing is read-only discovery, so we talk to the transport directly instead
    of building/registering an Arduino the way normal device code does.
    """
    resp = link.request(address, p.CMD_PING)
    if resp.cmd != p.RSP_PONG or len(resp.payload) < 2:
        raise RataError("unexpected ping response")
    pl = resp.payload
    return BoardInfo(
        version=pl[0],
        device_count=pl[1],
        max_devices=pl[2] if len(pl) > 2 else None,
        num_digital_pins=pl[3] if len(pl) > 3 else None,
    )


# --- registered-device introspection (CMD_DEVICE_INFO) ----------------------

DEV_NAMES: dict[int, str] = {
    p.DEV_DIGITAL_OUT: "DigitalOutput",
    p.DEV_DIGITAL_IN: "DigitalInput",
    p.DEV_PWM: "PWM",
    p.DEV_SERVO: "Servo",
    p.DEV_STEPPER: "Stepper",
    p.DEV_ANALOG_IN: "AnalogInput",
    p.DEV_ULTRASONIC: "Ultrasonic",
    p.DEV_DHT: "DHT",
    p.DEV_ENCODER: "RotaryEncoder",
}


@dataclass
class DeviceEntry:
    """One device a board has registered, from its CMD_DEVICE_INFO reply."""
    index: int
    dev_id: int
    dev_type: int
    params: bytes

    @property
    def name(self) -> str:
        return DEV_NAMES.get(self.dev_type, f"type 0x{self.dev_type:02X}")

    @property
    def pins(self) -> str:
        """Human description of where this device is wired, from its params."""
        pr = list(self.params)
        t = self.dev_type
        if t == p.DEV_ANALOG_IN and pr:
            return f"A{pr[0]}"
        if t == p.DEV_STEPPER and len(pr) >= 4:
            return "pins " + ",".join(str(x) for x in pr[:4])
        if t == p.DEV_ULTRASONIC and len(pr) >= 2:
            return f"trig {pr[0]} · echo {pr[1]}"
        if t == p.DEV_ENCODER and len(pr) >= 2:
            return f"clk {pr[0]} · dt {pr[1]}"
        if t == p.DEV_DHT and len(pr) >= 2:
            return f"pin {pr[0]} (DHT{pr[1]})"
        if pr:
            return f"pin {pr[0]}"
        return "-"


def enumerate_via_link(link: "Link", address: Address, limit: int = 64) -> list[DeviceEntry]:
    """List a board's registered devices by walking CMD_DEVICE_INFO indices.

    Stops at the first index the board rejects (older firmware NACKs the whole
    command, so this simply returns [] there). Needs firmware proto v3+.
    """
    out: list[DeviceEntry] = []
    for index in range(limit):
        try:
            resp = link.request(address, p.CMD_DEVICE_INFO, bytes([index]))
        except RataError:
            break
        if resp.cmd != p.RSP_DEVICE or len(resp.payload) < 4:
            break
        pl = resp.payload
        out.append(DeviceEntry(index=pl[0], dev_id=pl[1], dev_type=pl[2], params=bytes(pl[4:4 + pl[3]])))
    return out


def enumerate_serial(port: str, baud: int = 115200, timeout: float = 1.0) -> list[DeviceEntry]:
    """Open ``port`` and enumerate the devices the board currently has registered.

    Uses a normal (reset=True) open: on a CH340 board a no-reset open just holds
    the board in reset. The reset reboots it, which reloads any devices saved to
    EEPROM (``board.save_devices()``) -- so this lists the *persisted* devices.
    Devices only ever held in RAM don't survive a separate connection anyway.
    """
    from ratapy.link import SerialLink

    try:
        link = SerialLink(port, baud, timeout=timeout)
    except Exception:
        return []
    try:
        return enumerate_via_link(link, port)
    finally:
        link.close()


def discover_serial_ports() -> list[str]:
    """USB-serial device nodes that look like an Arduino (CH340 / ACM / USB)."""
    ports = set(glob.glob("/dev/ttyUSB*")) | set(glob.glob("/dev/ttyACM*"))
    return sorted(ports)


def probe_serial(port: str, baud: int = 115200, timeout: float = 1.0,
                 retries: int = 3) -> Detected:
    """Open ``port``, PING, and report what (if anything) answered.

    Retries a couple of times because opening the port resets the Arduino, and
    the first ping can beat the bootloader (the classic RATA startup race).
    """
    from ratapy.link import SerialLink

    try:
        link = SerialLink(port, baud, timeout=timeout)
    except Exception as e:                        # port busy, permission, gone
        msg = str(e)
        if "lock" in msg.lower() or "busy" in msg.lower():
            msg = "busy (in use by another program)"
        return Detected("serial", port, error=msg)
    try:
        last: Exception | None = None
        for _ in range(max(1, retries)):
            try:
                info = ping_via_link(link, port)  # address is just a label on serial
                return Detected("serial", port, board_from_pins(info.num_digital_pins), info)
            except RataError as e:
                last = e
        return Detected("serial", port, error=str(last) if last else "no response")
    finally:
        link.close()


def scan_serial() -> list[Detected]:
    """Probe every serial port and return one Detected each."""
    return [probe_serial(p) for p in discover_serial_ports()]


# --- i2c discovery (best effort; needs a wired bus) -------------------------

def scan_i2c(bus: int = 1, first: int = 0x08, last: int = 0x77) -> list[Detected]:
    """Probe the I2C bus for RATA slaves in the 0x08..0x77 range.

    Returns [] (not an error) when there is no bus -- an empty result just means
    "nothing here / no I2C on this machine".
    """
    try:
        from smbus2 import SMBus
    except Exception:
        return []
    found: list[Detected] = []
    try:
        smb = SMBus(bus)
    except Exception:
        return found
    try:
        from ratapy.link import I2CLink
        for addr in range(first, last + 1):
            try:
                smb.write_quick(addr)            # ACK check; raises if nobody home
            except Exception:
                continue
            hexa = f"0x{addr:02X}"
            link = I2CLink(bus=bus)
            try:
                info = ping_via_link(link, addr)
                found.append(Detected("i2c", hexa, board_from_pins(info.num_digital_pins), info))
            except Exception as e:
                found.append(Detected("i2c", hexa, error=str(e)))
            finally:
                link.close()
    finally:
        smb.close()
    return found
