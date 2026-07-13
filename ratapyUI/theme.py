"""Shared visual identity for the RATA control panel.

One place for the glyphs, colours and ASCII art so the TUI (curses) and the
standalone scripts (ANSI) look like siblings of ``firmware/sizes.py`` -- unicode
bars, green/yellow/red thresholds, box-drawing borders.

Nothing here imports curses, so it is safe to use from the plain CLI scripts too.
"""

from __future__ import annotations

import sys


BAR_USED = "█"
BAR_FREE = "░"
BAR_WIDTH = 30

# Box drawing (light + heavy) for borders and rules.
H, V = "─", "│"
TL, TR, BL, BR = "┌", "┐", "└", "┘"
HEAVY = "━"

OK_GLYPH = "●"
WARN_GLYPH = "▲"
BAD_GLYPH = "✕"
ARROW = "›"
BUSY = "⏳"
RUNNING = "⟳"
MASTER_GLYPH = "▣"


LOGO = r"""
 ██████╗  █████╗ ████████╗ █████╗
 ██╔══██╗██╔══██╗╚══██╔══╝██╔══██╗
 ██████╔╝███████║   ██║   ███████║
 ██╔══██╗██╔══██║   ██║   ██╔══██║
 ██║  ██║██║  ██║   ██║   ██║  ██║
 ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝
"""

TAGLINE = "Raspberry-pi Attached Arduinos  ·  control panel"


def level_for(pct: float) -> str:
    """'ok' / 'warn' / 'bad' for a 0..100 percentage (green / yellow / red)."""
    return "ok" if pct < 60 else "warn" if pct < 85 else "bad"


_ANSI = {
    "reset": "0", "bold": "1", "dim": "2",
    "ok": "32", "warn": "33", "bad": "31", "accent": "36", "muted": "2",
}
_TTY = sys.stdout.isatty()


def ansi(style: str, text: str) -> str:
    """Wrap ``text`` in an ANSI style (no-op when stdout is not a terminal)."""
    code = _ANSI.get(style, "0")
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def bar_cells(used: int, total: int, width: int = BAR_WIDTH) -> tuple[int, str]:
    """(#filled cells, level) for a bar -- the maths the TUI reuses with curses."""
    pct = (used / total * 100) if total else 0.0
    return round(pct / 100 * width), level_for(pct)


def bar_text(used: int, total: int, width: int = BAR_WIDTH, unit: str = "B") -> str:
    """A unicode usage bar with counts + percent, styled with ANSI colours.

    The plain-text twin of the curses bar -- used by the standalone scripts so
    ``storage.py`` on its own looks just like ``sizes.py``.
    """
    pct = (used / total * 100) if total else 0.0
    filled, lvl = bar_cells(used, total, width)
    graph = ansi(lvl, BAR_USED * filled) + ansi("muted", BAR_FREE * (width - filled))
    tail = f" {unit}" if unit else ""
    return (f"{graph}  {used:>7,} / {total:>7,}{tail}  "
            f"{ansi(lvl, f'{pct:5.1f}%')}  {ansi('muted', f'({total - used:,} free)')}")
