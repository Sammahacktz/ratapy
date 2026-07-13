"""CommandRunner -- run shell commands and stream their output line by line.

This is the single place a command actually gets executed, so the TUI's bottom
log and a standalone script show the *same* thing: the exact command, then its
output as it arrives. The TUI passes a sink that appends to its log pane; a
standalone script passes ``print`` (the default).
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from .common import REPO_ROOT

# A sink receives one already-formatted line at a time (no trailing newline).
Sink = Callable[[str], None]


class CommandRunner:
    """Executes commands from the repo root, emitting every line to a sink.

    Each command is echoed as ``$ the command`` before its output, so the log
    reads like a transcript of what RATA did on the user's behalf.
    """

    def __init__(self, sink: Sink | None = None, cwd: Path | None = None) -> None:
        self._sink: Sink = sink if sink is not None else print
        self._cwd = cwd or REPO_ROOT

    def log(self, line: str = "") -> None:
        """Emit a plain line to the sink (for notes, not command output)."""
        self._sink(line)

    def run(self, cmd: Sequence[str], echo: bool = True,
            ok_codes: Sequence[int] = (0,)) -> int:
        """Run ``cmd``, streaming stdout+stderr to the sink. Returns exit code.

        Never raises on a non-zero exit -- callers decide what a failure means and
        the code is surfaced in the log either way. ``ok_codes`` lists the exit
        codes that are *not* failures (for scripts that use a non-zero code to
        signal a normal outcome, e.g. install.sh --check = "update available").
        """
        argv = [str(a) for a in cmd]
        if echo:
            self._sink(f"$ {' '.join(shlex.quote(a) for a in argv)}")
        try:
            proc = subprocess.Popen(
                argv, cwd=str(self._cwd),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except FileNotFoundError:
            self._sink(f"  ! not found: {argv[0]}")
            return 127
        assert proc.stdout is not None
        for line in proc.stdout:
            self._sink(line.rstrip("\n"))
        code = proc.wait()
        if code not in ok_codes:
            self._sink(f"  ! exited with code {code}")
        return code
