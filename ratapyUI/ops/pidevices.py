#!/usr/bin/env python3
"""Install the Raspberry-Pi-only device libraries into this RATA install.

Adds camera (Picamera2 + libcamera), NeoPixel (rpi_ws281x) and audio
(sounddevice + PortAudio) support *after* the base install -- the same thing
`install.sh --pi` does at install time, without re-running the whole installer.

    python -m ratapyUI.ops.pidevices      # or: rata pi

Wraps scripts/setup-pi.sh (one implementation, shared with install.sh). The apt
part needs root: run this in a terminal so sudo can prompt, or set up passwordless
sudo -- from the TUI (no terminal) the script says so rather than hanging.
"""

from __future__ import annotations

import argparse

from .common import REPO_ROOT, SETUP_PI_SH
from .runner import CommandRunner


def setup(runner: CommandRunner) -> int:
    """Run scripts/setup-pi.sh against this install. Returns its exit code."""
    if not SETUP_PI_SH.exists():
        runner.log(f"  ! setup script missing: {SETUP_PI_SH}")
        return 1
    runner.log("Installing Pi device libraries (camera, NeoPixel, audio).")
    runner.log("The apt step needs root -- run this in a terminal if sudo prompts.")
    # RATA_HOME pins the script to THIS install's venv (REPO_ROOT is the install
    # dir), matching how ops/updates.py targets install.sh.
    return runner.run(["env", f"RATA_HOME={REPO_ROOT}", "bash", str(SETUP_PI_SH)])


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description="Install the Pi-only device libraries (camera, NeoPixel, audio)"
    ).parse_args(argv)
    return setup(CommandRunner())


if __name__ == "__main__":
    raise SystemExit(main())
