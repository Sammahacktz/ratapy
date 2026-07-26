#!/usr/bin/env python3
"""Run the ratapy unit-test suite (pytest), from the TUI or on its own.

    python -m ratapyUI.ops.runtests              # run everything, quietly
    python -m ratapyUI.ops.runtests -v           # verbose
    python -m ratapyUI.ops.runtests test_devices # only one file / node

Streams pytest's output through the shared runner, so the TUI's Log pane shows
exactly what `pytest` prints.
"""

from __future__ import annotations

import argparse
import sys

from .common import REPO_ROOT
from .runner import CommandRunner

TESTS_DIR = REPO_ROOT / "tests"


def list_suites() -> list[str]:
    """Names of the test files (``test_*.py``) available to run individually."""
    return sorted(p.stem for p in TESTS_DIR.glob("test_*.py"))


def pytest_command(selection: str | None = None, verbose: bool = False) -> list[str]:
    """Build the pytest command line (same interpreter as this process)."""
    cmd = [sys.executable, "-m", "pytest", "-v" if verbose else "-q"]
    if selection:
        # accept a bare file stem ("test_devices") or a full node id
        target = selection if "/" in selection or "::" in selection else f"tests/{selection}.py"
        cmd.append(target)
    return cmd


def run(runner: CommandRunner, selection: str | None = None, verbose: bool = False) -> int:
    """Run the suite, streaming to the runner's sink. Returns pytest's exit code."""
    return runner.run(pytest_command(selection, verbose))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the ratapy unit tests")
    ap.add_argument("selection", nargs="?", help="a test file stem or node id")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    return run(CommandRunner(), args.selection, args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
