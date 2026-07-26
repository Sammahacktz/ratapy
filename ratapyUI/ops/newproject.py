#!/usr/bin/env python3
"""Scaffold a RATA project: a venv with ratapy already importable.

    python -m ratapyUI.ops.newproject myapp     # or: rata start-project myapp

RATA itself lives in a private environment (~/.local/share/rata) that the user
should never install into -- `rata update` re-syncs it and would drop their
packages. So a project gets its OWN venv, with ratapy installed **editable** from
the RATA install: no second copy of the source, `rata update` reaches the project
too, and the editor resolves `from ratapy import ...` because it is in the venv it
already looks at.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from .common import REPO_ROOT
from .runner import CommandRunner

# ratapy's requires-python floor. Debian 12 / Raspberry Pi OS Bookworm ship
# exactly this, which is what lets a project venv sit on the system interpreter
# (and therefore see apt's packages) and still run RATA.
MIN_PYTHON = (3, 11)

STARTER = '''"""A first RATA script -- blink the LED on pin 13.

Run it with:   {venv}/bin/python main.py     (or activate the venv first)
Flash the board first:  ratapyui  ->  Flash Arduinos
"""

from ratapy import Raspberry
from ratapy.boards import Mega
from ratapy.devices import LED


def main() -> None:
    # `with` closes the serial port when the block ends.
    with Raspberry(port="/dev/ttyUSB0") as rp:
        board = Mega("A")            # Uno("A") / Nano("A") / Leonardo("A") / ...
        rp.register_arduino(board)

        led = LED(pin=13, board=board)
        led.blink(3)                 # runs on the board, non-blocking
        led.wait()                   # block until it has finished


if __name__ == "__main__":
    main()
'''

VSCODE_SETTINGS = """{{
    "python.defaultInterpreterPath": "${{workspaceFolder}}/{venv}/bin/python"
}}
"""

GITIGNORE = "{venv}/\n__pycache__/\n"


# The distro interpreter, by absolute path -- deliberately NOT `which python3`.
# apt installs into /usr/lib/python3/dist-packages, which belongs to THIS one; a
# python3 earlier on PATH (/usr/local/bin, pyenv, conda) owns none of it, so
# building there would expose no apt packages while appearing to work.
SYSTEM_PYTHON = Path("/usr/bin/python3")


def _base_python(runner: CommandRunner, system_site: bool) -> str:
    """The interpreter the project venv is built on.

    This is the whole trick behind --system-site-packages actually working: only a
    venv based on the distro interpreter can see apt's packages. RATA's own
    interpreter (sys.executable) is a standalone uv build whose site-packages holds
    nothing from apt, so a venv based on it sees no system packages whatever flags
    you pass. Falls back to it (loudly) when the distro one is unusable.
    """
    if not system_site:
        return sys.executable

    def fallback(why: str) -> str:
        runner.log(f"  ! {why} -- building on RATA's own interpreter instead")
        runner.log("    (apt-installed packages will NOT be importable; this is what --isolated does)")
        return sys.executable

    if not SYSTEM_PYTHON.exists():
        return fallback(f"no {SYSTEM_PYTHON}")
    probe = subprocess.run(
        [str(SYSTEM_PYTHON), "-c",
         "import sys; v = sys.version_info; print(v.major, v.minor, v.releaselevel)"],
        capture_output=True, text=True)
    if probe.returncode != 0:
        return fallback(f"{SYSTEM_PYTHON} is not runnable")
    major, minor, level = probe.stdout.split()
    version = (int(major), int(minor))
    if version < MIN_PYTHON:
        need = ".".join(str(n) for n in MIN_PYTHON)
        return fallback(f"{SYSTEM_PYTHON} is {major}.{minor}, ratapy needs >= {need}")
    if level != "final":
        # A pre-release ships a packaging that raises InvalidVersion('0.dev0') and
        # breaks every pip install made in the venv.
        return fallback(f"{SYSTEM_PYTHON} is a pre-release ({major}.{minor} {level})")
    return str(SYSTEM_PYTHON)


def _create_venv(runner: CommandRunner, venv: Path, prompt: str, system_site: bool) -> int:
    """Create the project venv, preferring uv (install.sh always provides it).

    uv is not just faster here: the `venv` module in RATA's own interpreter writes
    a prompt that ALREADY contains parentheses and lets activate add its own, so
    the shell shows "((name) )". uv's activate parenthesises exactly once. `--seed`
    puts pip in the venv, so the project works with plain `pip install` too.
    """
    base = _base_python(runner, system_site)
    extra = ["--system-site-packages"] if system_site else []
    uv = shutil.which("uv")
    if uv is not None:
        return runner.run([uv, "venv", "--seed", "--python", base,
                           "--prompt", prompt, *extra, str(venv)])
    # No uv: stdlib venv still works, the prompt may just look doubled.
    return runner.run([base, "-m", "venv", "--prompt", prompt, *extra, str(venv)])


def start_project(runner: CommandRunner, path: Path, system_site: bool = True) -> int:
    """Create <path> with a venv that has ratapy installed. Returns 0 on success.

    ``system_site`` (the default) builds on the system python3 and exposes apt's
    packages, so things like python3-dbus / python3-picamera2 are importable
    alongside ratapy. Pass False for an isolated venv on RATA's own interpreter.
    """
    target = path.expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        runner.log(f"  ! {target} already exists and is not empty")
        return 1

    # Named after the project, so an activated shell says (myapp_venv) rather than
    # a generic (.venv) shared by every project you have open.
    venv_name = f"{target.name}_venv"
    runner.log(f"Creating project at {target}")
    target.mkdir(parents=True, exist_ok=True)

    venv = target / venv_name
    if _create_venv(runner, venv, venv_name, system_site) != 0:
        runner.log("  ! could not create the virtual environment")
        return 1

    # Editable, so the project follows `rata update` instead of pinning a copy.
    runner.log("")
    runner.log(f"Installing ratapy (editable, from {REPO_ROOT}) -- this pulls its deps…")
    if runner.run([str(venv / "bin" / "pip"), "install", "--quiet", "-e", str(REPO_ROOT)]) != 0:
        runner.log("  ! could not install ratapy into the project venv")
        return 1

    (target / "main.py").write_text(STARTER.format(venv=venv_name))
    (target / ".gitignore").write_text(GITIGNORE.format(venv=venv_name))
    vscode = target / ".vscode"
    vscode.mkdir(exist_ok=True)
    (vscode / "settings.json").write_text(VSCODE_SETTINGS.format(venv=venv_name))

    runner.log("")
    runner.log(f"Ready. {target.name}/ now has:")
    kind = "sees apt's packages too" if system_site else "isolated"
    runner.log(f"  {venv_name}/{' ' * max(1, 18 - len(venv_name))}its own environment, ratapy installed ({kind})")
    runner.log("  main.py            a starter script (blink an LED)")
    runner.log("  .vscode/           points VS Code at the venv, so imports resolve")
    runner.log("")
    runner.log("Next:")
    runner.log(f"  cd {target}")
    runner.log(f"  source {venv_name}/bin/activate   # then plain `python` / `pip` are the project's")
    runner.log("  python main.py")
    runner.log("")
    runner.log("Add your own packages with `pip install <pkg>` while it is active.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scaffold a RATA project (venv + ratapy)")
    ap.add_argument("path", nargs="?", default=".",
                    help="target directory (default: the current one)")
    ap.add_argument("--isolated", action="store_true",
                    help="do not expose apt's system packages in the venv")
    args = ap.parse_args(argv)
    return start_project(CommandRunner(), Path(args.path), system_site=not args.isolated)


if __name__ == "__main__":
    raise SystemExit(main())
