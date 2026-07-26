"""The ``rata`` command -- a tiny dispatcher over RATA's sub-commands.

``install.sh`` writes a launcher for this into ~/.local/bin (the package ships no
console script of its own -- see pyproject), so the user has::

    rata doctor            # health check (ratapy.doctor)
    rata ui                # launch the control panel TUI (ratapyUI)
    rata start-project X   # scaffold X/: a venv with ratapy ready to import
    rata check             # is a newer released version available?
    rata update            # update to the latest release + re-sync deps
    rata uninstall         # remove the RATA env + launchers
    rata version           # print the installed version

plus every control-panel op, so nothing has to be run out of the install
directory (``rata flash --board uno --port /dev/ttyACM0`` instead of
``~/.local/share/rata/firmware/flash.sh ...``)::

    rata flash --board uno --port /dev/ttyACM0
    rata devices --i2c
    rata storage --live
    rata i2c / rata usb-gadget [--undo]
    rata test -v

It stays deliberately thin: each sub-command lives in its own module and is also
runnable directly (``python -m ratapyUI``, ``python -m ratapy.doctor``). The op
commands hand their arguments straight to that module's own ``main(argv)``, so
each flag is defined exactly once -- here they are only a name. The ops are
imported normally (the whole set costs one ``pyserial`` import, no curses/numpy),
which keeps ``OPS`` type-checked instead of a string lookup resolved at runtime.

``check`` / ``update`` / ``uninstall`` are the PATH-reachable front for
``install.sh --check`` / ``--update`` / ``--uninstall`` (which manages the install
at ~/.local/share/rata). They reuse ``ratapyUI.ops.updates`` rather than
duplicating it, so the CLI, the TUI's "Find updates" page and the script all do
exactly the same thing.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from importlib import metadata

from ratapyUI.ops import devices, flash, i2c, runtests, storage, usbgadget

# `rata <name> ...` -> that op's own main(rest). The op owns its arguments; this
# map is only the public name for it. Imported by hand rather than looked up by
# string, so a typo or a changed main() is a type error, not a runtime surprise.
OPS: dict[str, Callable[[list[str]], int]] = {
    "flash": flash.main,
    "devices": devices.main,
    "storage": storage.main,
    "i2c": i2c.main,
    "usb-gadget": usbgadget.main,
    "test": runtests.main,
}

_OPS_HELP = """
op commands (their own flags pass straight through; add --help to any of them):
  rata flash --board uno --port /dev/ttyACM0   compile + upload the firmware
  rata devices [--i2c]                         list connected boards
  rata storage [--live]                        firmware footprint / device slots
  rata i2c [--undo]                            enable/disable the Pi's I2C bus
  rata usb-gadget [--undo]                     enable/disable USB gadget mode
  rata test [-v]                               run the ratapy test-suite
"""


def _version() -> str:
    try:
        return metadata.version("ratapy")
    except metadata.PackageNotFoundError:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    args_in = list(sys.argv[1:] if argv is None else argv)
    # Dispatch op commands before argparse sees them: the op's own main() parses
    # the rest, so `rata flash --board uno` behaves exactly like
    # `python -m ratapyUI.ops.flash --board uno` -- one definition of each flag.
    if args_in and args_in[0] in OPS:
        # The op builds its own parser, and argparse takes prog from sys.argv[0]:
        # without this its --help would read "usage: cli.py ..." instead of the
        # command the user actually typed.
        argv0, sys.argv[0] = sys.argv[0], f"rata {args_in[0]}"
        try:
            return OPS[args_in[0]](args_in[1:])
        finally:
            sys.argv[0] = argv0

    parser = argparse.ArgumentParser(
        prog="rata", description="RATA command-line tools",
        epilog=_OPS_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-V", "--version", action="version", version=f"rata {_version()}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("doctor", help="check the installation and connected hardware")
    sub.add_parser("ui", help="launch the control panel TUI")
    for name, help_text in (
        ("check", "is a newer released version available?"),
        ("update", "update to the latest release + re-sync dependencies"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--pre-release", action="store_true",
                       help="track the master branch instead of the latest release tag")
    p = sub.add_parser("uninstall", help="remove the RATA env + launchers")
    p.add_argument("--usb-gadget", action="store_true",
                   help="also revert the USB gadget boot config (needs sudo + a reboot)")
    p = sub.add_parser("start-project", help="scaffold a new project (venv + ratapy)")
    p.add_argument("path", nargs="?", default=".",
                   help="target directory (default: the current one)")
    p.add_argument("--isolated", action="store_true",
                   help="do not expose apt's system packages (python3-dbus, picamera2, ...)")
    sub.add_parser("version", help="print the installed RATA version")

    args = parser.parse_args(args_in)

    if args.command == "doctor":
        from . import doctor
        return doctor.run()
    if args.command == "ui":
        from ratapyUI.app import main as ui_main
        return ui_main()
    if args.command == "start-project":
        from pathlib import Path

        from ratapyUI.ops import newproject
        from ratapyUI.ops.runner import CommandRunner
        return newproject.start_project(CommandRunner(), Path(args.path),
                                        system_site=not args.isolated)
    if args.command in ("check", "update", "uninstall"):
        from ratapyUI.ops import updates
        from ratapyUI.ops.runner import CommandRunner
        runner = CommandRunner()
        if args.command == "update":
            return updates.update(runner, pre=args.pre_release)
        if args.command == "uninstall":
            return updates.uninstall(runner, usb_gadget=args.usb_gadget)
        # Pass install.sh's code straight through, so `rata check` is scriptable
        # and a failed check stays distinct from "up to date" (0 / 10 / error).
        return updates.check_code(runner, pre=args.pre_release)
    if args.command == "version":
        print(f"rata {_version()}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
