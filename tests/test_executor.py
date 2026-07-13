"""ParallelExecutor: staging + a single commit per board, and the ambient block."""

from __future__ import annotations

from ratapy import protocol as p
from ratapy.devices import DigitalOutput
from ratapy.executor import ParallelExecutor
from ratapy.boards import Mega
from tests.conftest import MockLink


def _cmds(link: MockLink) -> list[int]:
    return [f.cmd for f in link.sent]


def test_bound_executor_queues_then_batches(board: Mega, link: MockLink) -> None:
    a = DigitalOutput(pin=7, board=board)
    b = DigitalOutput(pin=8, board=board)
    pe = ParallelExecutor()
    a.set_executor(pe)
    b.set_executor(pe)

    a.on()
    b.on()
    # nothing written yet -- only ADD_DEVICE happened at construction
    assert p.CMD_WRITE not in _cmds(link)
    assert p.CMD_STAGE not in _cmds(link)

    pe.execute()
    cmds = _cmds(link)
    assert cmds.count(p.CMD_STAGE) == 2          # both writes staged
    assert cmds.count(p.CMD_COMMIT) == 1          # one commit for the board


def test_context_manager_executes_on_clean_exit(board: Mega, link: MockLink) -> None:
    a = DigitalOutput(pin=7, board=board)
    with ParallelExecutor():
        a.on()                                    # ambient -> staged, not sent
        assert p.CMD_STAGE not in _cmds(link)
    assert p.CMD_COMMIT in _cmds(link)            # committed on block exit


def test_context_manager_discards_on_exception(board: Mega, link: MockLink) -> None:
    a = DigitalOutput(pin=7, board=board)
    try:
        with ParallelExecutor():
            a.on()
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert p.CMD_COMMIT not in _cmds(link)        # nothing committed
    assert p.CMD_STAGE not in _cmds(link)
