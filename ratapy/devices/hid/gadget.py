"""The Pi's USB gadget -- one composite device shared by HID + storage.

On Linux a board can *become* a USB peripheral through the kernel's "gadget"
framework: you describe a device under ConfigFS (`/sys/kernel/config/usb_gadget`)
out of *functions* (an HID gamepad, a mass-storage drive), link them into a
config, and bind the whole thing to the USB Device Controller (UDC). Once bound,
the HID function shows up as `/dev/hidg0` and every report you write there is
delivered to the host.

`UsbGadget` is the single object that owns that tree for a Raspberry. `Gamepad`
registers an HID function on it and `Storage` an optional mass-storage function;
the first `activate()` composes whatever is registered and binds it.

Two backends sit behind the same interface:

- `RealGadgetBackend` does the actual ConfigFS + `/dev/hidgN` I/O (needs a Pi with
  USB-OTG, `libcomposite`, and root).
- `SimulatedGadgetBackend` logs what it *would* do and swallows the reports, so a
  script (and the test-suite) runs on any machine. It is selected automatically
  when the host cannot be a gadget -- unless the Raspberry was created with
  ``usb_strict=True``, in which case the missing capability is an error.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ...protocol import RataError

log = logging.getLogger("ratapy.hid")

# ConfigFS locations + identity of the gadget we create.
CONFIGFS = Path("/sys/kernel/config/usb_gadget")
GADGET_NAME = "rata"
UDC_DIR = Path("/sys/class/udc")
ID_VENDOR = "0x1d6b"        # Linux Foundation
ID_PRODUCT = "0x0104"       # Multifunction Composite Gadget
HID_FUNCTION = "hid.usb0"
MSC_FUNCTION = "mass_storage.usb0"


@dataclass(frozen=True)
class Identity:
    """The USB strings the host shows for the device.

    `name` is the product string -- what appears in the host's game-controller /
    device list. `manufacturer` and `serial` round out the identity.
    """
    name: str = "RATA Gamepad"
    manufacturer: str = "RATA"
    serial: str = "0001"


def gadget_incapable_reason() -> str | None:
    """Why this machine can't be a USB gadget, or ``None`` if it can.

    Checks the three things ConfigFS gadget mode needs: the `usb_gadget` ConfigFS
    dir (i.e. `libcomposite` loaded), a UDC to bind to (i.e. USB-OTG enabled), and
    root (ConfigFS writes are privileged).
    """
    if not CONFIGFS.parent.is_dir():
        return "ConfigFS not mounted at /sys/kernel/config"
    if not CONFIGFS.is_dir():
        return "libcomposite not loaded (no /sys/kernel/config/usb_gadget)"
    if not UDC_DIR.is_dir() or not any(UDC_DIR.iterdir()):
        return "no USB Device Controller in /sys/class/udc -- is dwc2/OTG enabled?"
    if os.geteuid() != 0:
        return "USB gadget setup needs root"
    return None


class GadgetBackend(ABC):
    """The operations `UsbGadget` performs, abstracted over real vs simulated."""

    @abstractmethod
    def compose(self, identity: Identity, hid_desc: bytes | None,
                hid_report_len: int, msc_image: str | None) -> None:
        """(Re)create the gadget tree with the given identity + functions and bind it."""

    @abstractmethod
    def hid_write(self, report: bytes) -> None:
        """Send one HID report to the host."""

    @abstractmethod
    def teardown(self) -> None:
        """Unbind and remove the gadget tree; release any open handles."""

    @property
    @abstractmethod
    def simulated(self) -> bool: ...


class SimulatedGadgetBackend(GadgetBackend):
    """A no-hardware stand-in: logs actions and keeps the last report for tests."""

    def __init__(self) -> None:
        self.last_report: bytes | None = None
        self.report_count: int = 0
        self.composed: bool = False
        self.storage_shown: bool = False
        self.identity: Identity = Identity()
        log.warning(
            "USB gadget running in SIMULATED mode -- no real device is presented "
            "to a host (create the Raspberry with usb_strict=True to make this an error)."
        )

    def compose(self, identity: Identity, hid_desc: bytes | None,
                hid_report_len: int, msc_image: str | None) -> None:
        self.composed = True
        self.storage_shown = msc_image is not None
        self.identity = identity
        log.info("gadget compose: name=%r hid=%s (report_len=%d) storage=%s",
                 identity.name, hid_desc is not None, hid_report_len,
                 msc_image if msc_image else "off")

    def hid_write(self, report: bytes) -> None:
        self.last_report = report
        self.report_count += 1
        log.debug("gadget hid report #%d: %s", self.report_count, report.hex())

    def teardown(self) -> None:
        self.composed = False
        log.info("gadget teardown (simulated)")

    @property
    def simulated(self) -> bool:
        return True


class RealGadgetBackend(GadgetBackend):
    """Drives the real ConfigFS gadget and writes reports to `/dev/hidgN`."""

    def __init__(self) -> None:
        self._root = CONFIGFS / GADGET_NAME
        self._fd: int | None = None

    @staticmethod
    def _write(path: Path, data: str | bytes) -> None:
        mode = "wb" if isinstance(data, bytes) else "w"
        with open(path, mode) as f:
            f.write(data)

    def _mkdir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def compose(self, identity: Identity, hid_desc: bytes | None, hid_report_len: int,
                msc_image: str | None) -> None:
        self.teardown()                              # idempotent: rebuild from scratch
        g = self._root
        self._mkdir(g)
        self._write(g / "idVendor", ID_VENDOR)
        self._write(g / "idProduct", ID_PRODUCT)
        self._write(g / "bcdDevice", "0x0100")
        self._write(g / "bcdUSB", "0x0200")
        strings = g / "strings" / "0x409"
        self._mkdir(strings)
        self._write(strings / "manufacturer", identity.manufacturer)
        self._write(strings / "product", identity.name)
        self._write(strings / "serialnumber", identity.serial)

        config = g / "configs" / "c.1"
        self._mkdir(config / "strings" / "0x409")
        self._write(config / "strings" / "0x409" / "configuration", "RATA")
        self._write(config / "MaxPower", "250")

        if hid_desc is not None:
            fn = g / "functions" / HID_FUNCTION
            self._mkdir(fn)
            self._write(fn / "protocol", "0")
            self._write(fn / "subclass", "0")
            self._write(fn / "report_length", str(hid_report_len))
            self._write(fn / "report_desc", hid_desc)
            self._link(fn, config / HID_FUNCTION)

        if msc_image is not None:
            fn = g / "functions" / MSC_FUNCTION
            self._mkdir(fn)
            self._write(fn / "stall", "1")
            self._write(fn / "lun.0" / "removable", "1")
            self._write(fn / "lun.0" / "file", msc_image)
            self._link(fn, config / MSC_FUNCTION)

        # Bind to the first available UDC
        udc = next(iter(sorted(p.name for p in UDC_DIR.iterdir())))
        self._write(g / "UDC", udc)

        if hid_desc is not None:
            self._open_hidg()

    def _link(self, target: Path, link: Path) -> None:
        if not link.exists():
            link.symlink_to(target)

    def _open_hidg(self) -> None:
        # With a single HID function the kernel creates /dev/hidg0.
        self._fd = os.open("/dev/hidg0", os.O_WRONLY)

    def hid_write(self, report: bytes) -> None:
        if self._fd is None:
            raise RataError("HID device not open -- gadget not activated")
        os.write(self._fd, report)

    def teardown(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
        g = self._root
        if not g.exists():
            return
        # Reverse of compose: unbind, drop config links, remove dirs.
        try:
            self._write(g / "UDC", "\n")
        except OSError:
            pass
        config = g / "configs" / "c.1"
        for fn in (HID_FUNCTION, MSC_FUNCTION):
            link = config / fn
            if link.is_symlink() or link.exists():
                link.unlink()
        self._rmdir(config / "strings" / "0x409")
        self._rmdir(config)
        for fn in (HID_FUNCTION, MSC_FUNCTION):
            self._rmdir(g / "functions" / fn)
        self._rmdir(g / "strings" / "0x409")
        self._rmdir(g)

    @staticmethod
    def _rmdir(path: Path) -> None:
        try:
            path.rmdir()
        except OSError:
            pass

    @property
    def simulated(self) -> bool:
        return False


class UsbGadget:
    """The composite USB gadget a Raspberry presents (HID gamepad + storage).

    Created lazily by a `Raspberry` when ``usb_device=True``. `Gamepad` and
    `Storage` register their functions, then `activate()` composes and binds.
    """

    def __init__(self, strict: bool = False) -> None:
        self._strict = strict
        self._backend: GadgetBackend | None = None
        self._hid_desc: bytes | None = None
        self._hid_report_len: int = 0
        self._msc_image: str | None = None
        self._active: bool = False
        self._identity: Identity = Identity()

    def request_hid(self, report_desc: bytes, report_length: int, identity: Identity) -> None:
        """Declare the gamepad's HID function (its report descriptor + length)."""
        self._hid_desc = report_desc
        self._hid_report_len = report_length
        self._identity = identity
        if self._active:
            self._compose()

    def set_storage_image(self, image: str | None) -> None:
        """Show (image path) or hide (None) the mass-storage function."""
        self._msc_image = image
        if self._active:
            self._compose()

    def _ensure_backend(self) -> GadgetBackend:
        if self._backend is None:
            reason = gadget_incapable_reason()
            if reason is not None and self._strict:
                raise RataError(f"USB gadget unavailable: {reason}")
            self._backend = SimulatedGadgetBackend() if reason else RealGadgetBackend()
        return self._backend

    def _compose(self) -> None:
        """(Re)compose the gadget tree from the current identity + functions."""
        self._ensure_backend().compose(
            self._identity, self._hid_desc, self._hid_report_len, self._msc_image)
        self._active = True

    def activate(self) -> None:
        """Compose the registered functions and bind. Idempotent."""
        if not self._active:
            self._compose()

    def hid_write(self, report: bytes) -> None:
        self.activate()
        self._ensure_backend().hid_write(report)

    def teardown(self) -> None:
        if self._backend is not None:
            self._backend.teardown()
        self._active = False

    @property
    def simulated(self) -> bool:
        """True if the (selected) backend is the no-hardware stand-in."""
        return self._ensure_backend().simulated
