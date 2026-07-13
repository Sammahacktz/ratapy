"""The concrete pages of the control panel.

Each page is thin: it arranges widgets and calls into ``ratapyUI.ops`` for the
real work, so the panel is glue and the ops stay independently runnable.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from . import theme
from .app import App, DetailPage, Page
from .ops import devices as op_devices
from .ops import flash as op_flash
from .ops import i2c as op_i2c
from .ops import runtests as op_tests
from .ops import storage as op_storage
from .ops import updates as op_updates
from .ops import usbgadget as op_usbgadget
from .ops.common import (
    BOARDS,
    FLASH_SH,
    REPO_ROOT,
    DeviceEntry,
    Detected,
    discover_serial_ports,
    enumerate_serial,
    probe_serial,
    scan_serial,
)
from .tui import widgets as W

class HomePage(Page):
    """The landing screen: ASCII wordmark + the top-level menu."""

    title = "RATA"
    hints = "↑↓ move · Enter open · q quit   ·   every action is also a CLI script"

    def __init__(self) -> None:
        self.menu = W.Menu([
            W.MenuItem("Find updates", "updates", "check · pull"),
            W.MenuItem("List devices", "devices", "topology · ping"),
            W.MenuItem("Storage manager", "storage", "flash · SRAM · slots"),
            W.MenuItem("Flash Arduinos", "flash", "compile + upload"),
            W.MenuItem("USB gadget setup", "usbgadget", "Pi HID gamepad"),
            W.MenuItem("I2C setup", "i2c", "Pi I2C bus"),
            W.MenuItem("Run tests", "tests", "pytest"),
            W.MenuItem("Quit", "quit", ""),
        ])

    def draw(self, app: App, y: int, x: int, h: int, w: int) -> None:
        win = app.stdscr
        logo = [ln for ln in theme.LOGO.splitlines() if ln]
        art_w = max((len(ln) for ln in logo), default=0)
        cx = x + max(0, (w - art_w) // 2)
        top = y + max(1, (h - len(logo) - len(self.menu.items) - 4) // 2)
        for i, line in enumerate(logo):
            W.addstr(win, top + i, cx, line, app.palette["logo"])
        ty = top + len(logo)
        W.addstr(win, ty, x + max(0, (w - len(theme.TAGLINE)) // 2),
                 theme.TAGLINE, app.palette["muted"])
        # menu, centred under the logo
        mw = 48
        mx = x + max(0, (w - mw) // 2)
        self.menu.draw(win, ty + 2, mx, len(self.menu.items), mw, app.palette)

    def _open(self, app: App, value: object) -> None:
        if value == "quit":
            app.running = False
            return
        page_cls = {
            "updates": UpdatesPage,
            "devices": DevicesPage,
            "storage": StoragePage,
            "flash": FlashPage,
            "usbgadget": UsbGadgetPage,
            "i2c": I2cPage,
            "tests": TestsPage,
        }[str(value)]
        # show the loading overlay before we even build the page (its __init__
        # or on_enter may probe hardware).
        if page_cls.loading:
            app.show_loading(page_cls.loading)
        app.goto(page_cls())

    def handle_key(self, app: App, key: int) -> None:
        if self.menu.handle_key(key) == "select" and self.menu.current is not None:
            self._open(app, self.menu.current.value)

    def handle_mouse(self, app: App, my: int, mx: int) -> None:
        if self.menu.handle_mouse(my, mx) == "select" and self.menu.current is not None:
            self._open(app, self.menu.current.value)

class UpdatesPage(DetailPage):
    """Check the RATA install for a newer version and pull it.

    "Search" fetches and compares; if a newer version is available it enables
    "Update", which checks it out and re-syncs deps. Both just run
    ``install.sh --check`` / ``--update`` (see ratapyUI.ops.updates).

    Two fields steer them:
      - *Target*  — which RATA to act on: the standard install at
        ~/.local/share/rata (package), or this checkout (dev, run from a clone).
      - *Channel* — stable tracks the latest release tag; pre-release tracks the
        master branch (bleeding edge, install.sh --pre-release).
    """

    title = "Find updates"
    left_title = "Action"
    right_title = "About"
    hints = "↑↓ move · ←→ change field · Enter run · Esc back · q quit"

    def __init__(self) -> None:
        super().__init__()
        self._update_available = False
        self._searched = False
        self._dev = False               # target this checkout instead of the install
        self._pre = False               # track master instead of the latest release
        self._build()

    def _home(self) -> Path | None:
        """The RATA_HOME to act on: None = install.sh's default; else this checkout."""
        return REPO_ROOT if self._dev else None

    def _build(self) -> None:
        keep = self.menu.selected
        self.menu.set_items([
            W.MenuItem("Target", "target", "dev" if self._dev else "package", multi=True),
            W.MenuItem("Channel", "channel", "pre-release" if self._pre else "stable", multi=True),
            W.MenuItem("Search for updates", "search"),
            W.MenuItem("Update", "update", enabled=self._update_available),
            W.MenuItem("Back", "back"),
        ])
        self.menu.selected = min(keep, len(self.menu.items) - 1)

    def draw_detail(self, app: App, y: int, x: int, h: int, w: int) -> None:
        if not self._searched:
            status = "Not checked yet — run Search for updates."
            status_attr = app.palette["muted"]
        elif self._update_available:
            status = f"{theme.OK_GLYPH} An update is available — select Update."
            status_attr = app.palette["warn"]                       # yellow
        else:
            status = f"{theme.OK_GLYPH} You are up to date."
            status_attr = app.palette["ok"]                         # green
        where = str(REPO_ROOT) if self._dev else "~/.local/share/rata"
        lines = [
            status,
            "",
            f"Target:   {'dev' if self._dev else 'package'}  ({where})",
            f"Channel:  {'pre-release (master)' if self._pre else 'stable (latest release)'}",
            "",
            "Search  → git fetch + compare against the channel.",
            "Update  → check that out and re-sync deps",
            f"          ({theme.ARROW} git checkout · uv sync).",
            "",
            "Target  — which RATA is acted on:",
            f"  {theme.ARROW} package  the install at ~/.local/share/rata",
            f"  {theme.ARROW} dev      this checkout (run from a clone)",
            "Channel — which version to follow:",
            f"  {theme.ARROW} stable       highest vX.Y.Z release tag",
            f"  {theme.ARROW} pre-release  master branch (bleeding edge)",
            "Restart ratapyui afterwards to run the new version.",
        ]
        for i, ln in enumerate(lines):
            if i == 0:
                attr = status_attr
            else:
                attr = app.palette["muted"] if ln.startswith(" ") else app.palette["normal"]
            W.addstr(app.stdscr, y + i, x, ln[:w], attr)

    def _search(self, app: App) -> None:
        self._update_available = op_updates.check(app.runner(), self._home(), self._pre)
        self._searched = True
        self._build()

    def _update(self, app: App) -> None:
        if op_updates.update(app.runner(), self._home(), self._pre) == 0:
            self._update_available = False
            self._build()

    def on_adjust(self, app: App, item: W.MenuItem, delta: int) -> None:
        if item.value == "target":
            self._dev = not self._dev
        elif item.value == "channel":
            self._pre = not self._pre
        else:
            return
        self._update_available = False           # field changed -> re-search
        self._searched = False
        self._build()

    def on_select(self, app: App, item: W.MenuItem) -> None:
        if item.value == "back":
            app.go_home()
            return
        if item.value in ("target", "channel"):
            self.on_adjust(app, item, 1)
            return
        app.log.append("")
        if item.value == "search":
            app.run_action(item, lambda: self._search(app))
        elif item.value == "update":
            app.run_action(item, lambda: self._update(app))

