"""Arduino boards -- one class per model.

`Arduino` is the base. Each real board (`Uno`, `Nano`, `Mega`, ...) is a subclass
that fills in a *profile*: how many pins it has, which are PWM/analog capable, and
how many devices its RAM can hold. The profile lets the framework validate your
wiring in Python -- with a clear error -- before a single byte goes to the board.

    ad = Mega("A")               # serial (uses the Raspberry's default link)
    ad = Uno(0x08, link=i2c)     # or on an I2C bus, at a 7-bit address
    rp.register_arduino(ad)      # also verifies the firmware matches this model

The transport is chosen per board via `link=`; a board with no link falls back
to the Raspberry's default link (from its `port=`). Prefer the specific model;
the bare `Arduino` base still works as a permissive "generic board".
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

from . import protocol as p
from .protocol import Address, RataError

if TYPE_CHECKING:
    from .devices import Device
    from .link import Link
    from .raspberry import Raspberry

@dataclass
class BoardInfo:
    """What a board reports about itself in response to PING."""
    version: int
    device_count: int
    max_devices: int | None = None
    num_digital_pins: int | None = None


class AnalogPin(Enum):
    """An analog pin *label* (A0, A1, ...) -- the marking on the board, NOT a
    pin number.

    Which pin number a label means is board-specific (A0 is 14 on an Uno, 54 on
    a Mega), so a member carries only the label and is resolved against the
    board the device is actually on -- see ``Arduino.resolve_pin``. That is why
    these are labels rather than numbers: a number would be silently wrong if it
    reached a different model, while a label is correct on every board that has
    it and a clear error on one that doesn't. One enum serves every board::

        LED(pin=AnalogPin.A0, board=mega)   # -> pin 54
        LED(pin=AnalogPin.A0, board=uno)    # -> pin 14

    The value is the analog channel index, so AnalogInput takes them too:
    ``Potentiometer(channel=AnalogPin.A2)``.
    """
    A0 = 0
    A1 = 1
    A2 = 2
    A3 = 3
    A4 = 4
    A5 = 5
    A6 = 6
    A7 = 7
    A8 = 8
    A9 = 9
    A10 = 10
    A11 = 11
    A12 = 12
    A13 = 13
    A14 = 14
    A15 = 15


# What a device accepts for a pin: a number (13) or a label (AnalogPin.A1).
PinLike = int | AnalogPin


def _as_label(pin: PinLike) -> AnalogPin:
    """The label for `pin`. Callers handle plain numbers before this.

    Only exists to turn the "neither" case into a sentence: mypy already rejects
    it, but a REPL or an untyped project would otherwise hit an AttributeError
    from deep inside the resolve.
    """
    if isinstance(pin, AnalogPin):
        return pin
    raise TypeError(
        f"{pin!r} is not a pin: use a number (13) or a label (AnalogPin.A0)"
    )


class Arduino:
    MODEL: ClassVar[str] = "generic"
    NUM_DIGITAL_PINS: ClassVar[int] = 0            # 0 == unknown -> skip pin validation
    NUM_ANALOG_INPUTS: ClassVar[int] = 0           # analog channels A0.. (0 == unknown)
    PWM_PINS: ClassVar[frozenset[int]] = frozenset()
    ANALOG_PINS: ClassVar[frozenset[int]] = frozenset()
    ANALOG_PIN_BASE: ClassVar[int] = 0             # pin number of A0 (0 == unknown)
    MAX_DEVICES: int = 8

    def __init__(self, address: Address, link: "Link | None" = None) -> None:
        # address: a label on serial (single board); the 7-bit slave address on I2C.
        # link: this board's transport, or None to use the Raspberry's default.
        self.address: Address = address
        self._link: Link | None = link
        self._rp: Raspberry | None = None
        self._next_id: int = 0
        self._devices: dict[int, Device] = {}

    def _has_label(self, label: AnalogPin) -> None:
        """Raise ValueError if this board has no pin with that label."""
        if self.NUM_ANALOG_INPUTS and label.value >= self.NUM_ANALOG_INPUTS:
            last = self.NUM_ANALOG_INPUTS - 1
            raise ValueError(
                f"{self.MODEL} has no {label.name} (it has A0..A{last})"
            )

    def resolve_pin(self, pin: PinLike) -> int:
        """Turn a pin number or an analog label into this board's pin number.

            uno.resolve_pin(13)             -> 13   (numbers pass through)
            uno.resolve_pin(AnalogPin.A1)   -> 15   (A0 is pin 14 on an Uno)
            mega.resolve_pin(AnalogPin.A1)  -> 55   (A0 is pin 54 on a Mega)

        Use this for a pin you drive or read digitally. Analog *reads* address a
        channel instead -- see ``resolve_channel``.
        """
        if isinstance(pin, int):
            return pin                            # already a pin number
        label = _as_label(pin)
        self._has_label(label)
        if not self.ANALOG_PIN_BASE:
            raise ValueError(
                f"{self.MODEL} does not know where its analog pins start, so "
                f"{label.name} cannot be resolved -- pass the pin number instead"
            )
        num = self.ANALOG_PIN_BASE + label.value
        # A pin number past the digital range is analog-only silicon (the Nano's
        # A6/A7): real for analogRead, but it has no port register, so it can
        # never be a digital pin. Say so here -- "no pin 20" would be baffling
        # to someone who asked for A6.
        if self.NUM_DIGITAL_PINS and num >= self.NUM_DIGITAL_PINS:
            raise ValueError(
                f"{label.name} is analog-only on {self.MODEL} (it has no digital "
                f"pin number) -- read it with AnalogInput(channel={label.value})"
            )
        return num

    def resolve_channel(self, channel: PinLike) -> int:
        """Turn an analog channel number or label into a channel index.

            uno.resolve_channel(1)             -> 1
            uno.resolve_channel(AnalogPin.A1)  -> 1   (A1 is channel 1 anywhere)

        Channels are what analog reads use, and unlike pin numbers they match the
        label on every board -- A1 is channel 1 on an Uno and on a Mega alike.
        So this only converts; whether the board *has* that channel is
        AnalogInput's to check (it already reports the range).
        """
        if isinstance(channel, int):
            return channel
        return _as_label(channel).value

    def check_pin(self, pin: int, *, pwm: bool = False, analog: bool = False) -> None:
        """Raise ValueError if `pin` is not usable on this board."""
        if self.NUM_DIGITAL_PINS and not (0 <= pin <= self.NUM_DIGITAL_PINS - 1):
            raise ValueError(
                f"{self.MODEL} has no pin {pin} (valid: 0..{self.NUM_DIGITAL_PINS - 1})"
            )
        if pwm and self.PWM_PINS and pin not in self.PWM_PINS:
            raise ValueError(
                f"pin {pin} is not PWM-capable on {self.MODEL} "
                f"(PWM pins: {sorted(self.PWM_PINS)})"
            )
        if analog and self.ANALOG_PINS and pin not in self.ANALOG_PINS:
            raise ValueError(
                f"pin {pin} is not an analog input on {self.MODEL} "
                f"(analog pins: {sorted(self.ANALOG_PINS)})"
            )

    # --- registration with a Raspberry ------------------------------------

    def _attach(self, rp: "Raspberry") -> None:
        self._rp = rp
        if self._link is None:                       # inherit the Raspberry's default
            self._link = rp._default_link
        if self._link is None:
            raise RataError(
                f"{self!r} has no transport -- pass link=... "
                "or give the Raspberry a port="
            )

    def _require_link(self) -> "Link":
        if self._rp is None or self._link is None:
            raise RataError(
                f"{self!r} is not registered -- call rp.register_arduino(it) before adding devices"
            )
        return self._link

    def verify(self) -> BoardInfo:
        """Ping the board and warn if the firmware doesn't match this model."""
        info = self.ping()
        if info.version != p.PROTO_VERSION:
            warnings.warn(
                f"{self!r}: firmware speaks protocol v{info.version}, ratapy expects "
                f"v{p.PROTO_VERSION} -- re-flash firmware/rata",
                stacklevel=2,
            )
        if (self.NUM_DIGITAL_PINS and info.num_digital_pins
                and info.num_digital_pins != self.NUM_DIGITAL_PINS):
            warnings.warn(
                f"{self!r}: firmware reports {info.num_digital_pins} digital pins, "
                f"but {self.MODEL} expects {self.NUM_DIGITAL_PINS} -- wrong board or FQBN?",
                stacklevel=2,
            )
        if info.max_devices:
            # Trust the firmware's real cap if it is tighter than our profile.
            self.MAX_DEVICES = min(self.MAX_DEVICES, info.max_devices)
        return info

    # --- device plumbing (used by Device, not by users) -------------------

    def _register(self, device: "Device", dev_type: int, params: bytes) -> int:
        link = self._require_link()
        if len(self._devices) >= self.MAX_DEVICES:
            raise RataError(
                f"{self!r} is full: {self.MODEL} supports at most {self.MAX_DEVICES} devices"
            )
        dev_id = self._next_id
        link.request(self.address, p.CMD_ADD_DEVICE, bytes([dev_id, dev_type]) + params)
        self._devices[dev_id] = device
        self._next_id += 1
        return dev_id

    def _write(self, dev_id: int, data: bytes) -> None:
        self._require_link().request(self.address, p.CMD_WRITE, bytes([dev_id]) + data)

    def _stage(self, dev_id: int, data: bytes) -> None:
        """Buffer a write on the board; nothing happens until _commit()."""
        self._require_link().request(self.address, p.CMD_STAGE, bytes([dev_id]) + data)

    def _commit(self) -> None:
        """Apply every staged write in one firmware pass (see ParallelExecutor)."""
        self._require_link().request(self.address, p.CMD_COMMIT)

    def _read(self, dev_id: int) -> bytes:
        """Return a device's raw value bytes (everything after the id)."""
        resp = self._require_link().request(self.address, p.CMD_READ, bytes([dev_id]))
        if resp.cmd != p.RSP_VALUE or len(resp.payload) < 1:
            raise RataError("unexpected read response")
        return resp.payload[1:]

    def _read_int(self, dev_id: int) -> int:
        """A single device's value as a signed int16 (what _recv parses)."""
        data = self._read(dev_id)
        return p.i16(data) if len(data) >= 2 else (data[0] if data else 0)

    # Even 8-byte values (2 header + 8 each) keep a chunk's reply within MAX_PAYLOAD.
    _READ_MULTI_CHUNK: ClassVar[int] = 8

    def read_many(self, ids: list[int]) -> dict[int, int]:
        """Read several devices' values in one round-trip -> ``{id: int16}``.

        Sends one ``CMD_READ_MULTI`` per chunk instead of a ``CMD_READ`` per
        device, so polling N inputs costs ~1 frame rather than N (used by the HID
        gamepad loop). Needs firmware proto v6+.
        """
        link = self._require_link()
        out: dict[int, int] = {}
        for start in range(0, len(ids), self._READ_MULTI_CHUNK):
            chunk = ids[start:start + self._READ_MULTI_CHUNK]
            resp = link.request(self.address, p.CMD_READ_MULTI, bytes(chunk))
            if resp.cmd != p.RSP_VALUES:
                raise RataError("unexpected read-multi response")
            pl = resp.payload
            i = 0
            while i + 2 <= len(pl):                  # [id, nbytes, bytes...]
                dev_id, n = pl[i], pl[i + 1]
                out[dev_id] = p.i16(pl[i + 2:]) if n >= 2 else (pl[i + 2] if n else 0)
                i += 2 + n
            for dev_id in chunk:                     # reply truncated -> read the rest singly
                if dev_id not in out:
                    out[dev_id] = self._read_int(dev_id)
        return out

    def ping(self) -> BoardInfo:
        """Return what the board reports about itself (see BoardInfo)."""
        resp = self._require_link().request(self.address, p.CMD_PING)
        if resp.cmd != p.RSP_PONG or len(resp.payload) < 2:
            raise RataError("unexpected ping response")
        pl = resp.payload
        return BoardInfo(
            version=pl[0],
            device_count=pl[1],
            max_devices=pl[2] if len(pl) > 2 else None,
            num_digital_pins=pl[3] if len(pl) > 3 else None,
        )

    def reset(self) -> None:
        """Drop every device on this board and restart id allocation."""
        self._require_link().request(self.address, p.CMD_RESET)
        self._devices.clear()
        self._next_id = 0

    def save_devices(self) -> None:
        """Persist this board's current devices to its EEPROM.

        After this the devices survive a power-cycle or reset: on boot the board
        re-creates them, so your setup is still there after the script ends --
        and tools like the control panel can list what's wired up on a board
        nobody is driving. Call it once after configuring your devices (it writes
        EEPROM, which has a finite ~100k-cycle life, so don't call it in a loop).

        To forget the saved set later, `reset()` then `save_devices()` again
        (that persists an empty registry).
        """
        self._require_link().request(self.address, p.CMD_SAVE)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.address!r})"


