#!/usr/bin/env python3
"""The install.sh lifecycle commands (check / update / uninstall), as functions.

All the real logic (git fetch/compare, checkout, uv sync, removal) lives in
``install.sh``; this only shells out to it so the control panel's "Find updates"
page and the ``rata`` CLI can stream the output -- one implementation, three
front-ends. ``pre=True`` tracks master instead of the latest release tag
(install.sh --pre-release).

    python -m ratapyUI.ops.updates              # check only    (install.sh --check)
    python -m ratapyUI.ops.updates --update     # apply          (install.sh --update)
    python -m ratapyUI.ops.updates --pre        #   ... track master (pre-release)
    python -m ratapyUI.ops.updates --uninstall  # remove         (install.sh --uninstall)
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .common import INSTALL_SH
from .runner import CommandRunner

# install.sh --check exits 10 when a newer version is available (0 = up to date).
UPDATE_AVAILABLE = 10


def _pre(pre: bool) -> tuple[str, ...]:
    return ("--pre-release",) if pre else ()


def _install_sh(runner: CommandRunner, flag: str, home: Path | None = None,
                extra: Sequence[str] = (), ok_codes: tuple[int, ...] = (0,)) -> int:
    """Run ``install.sh <flag> [extra...]``.

    Targets the standard install at ~/.local/share/rata unless ``home`` overrides
    it (the panel's "this checkout" option, for a dev tree).
    """
    if not INSTALL_SH.exists():
        runner.log(f"  ! installer missing: {INSTALL_SH}")
        return 1
    cmd = ["bash", str(INSTALL_SH), flag, *extra]
    if home is not None:
        cmd = ["env", f"RATA_HOME={home}", *cmd]
    return runner.run(cmd, ok_codes=ok_codes)


def check_code(runner: CommandRunner, home: Path | None = None, pre: bool = False) -> int:
    """Run ``install.sh --check`` and return its exit code.

    0 = up to date, ``UPDATE_AVAILABLE`` = a newer version, anything else = the
    check failed (not installed, no remote, ...). Use this when you must tell a
    failure apart from "up to date"; `check` collapses both to False.
    """
    return _install_sh(runner, "--check", home, _pre(pre), (0, UPDATE_AVAILABLE))


def check(runner: CommandRunner, home: Path | None = None, pre: bool = False) -> bool:
    """True if a newer version is available (a failed check counts as no update)."""
    return check_code(runner, home, pre) == UPDATE_AVAILABLE


def update(runner: CommandRunner, home: Path | None = None, pre: bool = False) -> int:
    """Run ``install.sh --update``. Returns 0 on success."""
    return _install_sh(runner, "--update", home, _pre(pre))


def uninstall(runner: CommandRunner, home: Path | None = None,
              usb_gadget: bool = False) -> int:
    """Run ``install.sh --uninstall``: remove the RATA env + launchers.

    With ``usb_gadget`` it also reverts the Pi's USB-gadget boot config (needs sudo
    and a reboot); without it that config is left alone. Returns 0 on success.
    """
    return _install_sh(runner, "--uninstall", home,
                       ("--usb-gadget",) if usb_gadget else ())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RATA install lifecycle (check / update / uninstall)")
    ap.add_argument("--update", action="store_true", help="apply the update (default: just check)")
    ap.add_argument("--uninstall", action="store_true", help="remove the RATA env + launchers")
    ap.add_argument("--pre", action="store_true", help="track master (pre-release) instead of a release tag")
    ap.add_argument("--usb-gadget", action="store_true",
                    help="with --uninstall: also revert the USB gadget boot config")
    ap.add_argument("--home", type=Path, default=None,
                    help="target a specific RATA checkout instead of ~/.local/share/rata")
    args = ap.parse_args(argv)
    runner = CommandRunner()
    if args.uninstall:
        return uninstall(runner, args.home, args.usb_gadget)
    if args.update:
        return update(runner, args.home, args.pre)
    check(runner, args.home, args.pre)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