class DevicesPage(DetailPage):
    """A wiring overview: the master and each board as boxes joined by wires.

    Overview mode draws the topology; picking a board drills into its registered
    devices (id, kind, pins) read live from the firmware. `Ping` re-checks
    reachability.
    """

    title = "Connected devices"
    left_title = "Boards"
    right_title = "Topology"
    loading = "Scanning connected boards…"
    hints = "↑↓ move · Enter open/ping · Esc back · q quit"

    def __init__(self) -> None:
        super().__init__()
        self.found: list[Detected] = []
        self.include_i2c = False
        self.mode = "overview"                       # or "detail"
        self.drill: Detected | None = None
        self.entries: list[DeviceEntry] = []

    def on_enter(self, app: App) -> None:
        self._rescan(app)

    def _rescan(self, app: App) -> None:
        self.mode, self.drill, self.right_title = "overview", None, "Topology"
        app.log.append(f"$ scan serial{' + i2c' if self.include_i2c else ''}")
        self.found = op_devices.scan(include_i2c=self.include_i2c)
        for d in self.found:
            app.log.append("  " + op_devices.describe(d))
        self._overview_menu()

    def _overview_menu(self) -> None:
        items: list[W.MenuItem] = [W.MenuItem(d.label, ("board", d)) for d in self.found]
        if not items:
            items = [W.MenuItem("(no boards found)", None, enabled=False)]
        items += [
            W.MenuItem("Ping all", "ping_all"),
            W.MenuItem(f"I2C scan: {'on' if self.include_i2c else 'off'}", "toggle_i2c"),
            W.MenuItem("Rescan", "rescan"),
            W.MenuItem("Back", "back"),
        ]
        self.menu.set_items(items)

    def _selected_board(self) -> Detected | None:
        item = self.menu.current
        v = item.value if item else None
        return v[1] if isinstance(v, tuple) and v[0] == "board" else None

    def _draw_topology(self, app: App, y: int, x: int, h: int, w: int) -> None:
        win, pal = app.stdscr, app.palette
        bw = min(w, 40)
        bx = x + (w - bw) // 2
        cx = bx + bw // 2
        # master node
        W.box(win, y, bx, 3, bw, "", pal, focused=False)
        W.addstr(win, y + 1, bx + 2, f"{theme.MASTER_GLYPH} MASTER (this host)", pal["accent"])
        row = y + 3
        if not self.found:
            W.addstr(win, row + 1, x, "No boards connected — plug one in and Rescan.", pal["muted"])
            return
        sel = self._selected_board()
        for d in self.found:
            if row + 5 > y + h:                       # ran out of room
                break
            W.addstr(win, row, cx, theme.V, pal["muted"])   # wire from the trunk
            top = row + 1
            W.box(win, top, bx, 4, bw, "", pal, focused=(d is sel))
            ok = d.responds
            glyph = theme.OK_GLYPH if ok else theme.BAD_GLYPH
            name = d.board.name if d.board else "unknown board"
            W.addstr(win, top + 1, bx + 2, f"{glyph} {name}"[: bw - 4], pal["ok"] if ok else pal["bad"])
            if ok and d.info is not None:
                info = f"{d.address} · v{d.info.version} · {d.info.device_count}/{d.info.max_devices or '?'} dev"
            else:
                info = f"{d.address} · no response"
            W.addstr(win, top + 2, bx + 2, info[: bw - 4], pal["muted"])
            row = top + 4
        if row + 1 < y + h:
            W.addstr(win, row + 1, x, "Enter a board → its devices & pins.", pal["muted"])

    def _open_detail(self, app: App, d: Detected) -> None:
        self.mode, self.drill = "detail", d
        self.right_title = f"Devices · {d.address}"
        app.show_loading(f"Reading devices on {d.address}…")
        self.entries = enumerate_serial(d.address) if d.transport == "serial" else []
        app.log.append(f"$ device-info {d.address} → {len(self.entries)} device(s)")
        self.menu.set_items([
            W.MenuItem("Ping this board", "ping_one"),
            W.MenuItem("Back to topology", "to_overview"),
        ])

    def _draw_devices(self, app: App, y: int, x: int, h: int, w: int) -> None:
        win, pal = app.stdscr, app.palette
        d = self.drill
        assert d is not None
        W.addstr(win, y, x, (f"{d.board.name if d.board else 'board'} @ {d.address}")[:w], pal["title"])
        if d.transport != "serial":
            W.addstr(win, y + 2, x, "Introspection is available over serial only.", pal["muted"])
            return
        if not self.entries:
            for i, ln in enumerate([
                "No devices registered on this board.",
                "",
                "Devices are added at runtime by a script.",
                "To keep them after the script ends, call",
                "board.save_devices() -- it persists them to",
                "EEPROM, and the board reloads them on boot.",
            ]):
                W.addstr(win, y + 2 + i, x, ln[:w], pal["muted"])
            return
        W.addstr(win, y + 2, x, f"{'id':<4}{'device':<15}pins", pal["muted"])
        r = y + 3
        for e in self.entries:
            if r >= y + h:
                break
            W.addstr(win, r, x, f"{e.dev_id:<4}", pal["accent"])
            W.addstr(win, r, x + 4, e.name[:14].ljust(15), pal["normal"])
            W.addstr(win, r, x + 19, e.pins[: max(0, w - 19)], pal["ok"])
            r += 1

    def draw_detail(self, app: App, y: int, x: int, h: int, w: int) -> None:
        if self.mode == "detail":
            self._draw_devices(app, y, x, h, w)
        else:
            self._draw_topology(app, y, x, h, w)

    def handle_back(self, app: App) -> bool:
        if self.mode == "detail":
            self.mode, self.drill, self.right_title = "overview", None, "Topology"
            self._overview_menu()
            return True
        return False

    def _ping(self, app: App, d: Detected | None) -> None:
        if d is None:
            return
        app.log.append(f"$ ping {d.address}")
        res = probe_serial(d.address) if d.transport == "serial" else d
        if res.responds and res.info is not None:
            app.log.append(f"  {theme.OK_GLYPH} reachable — proto v{res.info.version}, "
                           f"{res.info.device_count} device(s)")
        else:
            app.log.append(f"  {theme.BAD_GLYPH} unreachable ({res.error})")

    def _ping_all(self, app: App) -> None:
        for d in self.found:
            self._ping(app, d)

    def on_select(self, app: App, item: W.MenuItem) -> None:
        v = item.value
        if v == "back":
            app.go_home()
        elif v == "rescan":
            app.show_loading("Rescanning…")
            self._rescan(app)
        elif v == "toggle_i2c":
            self.include_i2c = not self.include_i2c
            app.show_loading("Rescanning…")
            self._rescan(app)
        elif v == "ping_all":
            if not self.found:
                app.log.append("  (no boards to ping)")
            app.run_action(item, lambda: self._ping_all(app))
        elif v == "ping_one":
            app.run_action(item, lambda: self._ping(app, self.drill))
        elif v == "to_overview":
            self.handle_back(app)
        elif isinstance(v, tuple) and v[0] == "board":
            self._open_detail(app, v[1])

