#!/usr/bin/env python3
"""Enable or disable USB gadget mode on a Raspberry Pi (HID gamepad / storage).

Wraps scripts/setup-usb-gadget.sh so the control panel can run it and stream the
output. The script edits the Pi's boot config, so it needs **root** and a reboot.

    python -m ratapyUI.ops.usbgadget            # enable
    python -m ratapyUI.ops.usbgadget --undo     # revert to a normal Pi

Because the panel captures output through a pipe (no terminal), it can't answer a
sudo password prompt -- this runs `sudo -n` and, if that would prompt, tells you to
run the script yourself in a terminal instead.
"""

from __future__ import annotations

import argparse

from . import rootscript
from .common import SETUP_USB_GADGET_SH
from .runner import CommandRunner


def setup(runner: CommandRunner) -> int:
    """Enable USB gadget mode."""
    return rootscript.run(runner, SETUP_USB_GADGET_SH, "USB gadget", undo=False)


def undo(runner: CommandRunner) -> int:
    """Disable USB gadget mode (revert the boot config to a normal Pi)."""
    return rootscript.run(runner, SETUP_USB_GADGET_SH, "USB gadget", undo=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Enable/disable USB gadget mode")
    ap.add_argument("--undo", action="store_true", help="revert to a normal Pi")
    args = ap.parse_args(argv)
    return undo(CommandRunner()) if args.undo else setup(CommandRunner())


if __name__ == "__main__":
    raise SystemExit(main())
