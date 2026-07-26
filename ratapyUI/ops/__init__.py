"""RATA operations -- the actual work behind each menu item.

Every module here is dual-use:

- importable by the TUI (functions take a :class:`~ratapyUI.ops.runner.CommandRunner`
  whose sink is the on-screen log), and
- runnable on its own as ``python -m ratapyUI.ops.<name> [args]`` (the sink is
  ``print``), so nobody is forced through the TUI.
"""