class StoragePage(DetailPage):
    title = "Storage manager"
    left_title = "Target"
    right_title = "Usage"
    loading = "Reading connected boards…"

    def __init__(self) -> None:
        super().__init__()
        # right-panel state: list of (label, used, total, unit)
        self.bars: list[tuple[str, int, int, str]] = []
        self.note = "Select a board to compile its footprint, or a live board for slots."

    def on_enter(self, app: App) -> None:
        self._build(app)

    def _build(self, app: App) -> None:
        items = [W.MenuItem(f"Firmware · {b.name}", ("fw", key))
                 for key, b in BOARDS.items()]
        for d in scan_serial():
            if d.responds:
                items.append(W.MenuItem(f"Slots · {d.label}", ("slots", d)))
        items += [W.MenuItem("Rescan boards", "rescan"), W.MenuItem("Back", "back")]
        self.menu.set_items(items)

    def draw_detail(self, app: App, y: int, x: int, h: int, w: int) -> None:
        if not self.bars:
            W.addstr(app.stdscr, y, x, self.note, app.palette["muted"])
            return
        row = y
        for label, used, total, unit in self.bars:
            free = total - used
            pct = (used / total * 100) if total else 0.0
            W.addstr(app.stdscr, row, x, label, app.palette["title"])
            W.draw_bar(app.stdscr, row + 1, x, min(w, theme.BAR_WIDTH), used, total, app.palette)
            info = f"{used:,} / {total:,} {unit}  ·  {pct:.1f}%  ·  {free:,} free"
            W.addstr(app.stdscr, row + 2, x, info[:w], app.palette["muted"])
            row += 4

    def on_select(self, app: App, item: W.MenuItem) -> None:
        if item.value == "back":
            app.go_home()
            return
        if item.value == "rescan":
            self._build(app)
            return
        kind, target = cast("tuple[str, object]", item.value)
        if kind == "fw":
            board = BOARDS[cast(str, target)]
            app.log.append(f"$ compile footprint · {board.name}")
            try:
                fp = op_storage.compile_footprint(board)
            except RuntimeError as e:
                app.log.append("  ! " + e.args[0].splitlines()[-1])
                return
            self.bars = [(k, u, t, "B") for k, (u, t) in fp.items()]
            for k, (u, t) in fp.items():
                app.log.append(f"  {k}: {u:,} / {t:,} B")
        elif kind == "slots":
            d = cast(Detected, target)
            slots = op_storage.device_slots(d)
            if slots is None:
                app.log.append("  ! board did not report a slot count")
                return
            self.bars = [(f"Device slots · {d.label}", slots[0], slots[1], "slots")]

