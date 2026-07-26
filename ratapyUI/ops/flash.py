#!/usr/bin/env python3
"""Flash the RATA firmware onto an Arduino (thin, honest wrapper over flash.sh).

    python -m ratapyUI.ops.flash --board mega
    python -m ratapyUI.ops.flash --board uno --port /dev/ttyUSB1
    python -m ratapyUI.ops.flash --board uno --i2c 8         # I2C slave at addr 8
    python -m ratapyUI.ops.flash --board mega --compile-only # build, don't upload

All the real work lives in ``firmware/flash.sh`` (clean compile + upload, I2C
address baking). This module just builds the argument list -- so the TUI and the
CLI flash in exactly the same way, and you can see the command in the log.
"""

from __future__ import annotations

import argparse

from .common import BOARDS, FLASH_SH
from .runner import CommandRunner


def flash_command(board: str, port: str = "/dev/ttyUSB0",
                  i2c: int | None = None, compile_only: bool = False) -> list[str]:
    """Build the ``flash.sh`` command line for the given options."""
    if board not in BOARDS:
        raise ValueError(f"unknown board {board!r} (choose from {', '.join(BOARDS)})")
    cmd = [str(FLASH_SH), "--board", board]
    if compile_only:
        cmd.append("--compile-only")
    else:
        cmd += ["--port", port]
    if i2c is not None:
        cmd += ["--i2c", str(i2c)]
    return cmd


def flash(runner: CommandRunner, board: str, port: str = "/dev/ttyUSB0",
          i2c: int | None = None, compile_only: bool = False) -> int:
    """Run the flash and stream it to the runner's sink. Returns the exit code."""
    return runner.run(flash_command(board, port, i2c, compile_only))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Flash the RATA firmware")
    ap.add_argument("--board", required=True, choices=BOARDS)
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--i2c", type=int, default=None,
                    help="make it an I2C slave at this address (8..119)")
    ap.add_argument("--compile-only", action="store_true",
                    help="build but do not upload (no board needed)")
    args = ap.parse_args(argv)
    return flash(CommandRunner(), args.board, args.port, args.i2c, args.compile_only)


if __name__ == "__main__":
    raise SystemExit(main())
