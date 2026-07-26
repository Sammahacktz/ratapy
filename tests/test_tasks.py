"""BackgroundTasks -- threads for device work, with the lifecycle handled."""

from __future__ import annotations

import threading
import time

import pytest

from ratapy.boards import Uno
from ratapy.devices import LED
from ratapy.protocol import RataError
from ratapy.raspberry import Raspberry
from ratapy.tasks import BackgroundTasks
from tests.conftest import MockLink


@pytest.fixture
def rig() -> tuple[Raspberry, Uno, MockLink]:
    link = MockLink()
    rp = Raspberry(link=link)
    board = Uno("A", link=link)
    rp.register_arduino(board, verify=False)
    return rp, board, link


def test_a_task_runs_and_the_block_joins_it() -> None:
    ran = threading.Event()
    with BackgroundTasks() as tasks:
        tasks.run(ran.set)
    assert ran.is_set()                      # exit joined it, so this is settled


def test_run_works_as_a_decorator() -> None:
    ran = threading.Event()
    with BackgroundTasks() as tasks:
        @tasks.run
        def work() -> None:
            ran.set()
    assert ran.is_set()


def test_the_body_keeps_running_while_a_task_blocks() -> None:
    """The whole point: a blocking call in a task doesn't stop the main loop."""
    released = threading.Event()
    with BackgroundTasks() as tasks:
        @tasks.run
        def blocker() -> None:
            released.wait(2)                 # stands in for stepper.wait()

        spins = 0
        start = time.monotonic()
        while time.monotonic() - start < 0.15:
            spins += 1                       # the main loop is alive
            time.sleep(0.01)
        released.set()
    assert spins > 5


def test_several_tasks_run_at_once() -> None:
    seen: list[str] = []
    lock = threading.Lock()
    with BackgroundTasks() as tasks:
        for name in ("a", "b", "c"):
            def work(n: str = name) -> None:
                time.sleep(0.05)
                with lock:
                    seen.append(n)
            tasks.run(work)
    assert sorted(seen) == ["a", "b", "c"]


# --- the reason to use this over a raw thread -----------------------------

def test_a_failing_task_surfaces_at_the_block_exit() -> None:
    """A bare threading.Thread would print to stderr and die silently."""
    with pytest.raises(RataError, match="board fell off"):
        with BackgroundTasks() as tasks:
            @tasks.run
            def work() -> None:
                raise RataError("board fell off")
            time.sleep(0.05)


def test_a_raw_thread_really_does_swallow_it() -> None:
    # Pinning the behaviour that motivates the class: the exception never
    # reaches the caller, so the program carries on unaware.
    swallowed = []
    def hook(args: threading.ExceptHookArgs) -> None:
        swallowed.append(args.exc_value)
    old, threading.excepthook = threading.excepthook, hook
    try:
        t = threading.Thread(target=lambda: (_ for _ in ()).throw(RataError("boom")))
        t.start()
        t.join()                             # no exception raised here
    finally:
        threading.excepthook = old
    assert swallowed and isinstance(swallowed[0], RataError)


def test_one_failing_task_stops_its_siblings() -> None:
    sibling_saw_stop = threading.Event()
    with pytest.raises(RataError):
        with BackgroundTasks() as tasks:
            @tasks.run
            def sibling() -> None:
                while not tasks.stopping:
                    time.sleep(0.01)
                sibling_saw_stop.set()

            @tasks.run
            def failing() -> None:
                time.sleep(0.05)
                raise RataError("nope")

            time.sleep(0.2)
    assert sibling_saw_stop.is_set()


def test_an_error_in_the_body_wins_over_a_task_error() -> None:
    # The body's exception came first and is what the user is looking at.
    with pytest.raises(ValueError, match="from the body"):
        with BackgroundTasks() as tasks:
            @tasks.run
            def work() -> None:
                raise RataError("from the task")
            time.sleep(0.05)
            raise ValueError("from the body")


# --- stopping -------------------------------------------------------------

def test_stopping_ends_a_long_running_task() -> None:
    loops = [0]
    with BackgroundTasks() as tasks:
        @tasks.run
        def forever() -> None:
            while not tasks.stopping:        # the required shape
                loops[0] += 1
                tasks.sleep(0.01)
        time.sleep(0.1)
    assert loops[0] > 1                      # it ran...
    assert tasks.running == 0                # ...and it stopped


def test_stop_can_be_requested_early() -> None:
    with BackgroundTasks() as tasks:
        @tasks.run
        def forever() -> None:
            while not tasks.stopping:
                tasks.sleep(0.01)
        assert tasks.running == 1
        tasks.stop()
        time.sleep(0.05)
        assert tasks.running == 0


def test_tasks_sleep_wakes_early_on_stop() -> None:
    # time.sleep(5) in a task would hold up shutdown by 5 s; tasks.sleep does not.
    woke = threading.Event()
    start = time.monotonic()
    with BackgroundTasks() as tasks:
        @tasks.run
        def work() -> None:
            tasks.sleep(5)                   # cut short by the exit below
            woke.set()
        time.sleep(0.05)
    assert woke.is_set()
    assert time.monotonic() - start < 1      # nowhere near 5 s


def test_a_task_that_ignores_stopping_is_reported() -> None:
    with pytest.raises(RuntimeError, match="did not stop within"):
        with BackgroundTasks(join_timeout=0.1) as tasks:
            @tasks.run
            def rude() -> None:
                time.sleep(3)                # never checks `stopping`
            time.sleep(0.05)


def test_run_before_start_is_refused() -> None:
    tasks = BackgroundTasks()
    with pytest.raises(RuntimeError, match="not open"):
        tasks.run(lambda: None)


# --- with real devices ----------------------------------------------------