class FlashPage(DetailPage):
    title = "Flash Arduinos"
    left_title = "Configure"
    right_title = "Command"
    hints = "↑↓ field · ←→ change · Enter apply/flash · Esc back · q quit"

    def __init__(self) -> None:
        super().__init__()
        self.board = "mega"
        self.ports: list[str] = discover_serial_ports() or ["/dev/ttyUSB0"]
        self.port = self.ports[0]
        self.i2c: int | None = None
        self.compile_only = False
        self._rebuild()

    def _rebuild(self) -> None:
        i2c = "off" if self.i2c is None else str(self.i2c)
        keep = self.menu.selected
        self.menu.set_items([
            W.MenuItem(f"Board", "board", self.board, multi=True),
            W.MenuItem(f"Port", "port", self.port, multi=True),
            W.MenuItem(f"I2C address", "i2c", i2c, multi=True),
            W.MenuItem(f"Compile only", "compile", "yes" if self.compile_only else "no", multi=True),
            W.MenuItem("Flash now", "flash"),
            W.MenuItem("Rescan ports", "rescan"),
            W.MenuItem("Back", "back"),
        ])
        self.menu.selected = min(keep, len(self.menu.items) - 1)

    def _command(self) -> list[str]:
        return op_flash.flash_command(self.board, self.port, self.i2c, self.compile_only)

    def draw_detail(self, app: App, y: int, x: int, h: int, w: int) -> None:
        summary = [
            ("Board", BOARDS[self.board].name),
            ("FQBN", BOARDS[self.board].fqbn),
            ("Transport", "I2C @ %s" % self.i2c if self.i2c is not None else "serial"),
            ("Port", "-" if self.i2c is not None or self.compile_only else self.port),
            ("Upload", "no (compile only)" if self.compile_only else "yes"),
        ]
        for i, (k, v) in enumerate(summary):
            W.addstr(app.stdscr, y + i, x, f"{k:<11}", app.palette["muted"])
            W.addstr(app.stdscr, y + i, x + 12, v[: max(0, w - 12)], app.palette["normal"])
        cy = y + len(summary) + 1
        W.addstr(app.stdscr, cy, x, "Will run:", app.palette["muted"])
        cmd = " ".join(self._command()).replace(str(FLASH_SH), "./firmware/flash.sh")
        for j, chunk in enumerate([cmd[i:i + w] for i in range(0, len(cmd), max(1, w))]):
            W.addstr(app.stdscr, cy + 1 + j, x, chunk, app.palette["accent"])

    def on_adjust(self, app: App, item: W.MenuItem, delta: int) -> None:
        if item.value == "board":
            keys = list(BOARDS)
            self.board = keys[(keys.index(self.board) + delta) % len(keys)]
        elif item.value == "port":
            if self.ports:
                self.port = self.ports[(self.ports.index(self.port) + delta) % len(self.ports)]
        elif item.value == "i2c":
            choices: list[int | None] = [None, 8, 9, 10, 16]
            cur = choices.index(self.i2c) if self.i2c in choices else 0
            self.i2c = choices[(cur + delta) % len(choices)]
        elif item.value == "compile":
            self.compile_only = not self.compile_only
        self._rebuild()

    def on_select(self, app: App, item: W.MenuItem) -> None:
        if item.value == "back":
            app.go_home()
        elif item.value == "rescan":
            self.ports = discover_serial_ports() or ["/dev/ttyUSB0"]
            self.port = self.ports[0]
            self._rebuild()
            app.log.append(f"$ rescan ports -> {', '.join(self.ports)}")
        elif item.value == "flash":
            app.log.append("")
            app.run_action(item, lambda: op_flash.flash(
                app.runner(), self.board, self.port, self.i2c, self.compile_only))
        elif item.value in {"board", "port", "i2c", "compile"}:
            self.on_adjust(app, item, 1)          # Enter also cycles a field forward

