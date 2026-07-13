"""BackgroundTasks -- run device work on threads, without the thread boilerplate.

RATA's blocking calls are the clearest way to write a sequence.
Put the sequence on a background thread and both are true at once::

    with BackgroundTasks() as tasks:

        @tasks.run
        def arm():
            while not tasks.stopping:
                stepper.step(500)
                stepper.wait()            # blocks THIS thread only
                stepper.step(-500)
                stepper.wait()

        while not done:                   # main loop stays live throughout
            servo.angle(angle_from(joystick.y))
            time.sleep(0.02)

The block owns the lifecycle: tasks start when submitted, are asked to stop when
it exits, and are joined before it returns. Nothing is deferred or rewritten --
inside a task, every RATA call behaves exactly as it always has.

**Errors are the main reason to use this over a raw thread.** A bare
``threading.Thread`` whose target raises prints a traceback to stderr and dies,
while your program carries on with no idea a limb stopped moving. Here the
exception is captured and re-raised when the block exits.

Thread safety: the wire is serialised by the Link's own lock, so several threads
can drive devices at once. 
Two rules, though:

* **Create devices on the main thread**, before starting tasks. Registration is
  not atomic -- two threads can claim the same device id.
* **Give each task its own devices** where you can. Sharing one device across
  threads is safe on the wire, but its Python-side bookkeeping (an LED's
  ``is_on``, a Button's hold clock) can interleave.

Also keep the block *inside* your ``with Raspberry(...)`` block, so tasks are
stopped before the links close -- a task blocked in ``wait()`` on a closed port
would raise.

How many tasks?
A thread costs an OS stack (8 MB of *address space* by default, but only the few
KB it actually touches in RAM). The ceiling is memory, not a thread quota: even a
Pi Zero handles dozens comfortably. What actually goes wrong is spawning one per
event::

    while True:                      # DON'T
        if button.is_pressed:
            tasks.run(do_the_thing)  # a new thread every 20 ms

Use a few **long-lived** tasks that loop instead -- one per thing that moves::

    @tasks.run                       # DO
    def arm():
        while not tasks.stopping:
            if button.is_pressed:
                do_the_thing()
            tasks.sleep(0.02)

A finished task frees its thread by itself. If you want the mistake to fail loudly rather
than gradually, cap it: ``BackgroundTasks(max_workers=4)`` refuses to start a
fifth concurrent task.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from types import TracebackType
from typing import Any

Task = Callable[..., Any]


class BackgroundTasks:
    """A group of background threads with a shared stop signal.

    Use it as a context manager; submit work with :meth:`run`. See the module
    docstring for the whole picture.
    """

    def __init__(self, join_timeout: float = 5.0,
                 max_workers: int | None = None) -> None:
        #: How long __exit__ waits for a task to notice `stopping` and return.
        self.join_timeout = join_timeout
        #: Refuse to start more than this many tasks AT ONCE (None = no limit).
        self.max_workers = max_workers
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._errors: list[BaseException] = []
        self._lock = threading.Lock()
        self._entered = False

    def _reap(self) -> None:
        """Drop finished threads. The OS reclaims a thread when its function
        returns; this just stops us holding the dead Thread objects for the life
        of the block, which would grow without bound in a submit-per-event loop.
        """
        self._threads = [t for t in self._threads if t.is_alive()]

    # --- submitting work --------------------------------------------------

    def run(self, fn: Task, *args: Any, **kwargs: Any) -> Task:
        """Start `fn(*args, **kwargs)` on its own thread. Returns `fn`.

        Arguments are passed straight through, which is the tidy way to give a
        task the devices it owns instead of reaching for globals::

            def gripper(trigger, left, right):
                while not tasks.stopping:
                    if trigger.was_pressed:
                        ...

            tasks.run(gripper, btn, stepper_L, stepper_R)
            tasks.run(gripper, trigger=btn, left=stepper_L, right=stepper_R)

        With no arguments it works as a decorator, which is handier when the task
        closes over what it needs::

            @tasks.run
            def spin():
                ...

        The same function can be started more than once with different arguments
        -- one task per limb, say -- since each call gets its own thread.
        """
        if not self._entered:
            # False in two cases: never opened, or already closed. Either way
            # there is nothing to stop or join the thread, so refuse.
            raise RuntimeError(
                "BackgroundTasks is not open -- run() needs an active group. "
                "Use `with BackgroundTasks() as tasks:`, or `tasks.start()` "
                "first (and `tasks.close()` when done). If you already called "
                "close(), start() a fresh group."
            )
        if self._stop.is_set():
            raise RuntimeError("this BackgroundTasks group is already stopping")

        self._reap()                       # finished tasks free their slot
        if self.max_workers is not None and len(self._threads) >= self.max_workers:
            raise RuntimeError(
                f"max_workers={self.max_workers} reached ({len(self._threads)} "
                f"running) -- cannot start {fn.__name__!r}. Prefer a few "
                "long-lived tasks that loop, over one task per event."
            )

        def wrapper() -> None:
            try:
                fn(*args, **kwargs)
            except BaseException as e:      # noqa: BLE001 -- re-raised in close()
                with self._lock:
                    self._errors.append(e)
                self._stop.set()            # one task failing stops its siblings

        label = getattr(fn, "__name__", type(fn).__name__)
        # daemon: a task that ignores `stopping` must never wedge interpreter exit.
        thread = threading.Thread(target=wrapper, name=f"rata-task-{label}",
                                  daemon=True)
        self._threads.append(thread)
        thread.start()
        return fn


    @property
    def stopping(self) -> bool:
        """True once the block is exiting (or a sibling task failed).

        Long-running tasks should check this instead of looping forever::

            while not tasks.stopping:
                ...
        """
        return self._stop.is_set()

    def stop(self) -> None:
        """Ask every task to stop, without waiting for them."""
        self._stop.set()

    def sleep(self, seconds: float) -> bool:
        """Sleep, but wake immediately if the group is stopping.

        Use this instead of ``time.sleep()`` inside a task, so a long pause does
        not hold up shutdown. Returns True if it was cut short by a stop.
        """
        return self._stop.wait(seconds)

    @property
    def running(self) -> int:
        """How many tasks are still alive (finished ones are dropped as we look)."""
        self._reap()
        return len(self._threads)


    def start(self) -> "BackgroundTasks":
        """Open the group without a ``with`` block. Returns self, so::

            tasks = BackgroundTasks().start()
            ...
            tasks.close()          # you MUST call this yourself

        Prefer the context manager -- it calls close() even when your code
        raises. This form is for when the group has to outlive one scope (a
        class that owns it, say, closing it in its own teardown).
        """
        self._entered = True
        return self

    def close(self, *, reraise: bool = True) -> None:
        """Stop every task, wait for them, and report what went wrong.

        The manual counterpart to leaving the ``with`` block: safe to call twice,
        and after it the group is closed for new work. Pass ``reraise=False`` to
        tear down without re-raising a task's exception -- only useful when you
        are already handling an error of your own and don't want it masked.
        """
        self._stop.set()
        stuck = []
        for thread in self._threads:
            thread.join(timeout=self.join_timeout)
            if thread.is_alive():
                stuck.append(thread.name)
        self._threads = [t for t in self._threads if t.is_alive()]
        self._entered = False

        if stuck:
            # Daemon threads, so this cannot hang the program -- but a task that
            # never checks `stopping` is a bug worth naming. Raised even under
            # reraise=False: it is about YOUR task misbehaving, not about which
            # exception wins.
            raise RuntimeError(
                f"background task(s) did not stop within {self.join_timeout}s: "
                f"{', '.join(stuck)} -- a long-running task must check "
                "`tasks.stopping` (and use `tasks.sleep()` rather than time.sleep)"
            )
        if reraise:
            with self._lock:
                errors, self._errors = list(self._errors), []
            if errors:
                raise errors[0]

    def __enter__(self) -> "BackgroundTasks":
        return self.start()

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None, tb: TracebackType | None) -> None:
        # An exception in the `with` body wins: it came first and is what the
        # user is looking at. Task errors surface only when the body was clean.
        self.close(reraise=exc_type is None)
