#!/usr/bin/env python3
"""Enable or disable the Raspberry Pi's I2C bus (what `I2CLink` needs).

Wraps scripts/setup-i2c.sh so the control panel can run it and stream the output.
The script edits the Pi's boot config, so it needs **root** and a reboot.

    python -m ratapyUI.ops.i2c            # enable  -> /dev/i2c-1
    python -m ratapyUI.ops.i2c --undo     # turn the bus back off
"""

from __future__ import annotations

import argparse

from . import rootscript
from .common import SETUP_I2C_SH
from .runner import CommandRunner


def setup(runner: CommandRunner) -> int:
    """Enable the I2C bus (dtparam + i2c-dev + i2c-tools + group)."""
    return rootscript.run(runner, SETUP_I2C_SH, "I2C", undo=False)


def undo(runner: CommandRunner) -> int:
    """Disable the I2C bus (remove exactly what setup added)."""
    return rootscript.run(runner, SETUP_I2C_SH, "I2C", undo=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Enable/disable the Pi's I2C bus")
    ap.add_argument("--undo", action="store_true", help="turn the bus back off")
    args = ap.parse_args(argv)
    return undo(CommandRunner()) if args.undo else setup(CommandRunner())


if __name__ == "__main__":
    raise SystemExit(main())