class UsbGadgetPage(DetailPage):
    """Enable USB gadget mode on a Pi so it can be a HID gamepad / drive.

    Runs scripts/setup-usb-gadget.sh (via sudo). The detail panel explains what
    that one-time, root-only change does; a reboot is needed afterwards.
    """

    title = "USB gadget setup"
    left_title = "Action"
    right_title = "What it does"
    hints = "↑↓ move · Enter run · Esc back · q quit"

    def __init__(self) -> None:
        super().__init__()
        self.menu.set_items([
            W.MenuItem("Enable gadget mode (sudo)", "run"),
            W.MenuItem("Disable / revert (sudo)", "undo"),
            W.MenuItem("Back", "back"),
        ])

    def draw_detail(self, app: App, y: int, x: int, h: int, w: int) -> None:
        lines = [
            "Makes the Raspberry Pi able to present itself to a",
            "host PC as a USB gamepad (Gamepad) + drive (Storage).",
            "",
            "One-time, needs root + a reboot. It edits the Pi's",
            "boot config (safe to re-run; append-only):",
            "",
            f"  {theme.ARROW} config.txt:  dtoverlay=dwc2   (USB-OTG driver)",
            f"  {theme.ARROW} cmdline.txt: modules-load=dwc2,libcomposite",
            f"  {theme.ARROW} modprobe libcomposite         (load it now)",
            f"  {theme.ARROW} checks for mkfs.vfat (Storage image)",
            "",
            "After it runs:  sudo reboot, then connect the Pi's",
            "USB-OTG port to the host and run a Gamepad script.",
            "",
            "Disable / revert strips those two lines back out so",
            "the Pi behaves as a normal machine again (reboot).",
            "",
            "Only run this ON a Raspberry Pi. The panel needs",
            "passwordless sudo; otherwise run it in a terminal:",
            "  sudo ./scripts/setup-usb-gadget.sh [--undo]",
        ]
        for i, ln in enumerate(lines):
            attr = app.palette["muted"] if ln.startswith("  ") else app.palette["normal"]
            W.addstr(app.stdscr, y + i, x, ln[:w], attr)

    def on_select(self, app: App, item: W.MenuItem) -> None:
        if item.value == "back":
            app.go_home()
            return
        app.log.append("")
        if item.value == "undo":
            app.run_action(item, lambda: op_usbgadget.undo(app.runner()))
        else:
            app.run_action(item, lambda: op_usbgadget.setup(app.runner()))

