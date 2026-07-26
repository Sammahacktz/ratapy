"""Drawing widgets: titled boxes, a selectable menu, a scrolling log pane.

All drawing is defensive -- writing to the bottom-right cell of a curses window
raises, and windows can be tiny, so every helper clips to the window and
swallows the harmless edge-write error. Geometry is passed in as (y, x, h, w)
rectangles; the widgets hold only their own state (menu selection, log buffer).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .. import theme
from .screen import Key, Palette

if TYPE_CHECKING:
    from curses import window as Win

def addstr(win: "Win", y: int, x: int, text: str, attr: int = 0) -> None:
    """Write ``text`` at (y, x), clipped to the window, ignoring edge errors."""
    h, w = win.getmaxyx()
    if not (0 <= y < h) or x >= w:
        return
    if x < 0:
        text = text[-x:]
        x = 0
    text = text[: max(0, w - x)]
    try:
        win.addstr(y, x, text, attr)
    except Exception:
        # curses raises when writing the very last cell; the text is drawn anyway.
        pass


def box(win: "Win", y: int, x: int, h: int, w: int, title: str = "",
        palette: Palette | None = None, focused: bool = False) -> None:
    """Draw a bordered box with an optional title in the top border."""
    if h < 2 or w < 2:
        return
    border = (palette or {}).get("accent", 0) if focused else 0
    t = theme
    addstr(win, y, x, t.TL + t.H * (w - 2) + t.TR, border)
    for i in range(1, h - 1):
        addstr(win, y + i, x, t.V, border)
        addstr(win, y + i, x + w - 1, t.V, border)
    addstr(win, y + h - 1, x, t.BL + t.H * (w - 2) + t.BR, border)
    if title:
        label = f" {title} "
        attr = (palette or {}).get("title", 0)
        addstr(win, y, x + 2, label[: max(0, w - 4)], attr)


def clip_lines(text: str, width: int) -> list[str]:
    """Split ``text`` into lines that each fit ``width`` (no wrapping smarts)."""
    return [line[:width] for line in text.splitlines()]



@dataclass
class MenuItem:
    label: str
    value: object = None
    hint: str = ""
    enabled: bool = True # static: False = never selectable (e.g. a header)
    multi: bool = False # a field whose value cycles with left/right
    running: bool = False # transient: an action is running -> icon + no re-trigger


class Menu:
    """A vertical list the user moves through with the arrows / j-k / mouse."""

    def __init__(self, items: list[MenuItem]) -> None:
        self.items = items
        self.selected = 0
        self._top = 0                 # first visible row (for scrolling)
        self._last_region: tuple[int, int, int, int] | None = None

    def set_items(self, items: list[MenuItem]) -> None:
        self.items = items
        self.selected = min(self.selected, max(0, len(items) - 1))
        self._top = 0

    @property
    def current(self) -> MenuItem | None:
        return self.items[self.selected] if self.items else None

    def move(self, delta: int) -> None:
        if not self.items:
            return
        self.selected = (self.selected + delta) % len(self.items)

    def handle_key(self, key: int) -> str | None:
        """Return 'select' on Enter/Space, else None (after moving for arrows)."""
        if Key.is_(key, Key.UP):
            self.move(-1)
        elif Key.is_(key, Key.DOWN):
            self.move(1)
        elif Key.is_(key, Key.ENTER) or Key.is_(key, Key.SPACE):
            return "select"
        return None

    def handle_mouse(self, my: int, mx: int) -> str | None:
        """Click-to-select within the last drawn region. Returns 'select' on hit."""
        if self._last_region is None:
            return None
        y, x, h, w = self._last_region
        if not (x <= mx < x + w and y <= my < y + h):
            return None
        idx = self._top + (my - y)
        if 0 <= idx < len(self.items):
            self.selected = idx
            return "select"
        return None

    def draw(self, win: "Win", y: int, x: int, h: int, w: int,
             palette: Palette, focused: bool = True) -> None:
        self._last_region = (y, x, h, w)
        # keep the selection visible
        if self.selected < self._top:
            self._top = self.selected
        elif self.selected >= self._top + h:
            self._top = self.selected - h + 1

        for row in range(h):
            idx = self._top + row
            if idx >= len(self.items):
                break
            item = self.items[idx]
            chosen = idx == self.selected
            # lead glyph: running spinner wins, else the selection arrow
            lead = theme.RUNNING if item.running else (theme.ARROW if chosen else " ")
            text = f"{lead} {item.label}"
            # append the hint right-aligned only if both it and the label fit
            hint = f"< {item.hint} >" if item.multi else item.hint
            if item.hint and len(text) + len(hint) + 2 <= w:
                pad = w - len(text) - len(hint)
                text = f"{text}{' ' * pad}{hint}"
            text = text.ljust(w)[:w]
            if item.running:
                attr = palette["accent"]              # clearly "busy", not dimmed
            elif chosen and focused:
                attr = palette["selected"]
            elif not item.enabled:
                attr = palette["muted"]
            else:
                attr = palette["normal"]
            addstr(win, y + row, x, text, attr)


class LogPane:
    """A bounded, auto-scrolling transcript -- the bottom 'live terminal'."""

    def __init__(self, capacity: int = 2000) -> None:
        self.lines: deque[str] = deque(maxlen=capacity)

    def append(self, line: str) -> None:
        # split embedded newlines so callers can pass raw blocks too
        for part in str(line).split("\n"):
            self.lines.append(part)

    def clear(self) -> None:
        self.lines.clear()

    def draw(self, win: "Win", y: int, x: int, h: int, w: int, palette: Palette) -> None:
        visible = list(self.lines)[-h:]
        for row in range(h):
            line = visible[row] if row < len(visible) else ""
            attr = palette["normal"]
            if line.startswith("$ "):
                attr = palette["accent"]
            elif line.lstrip().startswith("!") or "fail" in line.lower() or "error" in line.lower():
                attr = palette["bad"]
            # pad to width so incremental redraws overwrite the previous frame
            addstr(win, y + row, x, line.ljust(w)[:w], attr)


def draw_bar(win: "Win", y: int, x: int, width: int, used: int, total: int,
             palette: Palette) -> None:
    """A curses usage bar (the coloured twin of theme.bar_text)."""
    filled, lvl = theme.bar_cells(used, total, width)
    addstr(win, y, x, theme.BAR_USED * filled, palette[lvl])
    addstr(win, y, x + filled, theme.BAR_FREE * (width - filled), palette["muted"])
