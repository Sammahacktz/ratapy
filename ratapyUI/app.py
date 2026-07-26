"""The RATA control panel -- a curses TUI that ties the ops together.

Layout (detail pages):

    ┌ title ─────────────────────────────────────────────┐
    │ ┌ menu ───────┐ ┌ details ────────────────────────┐ │
    │ │ › item      │ │  bars / forms / info            │ │
    │ └─────────────┘ └─────────────────────────────────┘ │
    ┌ Log ────────────────────────────────────────────────┐
    │ $ ./firmware/flash.sh --board mega ...               │
    └─────────────────────────────────────────────────────┘
      ↑↓ move · Enter select · Esc back · q quit

The bottom **Log** pane is the live transcript: every command an action runs is
echoed there and its output streams in as it happens (see ops/runner.py). The
home screen swaps the split for the ASCII wordmark.

Run it with ``ratapyui`` / ``python -m ratapyUI``. Each action is also a
standalone script (``python -m ratapyUI.ops.<name>``) for people who skip the UI.
"""

from __future__ import annotations

import curses
from collections.abc import Callable
from typing import TYPE_CHECKING

from . import theme
from .ops.runner import CommandRunner
from .tui import widgets as W
from .tui.screen import Key, Palette, run as run_curses

if TYPE_CHECKING:
    from curses import window as Win


class Page:
    """A full-screen view. Subclasses draw the work area and handle keys."""

    title = "RATA"
    hints = "↑↓ move · Enter select · Esc back · q quit"
    # shown on a loading overlay while on_enter() runs; None = open instantly
    loading: str | None = None

    def on_enter(self, app: "App") -> None:
        """Called when the page becomes active (e.g. to (re)scan hardware)."""

    def draw(self, app: "App", y: int, x: int, h: int, w: int) -> None:
        raise NotImplementedError

    def handle_key(self, app: "App", key: int) -> None:
        pass

    def handle_mouse(self, app: "App", my: int, mx: int) -> None:
        pass

    def handle_back(self, app: "App") -> bool:
        """Handle Esc/back internally. Return True if consumed, else App goes home."""
        return False


