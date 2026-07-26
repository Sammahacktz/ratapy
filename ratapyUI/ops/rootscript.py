#!/usr/bin/env python3
"""Run one of RATA's root-only Pi setup scripts, streaming it to a runner.

The Pi hardware features (USB gadget mode, the I2C bus) are each a small
`scripts/setup-*.sh` that edits the boot config and therefore needs root and a
reboot. They all need the same wrapper around that -- so it lives here once, and
`usbgadget` / `i2c` are just the script plus its label.

Because the panel captures output through a pipe (no terminal), it cannot answer a
sudo password prompt: this runs `sudo -n` first and, if that would prompt, tells
the user to run the script in a shell themselves.
"""

from __future__ import annotations

from pathlib import Path

from .. import theme
from .runner import CommandRunner


def run(runner: CommandRunner, script: Path, label: str, undo: bool) -> int:
    """Run ``script`` (with ``--undo`` if asked) via sudo. Returns its exit code."""
    if not script.exists():
        runner.log(f"  ! setup script missing: {script}")
        return 1

    verb = "disable" if undo else "enable"
    runner.log(f"{label} {verb} edits the Pi's boot config, so it needs root.")
    # No tty here, so we can't type a sudo password -- require passwordless sudo.
    if runner.run(["sudo", "-n", "true"], echo=False) != 0:
        runner.log("  ! sudo would prompt for a password (the panel has no terminal).")
        runner.log("    Run it yourself in a shell instead:")
        flag = " --undo" if undo else ""
        runner.log(f"      sudo ./scripts/{script.name}{flag}")
        return 1

    cmd = ["sudo", "-n", str(script)]
    if undo:
        cmd.append("--undo")
    code = runner.run(cmd)
    runner.log("")
    if code == 0:
        runner.log(f"done {theme.OK_GLYPH} -- reboot the Pi to apply:  sudo reboot")
    return code
