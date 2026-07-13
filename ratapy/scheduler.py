"""Scheduler -- runs device commands at a due time, off the main thread.

This is what makes ``led.sleep(3)`` not block your script. A device's ``sleep()``
moves *that device's* cursor into the future; any command it sends after that is
handed here with its due time instead of going straight to the board, so the
script runs on and other devices keep their own timing::

    led.on(); led2.on()
    led.sleep(3);  led.off()      # queued for t+3, returns at once
    led2.sleep(1); led2.off()     # queued for t+1 -- led2 is off first

One thread per Raspberry, started on first use, running a heap of due times. The
work itself is tiny (write a frame), so one thread is plenty; the wire is
serialised by the Link's own lock, which is what makes it safe to send from here
while the main thread is sending too.

Errors don't get swallowed: a command that raises in the background is kept and
re-raised out of :meth:`drain` (so ``rp.wait()`` / leaving a ``with Raspberry()``
block reports it), because there is no caller left to catch it otherwise.
"""

from __future__ import annotations

import heapq
import itertools
import threading
import time
from collections.abc import Callable

Job = Callable[[], None]


class Scheduler:
    """A due-time queue with one worker thread. Not part of the public API --
    reach it through ``Raspberry.wait()`` and ``Device.sleep()``."""

    def __init__(self) -> None:
        # (due, tick, job): `tick` breaks ties so two commands queued for the
        # same instant keep the order they were written in.
        self._queue: list[tuple[float, int, Job]] = []
        self._tick = itertools.count()
        self._cv = threading.Condition()
        self._thread: threading.Thread | None = None
        self._closing = False
        self._running = 0                       # jobs mid-flight (see drain)
        self._errors: list[BaseException] = []

    # --- producer side ----------------------------------------------------

    def at(self, due: float, job: Job) -> None:
        """Run `job` when `time.monotonic()` reaches `due` (or now, if passed)."""
        with self._cv:
            if self._closing:
                raise RuntimeError("scheduler is closed")
            heapq.heappush(self._queue, (due, next(self._tick), job))
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._work, name="rata-scheduler", daemon=True)
                self._thread.start()
            self._cv.notify_all()

    @property
    def pending(self) -> int:
        """How many commands are still waiting (plus any mid-flight)."""
        with self._cv:
            return len(self._queue) + self._running

    # --- consumer side ----------------------------------------------------

    def drain(self, timeout: float | None = None) -> bool:
        """Block until every queued command has run. True if the queue emptied.

        Re-raises the first error a background command hit, once. Waiting here is
        what keeps a script alive long enough for its own timeline to play out --
        `Raspberry.close()` does it for you.
        """
        with self._cv:
            done = self._cv.wait_for(
                lambda: (not self._queue and not self._running) or self._closing,
                timeout)
            errors, self._errors = self._errors, []
        if errors:
            raise errors[0]
        return done

    def close(self) -> None:
        """Stop the worker, abandoning anything still queued (drain first)."""
        with self._cv:
            self._closing = True
            self._queue.clear()
            self._cv.notify_all()
            thread = self._thread
            self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    # --- the worker -------------------------------------------------------

    def _work(self) -> None:
        while True:
            with self._cv:
                while not self._queue and not self._closing:
                    self._cv.wait()
                if self._closing:
                    return
                due, _, job = self._queue[0]
                now = time.monotonic()
                if due > now:
                    # Sleep until it's due -- but on the condition, so a command
                    # queued for an EARLIER time wakes us and gets re-checked.
                    self._cv.wait(timeout=due - now)
                    continue
                heapq.heappop(self._queue)
                self._running += 1
            try:
                job()
            except BaseException as e:          # noqa: BLE001 - see module docs
                with self._cv:
                    self._errors.append(e)
            finally:
                with self._cv:
                    self._running -= 1
                    self._cv.notify_all()