class DetailPage(Page):
    """The standard left-menu / right-detail page.

    Subclasses provide ``left_title`` / ``right_title``, fill ``menu`` (a
    :class:`~ratapyUI.tui.widgets.Menu`), draw the right panel in
    :meth:`draw_detail`, and react to a chosen item in :meth:`on_select`
    (or to left/right on a field in :meth:`on_adjust`).
    """

    left_title = "Menu"
    right_title = "Details"

    def __init__(self) -> None:
        self.menu = W.Menu([])

    # geometry: title row, then the two boxes side by side
    def draw(self, app: "App", y: int, x: int, h: int, w: int) -> None:
        win = app.stdscr
        W.addstr(win, y, x + 1, self.title, app.palette["title"])
        top, height = y + 1, h - 1
        left_w = min(38, max(18, w // 3))
        W.box(win, top, x, height, left_w, self.left_title, app.palette, focused=True)
        self.menu.draw(win, top + 1, x + 2, height - 2, left_w - 4, app.palette)
        rx, rw = x + left_w + 1, w - left_w - 1
        W.box(win, top, rx, height, rw, self.right_title, app.palette)
        self.draw_detail(app, top + 1, rx + 2, height - 2, rw - 4)

    def draw_detail(self, app: "App", y: int, x: int, h: int, w: int) -> None:
        pass

    def handle_key(self, app: "App", key: int) -> None:
        if Key.is_(key, Key.LEFT) or Key.is_(key, Key.RIGHT):
            item = self.menu.current
            if item is not None:
                self.on_adjust(app, item, 1 if Key.is_(key, Key.RIGHT) else -1)
            return
        if self.menu.handle_key(key) == "select" and self.menu.current is not None:
            self.on_select(app, self.menu.current)

    def handle_mouse(self, app: "App", my: int, mx: int) -> None:
        if self.menu.handle_mouse(my, mx) == "select" and self.menu.current is not None:
            self.on_select(app, self.menu.current)

    def on_select(self, app: "App", item: W.MenuItem) -> None:
        pass

    def on_adjust(self, app: "App", item: W.MenuItem, delta: int) -> None:
        pass


class App:
    """Owns the screen, the shared log pane, and the page-switching loop."""

    def __init__(self, stdscr: "Win", palette: Palette) -> None:
        self.stdscr = stdscr
        self.palette = palette
        self.log = W.LogPane()
        self.running = True
        self._log_rect: tuple[int, int, int, int] | None = None
        # built lazily to avoid an import cycle (pages import App)
        from .pages import HomePage
        self.home = HomePage()
        self.page: Page = self.home

    def goto(self, page: Page) -> None:
        self.page = page
        if page.loading:
            self.show_loading(page.loading)     # cover the slow on_enter()
        page.on_enter(self)

    def go_home(self) -> None:
        self.goto(self.home)

    def show_loading(self, message: str) -> None:
        """Draw a centered 'working' box immediately (before a slow operation)."""
        win = self.stdscr
        win.erase()
        h, w = win.getmaxyx()
        text = f"{theme.BUSY}  {message}"
        bw = min(w - 4, max(28, len(text) + 6))
        bh, by, bx = 5, (h - 5) // 2, (w - min(w - 4, max(28, len(text) + 6))) // 2
        W.box(win, by, bx, bh, bw, "", self.palette, focused=True)
        W.addstr(win, by + 2, bx + max(2, (bw - len(text)) // 2), text, self.palette["accent"])
        win.refresh()

    def runner(self) -> CommandRunner:
        """A CommandRunner whose output streams into the bottom log pane."""
        return CommandRunner(sink=self._log_sink)

    def run_action(self, item: W.MenuItem, fn: Callable[[], object]) -> None:
        """Run a blocking action tied to a menu item.

        Marks the item as running (spinner icon, and re-selecting it is a no-op)
        so a mashed Enter/click can't fire it twice; paints that state before we
        block; and flushes keys queued during the run so they don't re-trigger it.
        """
        if item.running:
            return
        item.running = True
        self.draw()  # show the running icon before we block
        try:
            fn()
        finally:
            item.running = False
            curses.flushinp() # discard keypresses buffered during the run

    def _log_sink(self, line: str) -> None:
        self.log.append(line)
        self._redraw_log()

    def _redraw_log(self) -> None:
        if self._log_rect is not None:
            self.log.draw(self.stdscr, *self._log_rect, self.palette)
            self.stdscr.refresh()

    def draw(self) -> None:
        win = self.stdscr
        win.erase()
        h, w = win.getmaxyx()
        if h < 12 or w < 50:
            W.addstr(win, 0, 0, "terminal too small (need >= 50x12)", self.palette["bad"])
            win.refresh()
            return

        footer_y = h - 1
        log_h = min(max(6, h // 4), h - 8)
        log_y = footer_y - log_h
        # bottom log pane (100% width)
        W.box(win, log_y, 0, log_h, w, "Log", self.palette)
        self._log_rect = (log_y + 1, 2, log_h - 2, w - 4)
        self.log.draw(win, *self._log_rect, self.palette)
        # work area above the log
        self.page.draw(self, 0, 0, log_y, w)
        # footer key hints
        W.addstr(win, footer_y, 1, self.page.hints.ljust(w - 1)[: w - 1], self.palette["muted"])
        win.refresh()

    def dispatch(self, key: int) -> None:
        if Key.is_(key, Key.MOUSE):
            try:
                _, mx, my, _, _ = curses.getmouse()
            except curses.error:
                return
            self.page.handle_mouse(self, my, mx)
            return
        if Key.is_(key, Key.QUIT):
            self.running = False
            return
        if Key.is_(key, Key.BACK):
            if self.page.handle_back(self):
                return # the page consumed it (e.g. drill-up)
            if self.page is not self.home:
                self.go_home()
            return
        self.page.handle_key(self, key)

    def run(self) -> None:
        self.log.append("RATA control panel ready.")
        self.log.append("Pick an action on the left; commands appear here.")
        self.page.on_enter(self)
        while self.running:
            self.draw()
            try:
                key = self.stdscr.getch()
            except KeyboardInterrupt:
                break
            if key == curses.KEY_RESIZE:
                continue
            self.dispatch(key)


def main() -> int:
    """Entry point: launch the curses app (restores the terminal on exit)."""
    import sys

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.stderr.write(
            "ratapyUI needs an interactive terminal.\n"
            "Run it directly (./ratapyui), or use an action on its own, e.g.\n"
            "  python -m ratapyUI.ops.devices\n"
        )
        return 2

    def _boot(stdscr: "Win", palette: Palette) -> None:
        App(stdscr, palette).run()
    run_curses(_boot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
