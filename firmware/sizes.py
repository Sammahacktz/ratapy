#!/usr/bin/env python3
"""Show the RATA firmware footprint (flash + SRAM) per board

    ./firmware/sizes.py              # serial build for mega, uno, nano
    ./firmware/sizes.py --i2c        # also show the I2C build of each
    ./firmware/sizes.py --board uno  # just one board

Compiles the sketch (via firmware/acli.sh) and reads the section sizes from the
compiler's JSON output
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACLI = HERE / "acli.sh"
SKETCH = HERE / "rata"

BOARDS = {
    "mega": ("Mega 2560", "arduino:avr:mega"),
    "uno":  ("Uno", "arduino:avr:uno"),
    "nano": ("Nano", "arduino:avr:nano"),
}

BAR_WIDTH = 30
USE = "█"
FREE = "░"

TTY = sys.stdout.isatty()
def c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if TTY else s

def colour_for(pct: float) -> str:
    return "32" if pct < 60 else "33" if pct < 85 else "31"   # green / yellow / red


def compile_sizes(fqbn: str, i2c: int | None) -> dict[str, tuple[int, int]]:
    """Return {'Flash': (used, max), 'SRAM': (used, max)} for one build."""
    cmd = [str(ACLI), "compile", "--clean", "--fqbn", fqbn, "--format", "json"]
    if i2c is not None:
        cmd += ["--build-property", f"build.extra_flags=-DRATA_I2C_ADDRESS={i2c:#04x}"]
    cmd.append(str(SKETCH))
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.stderr.write(out.stderr or out.stdout)
        raise SystemExit(f"compile failed for {fqbn}")
    data = json.loads(out.stdout)
    sections = (data.get("builder_result", {}).get("executable_sections_size")
                or data.get("executable_sections_size") or [])
    by_name = {s["name"]: s for s in sections}
    text = by_name.get("text", {"size": 0, "max_size": 0})
    ram = by_name.get("data", {"size": 0, "max_size": 0})
    return {
        "Flash": (text["size"], text["max_size"]),
        "SRAM":  (ram["size"], ram["max_size"]),
    }


def bar(used: int, total: int) -> str:
    pct = (used / total * 100) if total else 0.0
    filled = round(pct / 100 * BAR_WIDTH)
    graph = c(colour_for(pct), USE * filled) + c("2", FREE * (BAR_WIDTH - filled))
    return (f"{graph}  {used:>7,} / {total:>7,} B  "
            f"{c(colour_for(pct), f'{pct:5.1f}%')}  "
            f"{c('2', f'({total - used:,} free)')}")


def main() -> None:
    ap = argparse.ArgumentParser(description="RATA firmware footprint")
    ap.add_argument("--board", choices=BOARDS, help="only this board")
    ap.add_argument("--i2c", action="store_true", help="also show the I2C build")
    args = ap.parse_args()

    boards = {args.board: BOARDS[args.board]} if args.board else BOARDS

    print(c("1", "\nRATA firmware footprint"))
    print(c("2", "━" * 46))
    for key, (name, fqbn) in boards.items():
        variants = [("serial", None)]
        if args.i2c:
            variants.append(("I2C", 0x08))
        for label, addr in variants:
            tag = name if addr is None else f"{name}  ·  I2C"
            print(f"\n{c('1', tag):<28} {c('2', fqbn)}")
            sizes = compile_sizes(fqbn, addr)
            for kind, (used, total) in sizes.items():
                print(f"  {kind:<6} {bar(used, total)}")
    print()


if __name__ == "__main__":
    main()
