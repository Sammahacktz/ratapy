# ratapyUI — the RATA control panel

A terminal UI (and a set of standalone scripts) for the whole
Arduino/Raspberry-Pi workflow: **install** dependencies, **list** connected
devices, inspect **storage** (firmware footprint + device slots), and **flash**
boards — all from one place, styled like `firmware/sizes.py`.

```
┌ Flash Arduinos ─────────────────────────────────────────────┐
│ ┌ Configure ──────────┐ ┌ Command ───────────────────────┐  │
│ │ › Board    < mega > │ │ Board      Mega 2560           │  │
│ │   Port  </dev/ttyU> │ │ Transport  serial              │  │
│ │   Flash now         │ │ Will run:                      │  │
│ └─────────────────────┘ │ ./firmware/flash.sh --board .. │  │
│                         └────────────────────────────────┘  │
├ Log ────────────────────────────────────────────────────────┤
│ $ ./firmware/flash.sh --board mega --port /dev/ttyUSB0       │
│ Sketch uses 14060 bytes (5%) ...                             │
└─────────────────────────────────────────────────────────────┘
  ↑↓ field · ←→ change · Enter apply/flash · Esc back · q quit
```

## Run it

```bash
rata ui                     # after install.sh (the installed launcher)
./ratapyui                  # from a repo checkout (uses uv if present)
uv run python -m ratapyUI   # equivalent
```

Navigate with the **arrow keys** (or `j`/`k`), **Enter**/**Space** to select,
**←/→** to change a field, **Esc**/**b** to go back, **q** to quit. **Mouse**
clicks select menu items where the terminal supports it. A **loading overlay**
appears while a page probes hardware.

The bottom **Log** pane is a live transcript: every command an action runs is
echoed there (`$ ...`) and its output streams in as it happens.

### Pages

- **Install RATA** — toolchain + Python deps (`--with-pi` option).
- **List devices** — a **topology overview**: the master and each board drawn as
  boxes joined by wires (name, firmware version, device count). Enter a board to
  drill into its registered devices *and the pins they're wired to* (read live
  from the firmware via `CMD_DEVICE_INFO`); `Ping all` / `Ping this board`
  re-check reachability.
- **Storage manager** — firmware footprint per board + live device slots.
- **Flash Arduinos** — a form with a live command preview, then flash.
- **Run tests** — runs the `ratapy` pytest suite (all, or one file; verbose
  toggle); results stream into the Log.

> **Serial caveat & the fix:** opening a USB-serial port *resets* most Arduinos
> (the DTR auto-reset, especially CH340 clones), which clears the devices they
> had registered **in RAM**. So the drill-down of a freshly scanned **serial**
> board shows *no* devices — connecting rebooted it. The fix is to **persist**:
> call `board.save_devices()` in your script and the board writes its registry to
> **EEPROM** and reloads it on every boot — so it survives the reset (and a
> power-cycle), and the panel then lists those devices even after your script has
> ended. Without saving, introspection only reflects the live RAM registry (I2C,
> which has no reset, or a single session).

## Every action is also a standalone script

You are never forced through the TUI — each action is runnable on its own, with
the same output going to your shell instead of the log pane:

```bash
python -m ratapyUI.ops.updates            # check for a newer release (install.sh --check)
python -m ratapyUI.ops.updates --update   #   ... and pull it       (install.sh --update)
python -m ratapyUI.ops.updates --pre      #   ... track master (pre-release) instead
python -m ratapyUI.ops.updates --home .   #   ... act on this checkout, not the install
python -m ratapyUI.ops.devices            # list serial devices
python -m ratapyUI.ops.devices --i2c      #   ... and scan the I2C bus
python -m ratapyUI.ops.storage            # firmware footprint per board
python -m ratapyUI.ops.storage --live     #   ... device slots on live boards
python -m ratapyUI.ops.flash --board mega # compile + upload
```

Installing RATA itself is `install.sh`'s job (a private runtime + venv, pinned
toolchain); the panel's "Find updates" page only *updates* an existing install.
For updates you normally just use the `rata` command — `rata check` / `rata
update` are the same calls with less typing.

(The `ops/*.py` files are marked executable, so `./ratapyUI/ops/devices.py`
works too.)

## Structure

```
ratapyUI/
  __main__.py     python -m ratapyUI -> launch the TUI
  app.py          the App shell: layout, event loop, Page / DetailPage bases
  pages.py        the concrete pages (Home, Updates, Devices, Storage, Flash)
  theme.py        glyphs, colours, ASCII wordmark, ANSI/text bars (no curses)
  tui/            reusable curses toolkit (no business logic)
    screen.py     colour palette, mouse, key names, curses bootstrap
    widgets.py    Box, Menu (keyboard+mouse), LogPane, usage bars
  ops/            the actual work -- dual-use (TUI + standalone CLI)
    runner.py     CommandRunner: run a command, stream lines to a sink (the log)
    common.py     repo paths, board table, serial/I2C device discovery
    updates.py    devices.py    storage.py    flash.py    usbgadget.py
../ratapyui        launcher script (repo root)
```

The split is deliberate: **`ops/` does the work** (and stays runnable on its
own), **`tui/` draws**, and **`app.py` + `pages.py` are thin glue**. A page
arranges widgets and calls an op; it holds no logic of its own.

## Extending it

- **A new action:** add `ops/<name>.py` with a `main(argv)` CLI plus functions
  that take a `CommandRunner`. Then add a `DetailPage` subclass in `pages.py`
  (set `menu` items, implement `draw_detail` + `on_select`) and a home-menu
  entry. Keep the op independently runnable.
- **A new widget:** put it in `tui/widgets.py` — it should only draw and hold its
  own state, taking a `(y, x, h, w)` rectangle and the palette.

## Notes

- Needs a real terminal (curses). Minimum size ~50×12; it tells you if smaller.
- `install`/`flash` shell out to `firmware/flash.sh` and `arduino-cli` (via
  `firmware/acli.sh`) — the same tools documented in
  [../docs/INSTALL.md](../docs/INSTALL.md).
- Device discovery uses `ratapy` to PING each serial port; the I2C scan needs a
  wired bus and returns nothing (not an error) when there isn't one.
