"""Storage -- show / hide the Pi as a USB drive on the host.

When the Pi is a USB gadget it can *also* offer a mass-storage function, so the
host mounts it as a removable drive you can drop files onto. `hide()` removes that
function -- the host stops seeing a drive, so the gamepad is all that's exposed
(handy when you want the device to act purely as a controller, with its files
locked away). `show()` brings the drive back::

    storage = Storage(board=rp)
    if not ready:
        storage.hide()      # gamepad-only, no drive
    else:
        storage.show()      # editable drive visible again

RATA manages the backing store itself: a small FAT image under the user's home,
created on first `show()`. Note this is a *managed area*, not the Pi's live root
filesystem -- a Linux mass-storage gadget always backs onto a block image, so
(unlike a CircuitPython board) the drive is not your source tree.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from ...protocol import RataError
from ...raspberry import Raspberry
from ..local.base import LocalDevice

log = logging.getLogger("ratapy.hid")

DEFAULT_IMAGE = Path.home() / ".rata" / "usb_drive.img"


def _parse_size(size: str | int) -> int:
    """Bytes from an int or a ``"64M"`` / ``"1G"`` string."""
    if isinstance(size, int):
        return size
    s = size.strip().upper()
    mult = 1
    if s.endswith("K"):
        mult, s = 1024, s[:-1]
    elif s.endswith("M"):
        mult, s = 1024 ** 2, s[:-1]
    elif s.endswith("G"):
        mult, s = 1024 ** 3, s[:-1]
    return int(s) * mult


class Storage(LocalDevice):
    """The Pi's USB mass-storage drive -- toggled with `show()` / `hide()`.

    Args:
        board: the Raspberry (needs ``usb_device=True``).
        image: backing image path (defaults to ``~/.rata/usb_drive.img``).
        size: size to create the image at if it doesn't exist (e.g. ``"64M"``).
        shown: initial state -- whether the drive is exposed straight away.
    """

    def __init__(
        self,
        board: Raspberry | None = None,
        image: str | Path | None = None,
        size: str | int = "64M",
        shown: bool = True,
    ) -> None:
        super().__init__(board)
        self._image = Path(image) if image is not None else DEFAULT_IMAGE
        self._size = _parse_size(size)
        self._shown = False
        if shown:
            self.show()

    def _ensure_image(self) -> None:
        """Create + FAT-format the backing image if it isn't there yet."""
        if self.board.gadget.simulated or self._image.exists():
            return
        self._image.parent.mkdir(parents=True, exist_ok=True)
        with open(self._image, "wb") as f:
            f.truncate(self._size)
        try:
            subprocess.run(["mkfs.vfat", str(self._image)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except FileNotFoundError as e:
            raise RataError(
                "mkfs.vfat not found -- install dosfstools to use USB storage"
            ) from e
        except subprocess.CalledProcessError as e:
            raise RataError(f"could not format {self._image}: {e.stderr.decode().strip()}") from e

    def show(self) -> None:
        """Expose the Pi as a removable drive on the host."""
        self._ensure_image()
        self.board.gadget.set_storage_image(str(self._image))
        self.board.gadget.activate()
        self._shown = True

    def hide(self) -> None:
        """Remove the drive -- the host stops seeing the Pi as storage."""
        self.board.gadget.set_storage_image(None)
        self._shown = False

    @property
    def is_shown(self) -> bool:
        return self._shown

    # No _release: the Raspberry tears the whole gadget down (base hook is a no-op).

    def __repr__(self) -> str:
        return f"Storage(image={self._image}, shown={self._shown})"