class Uno(Arduino):
    """Arduino Uno (ATmega328P). Digital 0-13, analog A0-A5 (pins 14-19)."""
    MODEL = "uno"
    NUM_DIGITAL_PINS = 20
    NUM_ANALOG_INPUTS = 6                     # A0-A5
    PWM_PINS = frozenset({3, 5, 6, 9, 10, 11})
    ANALOG_PINS = frozenset(range(14, 20))   # A0-A5
    ANALOG_PIN_BASE = 14                     # A0 == pin 14
    MAX_DEVICES = 12


class Nano(Uno):
    """Arduino Nano (ATmega328P). Like the Uno plus analog-only A6/A7.

    Same 20 digital pins as the Uno: the core's `eightanaloginputs` variant is
    the Uno's `standard` variant with only NUM_ANALOG_INPUTS overridden. A6/A7
    are ADC-only (no port register), so they are analog *channels* 6-7 and never
    digital pins -- reach them with AnalogInput(channel=6), not by pin number.
    """
    MODEL = "nano"
    NUM_DIGITAL_PINS = 20
    NUM_ANALOG_INPUTS = 8                     # A0-A7
    ANALOG_PINS = frozenset(range(14, 20))   # A0-A5 (A6/A7 have no pin number)


class Mega(Arduino):
    """Arduino Mega 2560. Digital 0-69, analog A0-A15 (pins 54-69)."""
    MODEL = "mega"
    NUM_DIGITAL_PINS = 70
    NUM_ANALOG_INPUTS = 16                    # A0-A15
    ANALOG_PIN_BASE = 54                      # A0 == pin 54
    PWM_PINS = frozenset(range(2, 14)) | {44, 45, 46}
    ANALOG_PINS = frozenset(range(54, 70))   # A0-A15
    MAX_DEVICES = 32


class Leonardo(Arduino):
    """Arduino Leonardo (ATmega32U4). Digital 0-30, analog A0-A11.

    A native-USB board: the sketch's serial link *is* the USB port, so it
    re-enumerates on upload/reset and its /dev path can change between resets.
    """
    MODEL = "leonardo"
    NUM_DIGITAL_PINS = 31
    NUM_ANALOG_INPUTS = 12                    # A0-A11
    ANALOG_PIN_BASE = 18                      # A0 == pin 18
    PWM_PINS = frozenset({3, 5, 6, 9, 10, 11, 13})
    ANALOG_PINS = frozenset(range(18, 30))   # A0-A11 -> digital 18..29
    MAX_DEVICES = 12                          # 2.5 KB SRAM (firmware caps at 12)


class Micro(Leonardo):
    """Arduino Micro (ATmega32U4). Electrically the Leonardo -- same pin map."""
    MODEL = "micro"
