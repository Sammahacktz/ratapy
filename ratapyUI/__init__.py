"""ratapyUI -- a terminal control panel for the RATA project.

One place to install dependencies, list connected Arduinos, inspect firmware and
device storage, and flash boards -- as a curses TUI *and* as standalone scripts.

    ratapyui                          # launch the TUI
    python -m ratapyUI                # same thing
    python -m ratapyUI.ops.devices    # or run any action on its own

The TUI (``app`` + ``pages``) is pure glue over ``ratapyUI.ops`` (the real work)
and ``ratapyUI.tui`` (a small curses toolkit). See ratapyUI/README.md.
"""

__all__ = ["theme"]
__version__ = "0.1.0"
