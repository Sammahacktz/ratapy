"""Curses bootstrap: colour palette, mouse, and key-name helpers.

Keeps every curses-global concern in one spot so the widgets and pages can just
ask the palette for ``palette["ok"]`` and compare keys with the ``Key`` names.
"""

from __future__ import annotations

import curses
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from curses import window as Win    

# Resolve a lone Esc quickly, but still assemble arrow-key escape sequences
# (Esc + '[B' -> KEY_DOWN). Without this, a fast arrow press can surface as a
# bare Esc. Must be set before curses initialises the terminal.
os.environ.setdefault("ESCDELAY", "25")

# A palette maps a semantic name to a curses attribute (colour pair | bold ...).
Palette = dict[str, int]


def init_palette() -> Palette:
    """Set up colour pairs (degrading gracefully on a mono terminal)."""
    palette: Palette = {name: 0 for name in
                        ("normal", "ok", "warn", "bad", "accent", "muted",
                         "title", "selected", "logo")}
    palette["title"] = curses.A_BOLD
    palette["selected"] = curses.A_REVERSE | curses.A_BOLD
    palette["muted"] = curses.A_DIM
    if not curses.has_colors():
        return palette

    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error: # terminal without default colours
        bg = curses.COLOR_BLACK

    pairs = {
        "ok":     (curses.COLOR_GREEN, bg),
        "warn":   (curses.COLOR_YELLOW, bg),
        "bad":    (curses.COLOR_RED, bg),
        "accent": (curses.COLOR_CYAN, bg),
        "logo":   (curses.COLOR_CYAN, bg),
        "muted":  (curses.COLOR_WHITE, bg),
    }
    for i, (name, (fg, back)) in enumerate(pairs.items(), start=1):
        curses.init_pair(i, fg, back)
        palette[name] = curses.color_pair(i)
    palette["title"] = palette["accent"] | curses.A_BOLD
    palette["selected"] = curses.A_REVERSE | curses.A_BOLD
    palette["muted"] |= curses.A_DIM
    palette["logo"] |= curses.A_BOLD
    return palette


def enable_mouse() -> bool:
    """Turn on mouse click reporting. Returns True if the terminal supports it."""
    try:
        avail, _ = curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED)
        return avail != 0
    except curses.error:
        return False


def configure(stdscr: "Win") -> Palette:
    """Common startup for the root window; returns the palette."""
    curses.curs_set(0)             
    stdscr.keypad(True)            
    stdscr.nodelay(False)
    enable_mouse()
    return init_palette()


class Key:
    """Symbolic key checks (getch() returns ints; this keeps pages readable)."""

    UP = {curses.KEY_UP, ord("k")}
    DOWN = {curses.KEY_DOWN, ord("j")}
    LEFT = {curses.KEY_LEFT, ord("h")}
    RIGHT = {curses.KEY_RIGHT, ord("l")}
    ENTER = {curses.KEY_ENTER, 10, 13}
    SPACE = {ord(" ")}
    BACK = {27, curses.KEY_BACKSPACE, ord("b")}   # Esc / Backspace / b
    QUIT = {ord("q")}
    TAB = {ord("\t"), 9}
    MOUSE = {curses.KEY_MOUSE}

    @staticmethod
    def is_(key: int, names: set[int]) -> bool:
        return key in names


def run(main: Any) -> Any:
    """Run ``main(stdscr, palette)`` inside a curses session (restores on exit)."""
    def _wrapped(stdscr: "Win") -> Any:
        palette = configure(stdscr)
        return main(stdscr, palette)
    return curses.wrapper(_wrapped)
