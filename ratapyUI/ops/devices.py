#!/usr/bin/env python3
"""List Arduinos connected over serial (and I2C, if a bus is wired).

    python -m ratapyUI.ops.devices            # serial ports
    python -m ratapyUI.ops.devices --i2c      # also scan the I2C bus (bus 1)

Opens each serial port, sends a RATA PING, and reports what answered -- board
model (guessed from the pin count it reports), firmware version and how many
devices it currently has registered.
"""

from __future__ import annotations

import argparse

from .. import theme
from .common import Detected, scan_i2c, scan_serial


def scan(include_i2c: bool = False, i2c_bus: int = 1) -> list[Detected]:
    """Probe serial ports (and optionally the I2C bus). Returns one item each."""
    found = scan_serial()
    if include_i2c:
        found += scan_i2c(i2c_bus)
    return found


def describe(d: Detected) -> str:
    """A one-line human summary of a probed connection."""
    if not d.responds:
        return f"{theme.BAD_GLYPH} {d.address:<16} no RATA response ({d.error})"
    info = d.info
    assert info is not None
    model = d.board.name if d.board else f"?/{info.num_digital_pins} pins"
    return (f"{theme.OK_GLYPH} {d.address:<16} {model:<12} "
            f"proto v{info.version}  ·  {info.device_count}/{info.max_devices or '?'} devices")


def render(found: list[Detected]) -> list[str]:
    """Format the whole scan as printable lines (shared shape for CLI + TUI)."""
    if not found:
        return [theme.ansi("muted", "no serial ports found (is a board plugged in?)")]
    return [describe(d) for d in found]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="List connected RATA devices")
    ap.add_argument("--i2c", action="store_true", help="also scan the I2C bus")
    ap.add_argument("--bus", type=int, default=1, help="I2C bus number (default 1)")
    args = ap.parse_args(argv)

    print(theme.ansi("bold", "\nConnected devices"))
    print(theme.ansi("muted", theme.HEAVY * 46))
    for line in render(scan(include_i2c=args.i2c, i2c_bus=args.bus)):
        print("  " + line)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
