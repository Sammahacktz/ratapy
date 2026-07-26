#!/usr/bin/env python3
"""Storage manager: firmware footprint per board + live device-slot usage.

    python -m ratapyUI.ops.storage                 # footprint of every board
    python -m ratapyUI.ops.storage --board uno     # just one board
    python -m ratapyUI.ops.storage --i2c           # footprint of the I2C build too
    python -m ratapyUI.ops.storage --live          # slots used on connected boards

Two kinds of "storage":

- **Firmware footprint** -- how much flash / SRAM the sketch uses on each board
  (like ``firmware/sizes.py``, compiled fresh via arduino-cli).
- **Device slots** -- how many of a *connected* board's device slots are in use
  (from its live PING reply: device_count / max_devices).
"""

from __future__ import annotations

import argparse
import json
import subprocess

from .. import theme
from .common import ACLI, BOARDS, SKETCH, Board, Detected, scan_serial

# Section (used, max) in bytes.
Footprint = dict[str, tuple[int, int]]


def compile_footprint(board: Board, i2c: int | None = None) -> Footprint:
    """Compile the sketch for ``board`` and return flash/SRAM (used, max) bytes.

    Reads the compiler's JSON section sizes -- not the localized text summary.
    Raises RuntimeError with the compiler output if the build fails.
    """
    cmd = [str(ACLI), "compile", "--clean", "--fqbn", board.fqbn, "--format", "json"]
    if i2c is not None:
        cmd += ["--build-property", f"build.extra_flags=-DRATA_I2C_ADDRESS={i2c:#04x}"]
    cmd.append(str(SKETCH))
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr or out.stdout or f"compile failed for {board.fqbn}")
    data = json.loads(out.stdout)
    sections = (data.get("builder_result", {}).get("executable_sections_size")
                or data.get("executable_sections_size") or [])
    by_name = {s["name"]: s for s in sections}
    text = by_name.get("text", {"size": 0, "max_size": 0})
    ram = by_name.get("data", {"size": 0, "max_size": 0})
    return {"Flash": (text["size"], text["max_size"]),
            "SRAM": (ram["size"], ram["max_size"])}


def device_slots(d: Detected) -> tuple[int, int] | None:
    """(used, total) device slots for a connected board, or None if unknown."""
    if d.info is None or d.info.max_devices is None:
        return None
    return d.info.device_count, d.info.max_devices


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RATA storage manager")
    ap.add_argument("--board", choices=BOARDS, help="only this board")
    ap.add_argument("--i2c", action="store_true", help="also show the I2C build")
    ap.add_argument("--live", action="store_true",
                    help="show device-slot usage of connected boards instead")
    args = ap.parse_args(argv)

    if args.live:
        print(theme.ansi("bold", "\nDevice slots in use"))
        print(theme.ansi("muted", theme.HEAVY * 46))
        found = [d for d in scan_serial() if d.responds]
        if not found:
            print("  " + theme.ansi("muted", "no responding boards found"))
        for d in found:
            slots = device_slots(d)
            print(f"\n{theme.ansi('bold', d.label)}")
            if slots is None:
                print("  " + theme.ansi("muted", "board did not report a slot count"))
            else:
                print(f"  Slots  {theme.bar_text(*slots, unit='')}")
        print()
        return 0

    boards = {args.board: BOARDS[args.board]} if args.board else dict(BOARDS)
    print(theme.ansi("bold", "\nRATA firmware footprint"))
    print(theme.ansi("muted", theme.HEAVY * 46))
    for board in boards.values():
        variants: list[tuple[str, int | None]] = [("serial", None)]
        if args.i2c:
            variants.append(("I2C", 0x08))
        for label, addr in variants:
            tag = board.name if addr is None else f"{board.name}  ·  I2C"
            print(f"\n{theme.ansi('bold', tag):<28} {theme.ansi('muted', board.fqbn)}")
            try:
                sizes = compile_footprint(board, addr)
            except RuntimeError as e:
                print("  " + theme.ansi("bad", f"compile failed: {e.args[0].splitlines()[-1]}"))
                continue
            for kind, (used, total) in sizes.items():
                print(f"  {kind:<6} {theme.bar_text(used, total)}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
