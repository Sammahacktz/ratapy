"""Device.sleep() -- per-device timing that doesn't block the script.

Timings here are deliberately small but generous: we assert ORDER and coarse
buckets, never exact instants, so a loaded CI box can't fail them.
"""

from __future__ import annotations

import time

import pytest

from ratapy.boards import Uno
from ratapy.devices import LED, AnalogInput
from ratapy.executor import ParallelExecutor
from ratapy.protocol import RataError
from ratapy.raspberry import Raspberry
from tests.conftest import MockLink


@pytest.fixture
def rig() -> tuple[Raspberry, Uno, MockLink]:
    link = MockLink()
    rp = Raspberry(link=link)
    board = Uno("A", link=link)
    rp.register_arduino(board, verify=False)
    return rp, board, link


def _timestamped(board: Uno) -> list[tuple[float, int, bytes]]:
    """Record (when, device id, payload) for every write the board sends."""
    log: list[tuple[float, int, bytes]] = []
    t0 = time.monotonic()
    original = board._write

    def traced(dev_id: int, data: bytes) -> None:
        log.append((time.monotonic() - t0, dev_id, data))
        original(dev_id, data)

    board._write = traced                                    # type: ignore[method-assign]
    return log


def test_sleep_returns_immediately(rig: tuple[Raspberry, Uno, MockLink]) -> None:
    rp, board, _ = rig
    led = LED(pin=2, board=board)
    start = time.monotonic()
    led.sleep(0.5)
    assert time.monotonic() - start < 0.1        # the whole point: it did not wait
    rp.close()


def test_each_device_keeps_its_own_timeline(rig: tuple[Raspberry, Uno, MockLink]) -> None:
    """The motivating case: led2 is off at t+1, not t+4.

    Written with time.sleep this would serialise -- led2 could not turn off until
    led's 3 seconds had passed.
    """
    rp, board, _ = rig
    led, led2 = LED(pin=2, board=board), LED(pin=3, board=board)
    log = _timestamped(board)

    led.on(); led2.on()
    led.sleep(0.30);  led.off()
    led2.sleep(0.10); led2.off()
    rp.wait()

    order = [(dev, data) for _, dev, data in log]
    assert order == [
        (led._id, b"\x01"), (led2._id, b"\x01"),   # both on, at once
        (led2._id, b"\x00"),                        # led2 off FIRST (0.10)
        (led._id, b"\x00"),                         # then led   (0.30)
    ]
    at = {(dev, data): t for t, dev, data in log}
    assert at[(led2._id, b"\x00")] < 0.25          # ~0.10, nowhere near 0.40
    assert 0.25 < at[(led._id, b"\x00")] < 0.6     # ~0.30
    rp.close()


def test_successive_sleeps_add_up(rig: tuple[Raspberry, Uno, MockLink]) -> None:
    rp, board, _ = rig
    led = LED(pin=2, board=board)
    log = _timestamped(board)
    led.sleep(0.1); led.on()
    led.sleep(0.1); led.off()          # 0.2 from the start, not 0.1
    rp.wait()
    assert [data for _, _, data in log] == [b"\x01", b"\x00"]
    assert log[1][0] > log[0][0] >= 0.05
    assert log[1][0] >= 0.18
    rp.close()


def test_commands_after_a_sleep_are_deferred_not_sent(
        rig: tuple[Raspberry, Uno, MockLink]) -> None:
    rp, board, link = rig
    led = LED(pin=2, board=board)
    before = len(link.sent)
    led.sleep(0.2)
    led.off()
    assert len(link.sent) == before                # nothing on the wire yet
    assert rp.scheduler.pending == 1
    rp.wait()
    assert len(link.sent) > before                 # ...and now it has gone
    rp.close()


def test_wait_blocks_until_the_timeline_drains(
        rig: tuple[Raspberry, Uno, MockLink]) -> None:
    rp, board, _ = rig
    led = LED(pin=2, board=board)
    led.sleep(0.2); led.off()
    start = time.monotonic()
    assert rp.wait() is True
    assert time.monotonic() - start >= 0.15
    assert rp.scheduler.pending == 0
    rp.close()


def test_wait_reports_timeout_without_draining(
        rig: tuple[Raspberry, Uno, MockLink]) -> None:
    rp, board, _ = rig
    led = LED(pin=2, board=board)
    led.sleep(5); led.off()
    assert rp.wait(timeout=0.05) is False          # still pending, said so
    rp._scheduler.close()                          # type: ignore[union-attr]


def test_close_runs_what_is_still_due(rig: tuple[Raspberry, Uno, MockLink]) -> None:
    # Otherwise `with Raspberry()` would drop a pending off() and leave the LED on.
    rp, board, _ = rig
    led = LED(pin=2, board=board)
    log = _timestamped(board)
    led.sleep(0.15); led.off()
    rp.close()
    assert [data for _, _, data in log] == [b"\x00"]


def test_an_error_in_a_deferred_command_surfaces_at_wait(
        rig: tuple[Raspberry, Uno, MockLink]) -> None:
    # A deferred command has no caller left to catch it, so wait() must report it
    # rather than let it vanish on the scheduler thread.
    rp, board, _ = rig
    led = LED(pin=2, board=board)

    def boom(dev_id: int, data: bytes) -> None:
        raise RataError("board fell off")

    board._write = boom                            # type: ignore[method-assign]
    led.sleep(0.05); led.off()
    with pytest.raises(RataError, match="board fell off"):
        rp.wait()
    rp.close()


def test_reads_are_not_deferred(rig: tuple[Raspberry, Uno, MockLink]) -> None:
    # A read has to return a value now; there is nothing to defer it to.
    rp, board, link = rig
    pot = AnalogInput(channel=0, board=board)
    link.value = 512
    pot.sleep(5)
    start = time.monotonic()
    assert pot.value == 512
    assert time.monotonic() - start < 0.1
    rp._scheduler = None                           # nothing was queued
    rp.close()


def test_sleep_inside_an_executor_is_refused(
        rig: tuple[Raspberry, Uno, MockLink]) -> None:
    # An executor exists to start commands at ONE instant -- a gap contradicts it.
    rp, board, _ = rig
    led = LED(pin=2, board=board)
    with pytest.raises(RataError, match="cannot be used inside a ParallelExecutor"):
        with ParallelExecutor():
            led.sleep(0.1)
    pe = ParallelExecutor()
    led.set_executor(pe)
    with pytest.raises(RataError, match="cannot be used inside a ParallelExecutor"):
        led.sleep(0.1)
    rp.close()


def test_negative_sleep_is_refused(rig: tuple[Raspberry, Uno, MockLink]) -> None:
    rp, board, _ = rig
    led = LED(pin=2, board=board)
    with pytest.raises(ValueError, match="positive delay"):
        led.sleep(-1)
    rp.close()


def test_no_sleep_means_no_thread(rig: tuple[Raspberry, Uno, MockLink]) -> None:
    # A script that never sleeps should not pay for a scheduler at all.
    rp, board, _ = rig
    led = LED(pin=2, board=board)
    led.on(); led.off()
    assert rp._scheduler is None
    assert rp.wait() is True
    rp.close()