def test_a_task_drives_a_device_while_the_body_drives_another(
        rig: tuple[Raspberry, Uno, MockLink]) -> None:
    rp, board, link = rig
    worker_led = LED(pin=2, board=board)      # each side gets its OWN device
    main_led = LED(pin=3, board=board)

    with BackgroundTasks() as tasks:
        @tasks.run
        def flash() -> None:
            while not tasks.stopping:
                worker_led.on()
                worker_led.off()
                tasks.sleep(0.005)

        for _ in range(20):
            main_led.on()
            main_led.off()
            time.sleep(0.005)

    ids = {f.payload[0] for f in link.sent if f.cmd is not None and len(f.payload) > 0}
    assert worker_led._id in ids and main_led._id in ids
    rp.close()


# --- thread budget --------------------------------------------------------

def test_finished_tasks_free_their_slot() -> None:
    """Dead Thread objects must not accumulate for the life of the block.

    The OS reclaims the thread itself when the function returns; this is about
    us not holding the corpse, which a submit-per-event loop would do forever.
    """
    with BackgroundTasks() as tasks:
        for _ in range(50):
            tasks.run(lambda: None)
        deadline = time.monotonic() + 2
        while tasks.running and time.monotonic() < deadline:
            time.sleep(0.01)
        assert tasks.running == 0
        assert len(tasks._threads) == 0          # reaped, not just dead


def test_max_workers_refuses_a_spawn_storm() -> None:
    with BackgroundTasks(max_workers=2) as tasks:
        for _ in range(2):
            tasks.run(lambda: time.sleep(0.3))
        with pytest.raises(RuntimeError, match="max_workers=2 reached"):
            tasks.run(lambda: None)
        tasks.stop()


def test_a_finished_task_makes_room_under_max_workers() -> None:
    with BackgroundTasks(max_workers=1) as tasks:
        tasks.run(lambda: None)
        deadline = time.monotonic() + 2
        while tasks.running and time.monotonic() < deadline:
            time.sleep(0.01)
        tasks.run(lambda: None)                  # the slot came back
        assert True


def test_no_limit_by_default() -> None:
    with BackgroundTasks() as tasks:
        for _ in range(20):
            tasks.run(lambda: None)
        assert tasks.max_workers is None


# --- passing arguments to a task ------------------------------------------

def test_run_forwards_positional_and_keyword_arguments() -> None:
    got: list[object] = []
    with BackgroundTasks() as tasks:
        def work(a: int, b: int, *, c: int) -> None:
            got.append((a, b, c))
        tasks.run(work, 1, 2, c=3)
    assert got == [(1, 2, 3)]


def test_run_passes_a_device_to_its_task(
        rig: tuple[Raspberry, Uno, MockLink]) -> None:
    """The point: hand a task the devices it owns, instead of a global."""
    rp, board, link = rig
    led = LED(pin=2, board=board)
    done = threading.Event()

    def flash(target: LED, times: int) -> None:
        for _ in range(times):
            target.on()
            target.off()
        done.set()

    with BackgroundTasks() as tasks:
        tasks.run(flash, led, times=3)
    assert done.is_set()
    writes = [f for f in link.sent if f.payload and f.payload[0] == led._id]
    assert len(writes) >= 6
    rp.close()


def test_the_same_function_can_run_twice_with_different_arguments() -> None:
    seen: list[str] = []
    lock = threading.Lock()
    with BackgroundTasks() as tasks:
        def work(name: str) -> None:
            with lock:
                seen.append(name)
        tasks.run(work, "left")
        tasks.run(work, "right")
    assert sorted(seen) == ["left", "right"]


def test_the_decorator_form_still_works_with_no_arguments() -> None:
    ran = threading.Event()
    with BackgroundTasks() as tasks:
        @tasks.run
        def work() -> None:
            ran.set()
    assert ran.is_set()


def test_a_callable_without_a_name_is_accepted() -> None:
    # functools.partial has no __name__; the thread label must not blow up.
    from functools import partial
    ran = threading.Event()
    with BackgroundTasks() as tasks:
        tasks.run(partial(lambda e: e.set(), ran))
    assert ran.is_set()


# --- manual lifecycle (no `with`) -----------------------------------------

def test_start_and_close_without_a_context_manager() -> None:
    ran = threading.Event()
    tasks = BackgroundTasks().start()
    try:
        tasks.run(ran.set)
    finally:
        tasks.close()
    assert ran.is_set()
    assert tasks.running == 0


def test_close_stops_a_long_running_task() -> None:
    loops = [0]
    tasks = BackgroundTasks().start()

    def forever() -> None:
        while not tasks.stopping:
            loops[0] += 1
            tasks.sleep(0.01)

    tasks.run(forever)
    time.sleep(0.08)
    tasks.close()
    assert loops[0] > 1
    assert tasks.running == 0


def test_close_reraises_a_task_error() -> None:
    tasks = BackgroundTasks().start()
    tasks.run(lambda: (_ for _ in ()).throw(RataError("manual boom")))
    time.sleep(0.05)
    with pytest.raises(RataError, match="manual boom"):
        tasks.close()


def test_close_is_safe_to_call_twice() -> None:
    tasks = BackgroundTasks().start()
    tasks.run(lambda: None)
    tasks.close()
    tasks.close()                            # no error, nothing left to join


def test_close_reraise_false_swallows_the_task_error() -> None:
    # For when you are already handling your own failure and don't want it masked.
    tasks = BackgroundTasks().start()
    tasks.run(lambda: (_ for _ in ()).throw(RataError("quiet")))
    time.sleep(0.05)
    tasks.close(reraise=False)               # no raise


def test_run_after_close_is_refused() -> None:
    tasks = BackgroundTasks().start()
    tasks.close()
    with pytest.raises(RuntimeError, match="not open"):
        tasks.run(lambda: None)