class I2cPage(DetailPage):
    """Turn the Pi's I2C bus on/off -- what `I2CLink` needs to reach Arduinos.

    Runs scripts/setup-i2c.sh (via sudo). Like the USB gadget page, it is a
    one-time, root-only boot-config change that needs a reboot.
    """

    title = "I2C setup"
    left_title = "Action"
    right_title = "What it does"
    hints = "↑↓ move · Enter run · Esc back · q quit"

    def __init__(self) -> None:
        super().__init__()
        self.menu.set_items([
            W.MenuItem("Enable I2C bus (sudo)", "run"),
            W.MenuItem("Disable / revert (sudo)", "undo"),
            W.MenuItem("Back", "back"),
        ])

    def draw_detail(self, app: App, y: int, x: int, h: int, w: int) -> None:
        lines = [
            "Turns on the Pi's ARM I2C controller, so RATA can",
            "drive Arduinos over two wires with I2CLink(bus=1).",
            "",
            "One-time, needs root + a reboot. It changes:",
            "",
            f"  {theme.ARROW} config.txt:   dtparam=i2c_arm=on  (creates /dev/i2c-1)",
            f"  {theme.ARROW} /etc/modules: i2c-dev             (exposes the bus)",
            f"  {theme.ARROW} apt install i2c-tools             (i2cdetect)",
            f"  {theme.ARROW} adds you to the i2c group         (use it as non-root)",
            "",
            "After it runs:  sudo reboot, then check the board",
            "answers:  i2cdetect -y 1   (shows its --i2c address)",
            "",
            "Wiring: SDA = GPIO2 (pin 3), SCL = GPIO3 (pin 5),",
            "plus a COMMON GROUND. The Pi is 3.3V and NOT",
            "5V-tolerant -- put a level shifter between it and a",
            "5V Arduino, or use a 3.3V board.",
            "",
            "Disable / revert removes exactly those two lines",
            "again (i2c-tools and the group are left alone).",
        ]
        for i, ln in enumerate(lines):
            attr = app.palette["muted"] if ln.startswith("  ") else app.palette["normal"]
            W.addstr(app.stdscr, y + i, x, ln[:w], attr)

    def on_select(self, app: App, item: W.MenuItem) -> None:
        if item.value == "back":
            app.go_home()
            return
        app.log.append("")
        if item.value == "undo":
            app.run_action(item, lambda: op_i2c.undo(app.runner()))
        else:
            app.run_action(item, lambda: op_i2c.setup(app.runner()))

