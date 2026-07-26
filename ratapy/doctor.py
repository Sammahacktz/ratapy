"""``rata doctor`` -- a health check for a RATA installation.

Prints one line per check so a user can see, at a glance, what is installed and
wired up and what still needs attention::

    rata doctor

Each line is prefixed with a status glyph: ``✓`` good, ``✗`` a problem worth
fixing, ``–`` not present / not applicable (e.g. a Pi-only feature on a laptop).
The command never changes anything; it only reports.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Literal

Status = Literal["ok", "bad", "na"]
GLYPH: dict[Status, str] = {"ok": "✓", "bad": "✗", "na": "–"}
COLOR: dict[Status, str] = {"ok": "\033[32m", "bad": "\033[31m", "na": "\033[90m"}
RESET = "\033[0m"


def _line(status: Status, text: str) -> None:
    glyph = GLYPH[status]
    if sys.stdout.isatty():
        glyph = f"{COLOR[status]}{glyph}{RESET}"
    print(f"{glyph} {text}")


def _arduino_cli() -> str | None:
    """Resolve the arduino-cli binary the same way firmware/acli.sh does."""
    env = os.environ.get("ARDUINO_CLI")
    if env and Path(env).exists():
        return env
    found = shutil.which("arduino-cli")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "arduino-cli"
    return str(local) if local.exists() else None


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 1, ""
    return p.returncode, p.stdout + p.stderr


def _check_version() -> None:
    try:
        _line("ok", f"RATA version {metadata.version('ratapy')}")
    except metadata.PackageNotFoundError:
        _line("na", "RATA version unknown (not installed as a package)")


def _check_python() -> None:
    v = sys.version_info
    status: Status = "ok" if (v.major, v.minor) >= (3, 12) else "bad"
    _line(status, f"Python {v.major}.{v.minor}.{v.micro}")


def _check_serial() -> None:
    try:
        import serial  # noqa: F401
        _line("ok", "Serial package available (pyserial)")
    except ImportError:
        _line("bad", "pyserial missing (pip/uv install)")


def _check_arduino_cli(cli: str | None) -> None:
    if cli is None:
        _line("bad", "Arduino CLI not found (install.sh installs it)")
        return
    code, out = _run([cli, "version"])
    ver = out.strip().split("Version:")[-1].split()[0] if "Version:" in out else "?"
    _line("ok" if code == 0 else "bad", f"Arduino CLI {ver}")


def _check_core(cli: str | None) -> None:
    if cli is None:
        _line("na", "arduino:avr core (needs Arduino CLI)")
        return
    _code, out = _run([cli, "core", "list"])
    _line("ok" if "arduino:avr" in out else "bad", "arduino:avr core installed")


def _check_libs(cli: str | None) -> None:
    if cli is None:
        _line("na", "Arduino libraries (needs Arduino CLI)")
        return
    _code, out = _run([cli, "lib", "list"])
    for lib in ("AccelStepper", "DHTStable"):
        _line("ok" if lib in out else "bad", f"{lib} installed")


def _check_dialout() -> None:
    try:
        import grp
        gid = grp.getgrnam("dialout").gr_gid
        members = set(grp.getgrnam("dialout").gr_mem) | {os.environ.get("USER", "")}
        in_group = gid in os.getgroups() or os.getlogin() in members
    except (KeyError, OSError):
        in_group = False
    _line("ok" if in_group else "bad", "User belongs to dialout")


def _check_serial_ports() -> None:
    ports = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    if not ports:
        _line("na", "No serial port present (plug in an Arduino)")
        return
    for port in ports:
        ok = os.access(port, os.R_OK | os.W_OK)
        _line("ok" if ok else "bad", f"{port} is accessible")


def _check_pi_camera() -> None:
    cli = shutil.which("libcamera-hello") or shutil.which("rpicam-hello")
    if cli is not None:
        code, out = _run([cli, "--list-cameras"])
        detected = code == 0 and "Available cameras" in out and "no cameras" not in out.lower()
        _line("ok" if detected else "na", "Raspberry Pi camera "
              + ("detected" if detected else "not detected"))
    else:
        _line("na", "Raspberry Pi camera not detected")


def _check_usb_gadget() -> None:
    udc = Path("/sys/class/udc")
    configured = udc.is_dir() and any(udc.iterdir())
    _line("ok" if configured else "na",
          "USB gadget mode " + ("configured" if configured else "not configured"))


def run() -> int:
    """Run every check, printing a line each. Always returns 0 (report-only)."""
    cli = _arduino_cli()
    _check_version()
    _check_python()
    _check_serial()
    _check_arduino_cli(cli)
    _check_core(cli)
    _check_libs(cli)
    _check_dialout()
    _check_serial_ports()
    _check_pi_camera()
    _check_usb_gadget()
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
