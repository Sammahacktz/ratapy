"""ParallelExecutor -- collect device commands, fire them all at once.

Sending two commands normally puts milliseconds between them. When actions must
start together (two steppers moving in sync), collect them in an executor: each
command is *staged* on its board instead of executed, and ``execute()`` sends one
COMMIT per board -- the firmware then applies all staged writes in a single
loop() pass, microseconds apart.

Two equivalent styles::

    with ParallelExecutor():          # everything inside is staged...
        stepper1.step(20, speed=50)
        stepper2.step(20, speed=50)
    # ...and executed together here (skipped if the block raised)

    pe = ParallelExecutor()           # explicit form: bind devices to it
    stepper1.set_executor(pe)
    stepper2.set_executor(pe)
    stepper1.step(20, speed=50)       # queued, not executed
    stepper2.step(20, speed=50)
    pe.execute()                      # both start together
    stepper1.remove_executor()        # back to immediate commands
    stepper2.remove_executor()

Only *goal-setting* calls belong in an executor (step, on, off). Time-structured
helpers like ``LED.blink`` sleep between writes and make no sense staged. Nor
does ``Device.sleep()``, which is the exact opposite of an executor -- it puts a
gap between commands, while this removes them -- so it raises inside a block.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .boards import Arduino

# The executor a `with` block installs; Device._send picks it up automatically.
# A ContextVar (not a module global) so each thread/async task sees only the
# executor of ITS OWN `with` block -- two threads batching commands at the same
# time cannot leak writes into each other's queue.
_active_executor: ContextVar["ParallelExecutor | None"] = ContextVar(
    "rata_active_executor", default=None
)

def active_executor() -> "ParallelExecutor | None":
    """The executor installed by the innermost `with ParallelExecutor():`, if any."""
    return _active_executor.get()


class ParallelExecutor:
    """Batches device commands so they start (near-)simultaneously."""

    def __init__(self) -> None:
        self._queue: list[tuple[Arduino, int, bytes]] = []
        self._token: Token[ParallelExecutor | None] | None = None

    def add(self, board: "Arduino", dev_id: int, data: bytes) -> None:
        """Queue one write (called by Device._send, not usually by users)."""
        self._queue.append((board, dev_id, data))

    def execute(self) -> None:
        """Stage every queued write on its board, then commit all boards."""
        boards: list[Arduino] = []
        for board, dev_id, data in self._queue:
            board._stage(dev_id, data)
            if board not in boards:
                boards.append(board)
        self._queue.clear()
        for board in boards:
            board._commit()


    def __enter__(self) -> "ParallelExecutor":
        # set() returns a Token remembering the previous value; reset() in
        # __exit__ restores it, so nested `with` blocks unwind correctly.
        self._token = _active_executor.set(self)
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None, tb: TracebackType | None) -> None:
        if self._token is not None:
            _active_executor.reset(self._token)
            self._token = None
        if exc_type is None:
            self.execute()         
        else:
            self._queue.clear()   