class TestsPage(DetailPage):
    title = "Run tests"
    left_title = "Suite"
    right_title = "About"
    hints = "↑↓ move · Enter run · v verbose · Esc back · q quit"

    def __init__(self) -> None:
        super().__init__()
        self.verbose = False
        self._build()

    def _build(self) -> None:
        keep = self.menu.selected
        items = [W.MenuItem("Run all tests", "all")]
        items += [W.MenuItem(name, ("one", name)) for name in op_tests.list_suites()]
        items += [
            W.MenuItem("Verbose", "verbose", "on" if self.verbose else "off", multi=True),
            W.MenuItem("Back", "back"),
        ]
        self.menu.set_items(items)
        self.menu.selected = min(keep, len(self.menu.items) - 1)

    def draw_detail(self, app: App, y: int, x: int, h: int, w: int) -> None:
        lines = [
            "Unit tests for the ratapy framework (pytest).",
            "",
            "  Run all tests   → the whole suite",
            "  <a test file>   → just that module",
            f"  Verbose         → {'-v' if self.verbose else '-q'} output",
            "",
            "Results stream into the Log below; the final",
            "line is pytest's pass/fail summary.",
        ]
        for i, ln in enumerate(lines):
            W.addstr(app.stdscr, y + i, x, ln[:w], app.palette["normal"])

    def on_adjust(self, app: App, item: W.MenuItem, delta: int) -> None:
        if item.value == "verbose":
            self.verbose = not self.verbose
            self._build()

    def on_select(self, app: App, item: W.MenuItem) -> None:
        if item.value == "back":
            app.go_home()
        elif item.value == "verbose":
            self.verbose = not self.verbose
            self._build()
        elif item.value == "all":
            app.log.append("")
            app.run_action(item, lambda: op_tests.run(app.runner(), verbose=self.verbose))
        else:
            _kind, name = cast("tuple[str, str]", item.value)
            app.log.append("")
            app.run_action(item, lambda: op_tests.run(
                app.runner(), selection=name, verbose=self.verbose))
