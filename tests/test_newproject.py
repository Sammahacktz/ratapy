"""start-project: mirroring the Pi pip-extras into the new project venv.

The bug this guards: rpi_ws281x / sounddevice are pip-installed into the RATA
venv by `rata pi`, but a `start-project` venv is separate, so a NeoPixel/audio
project would hit "No module named rpi_ws281x". _mirror_pi_extras copies whatever
the RATA install has into the new venv.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

from ratapyUI.ops import newproject
from ratapyUI.ops.runner import CommandRunner


def _runner() -> tuple[CommandRunner, list[str], list[list[str]]]:
    log: list[str] = []
    ran: list[list[str]] = []
    r = CommandRunner(sink=log.append)
    r.run = lambda cmd, **kw: (ran.append([str(c) for c in cmd]) or 0)  # type: ignore[method-assign]
    return r, log, ran


def _fake_probe(present: set[str]):
    """subprocess.run stand-in: returncode 0 iff the imported pkg is 'present'."""
    class P:
        def __init__(self, rc: int) -> None:
            self.returncode = rc

    def run(cmd, **kw):  # type: ignore[no-untyped-def]
        pkg = cmd[-1].removeprefix("import ")
        return P(0 if pkg in present else 1)
    return run


def test_mirror_is_a_silent_noop_when_nothing_is_installed() -> None:
    r, log, ran = _runner()
    with patch.object(pathlib.Path, "exists", lambda self: True), \
         patch.object(newproject.subprocess, "run", _fake_probe(set())):
        newproject._mirror_pi_extras(r, pathlib.Path("/proj/venv"))
    assert log == []          # no noise
    assert ran == []          # nothing installed


def test_mirror_installs_only_what_the_rata_venv_has() -> None:
    r, log, ran = _runner()
    with patch.object(pathlib.Path, "exists", lambda self: True), \
         patch.object(newproject.subprocess, "run", _fake_probe({"rpi_ws281x"})):
        newproject._mirror_pi_extras(r, pathlib.Path("/proj/venv"))
    installs = [c for c in ran if "install" in c]
    assert len(installs) == 1
    assert installs[0][-1] == "rpi_ws281x"        # not sounddevice (absent)
    assert "/proj/venv/bin/pip" in installs[0][0]
    assert any("Mirroring" in ln for ln in log)


def test_mirror_installs_all_present_extras() -> None:
    r, log, ran = _runner()
    with patch.object(pathlib.Path, "exists", lambda self: True), \
         patch.object(newproject.subprocess, "run",
                      _fake_probe({"rpi_ws281x", "sounddevice"})):
        newproject._mirror_pi_extras(r, pathlib.Path("/proj/venv"))
    installs = [c for c in ran if "install" in c][0]
    assert "rpi_ws281x" in installs and "sounddevice" in installs


def test_mirror_skips_when_no_rata_venv() -> None:
    # A dev checkout without ~/.local/share/rata/.venv -> nothing to mirror.
    r, log, ran = _runner()
    with patch.object(pathlib.Path, "exists", lambda self: False):
        newproject._mirror_pi_extras(r, pathlib.Path("/proj/venv"))
    assert log == [] and ran == []
