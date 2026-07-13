"""Button long-press: pressed_for() (instant) + wait_pressed_for() (watches).

The MockLink's `value` IS the pin: with the default pull_up, 0 = pressed (the
button pulls the pin LOW) and 1 = released. Flipping it mid-call is how we act
out someone letting go.
"""

from __future__ import annotations

import threading
import time

import pytest

from ratapy.boards import Uno
from ratapy.devices import Button, LimitSwitch
from ratapy.raspberry import Raspberry
from tests.conftest import MockLink

PRESSED, RELEASED = 0, 1


@pytest.fixture
def button() -> tuple[Button, MockLink]:
    link = MockLink()
    rp = Raspberry(link=link)
    board = Uno("A", link=link)
    rp.register_arduino(board, verify=False)
    return Button(pin=4, board=board), link


def _release_after(link: MockLink, delay: float) -> threading.Timer:
    t = threading.Timer(delay, lambda: setattr(link, "value", RELEASED))
    t.daemon = True
    t.start()
    return t


def test_true_when_held_the_whole_time(button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = PRESSED
    assert b.wait_pressed_for(0.1) is True


def test_false_when_released_early(button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = PRESSED
    _release_after(link, 0.05)
    assert b.wait_pressed_for(1.0) is False


def test_returns_as_soon_as_it_is_released(button: tuple[Button, MockLink]) -> None:
    # It must not sit out the full second once the answer is already known.
    b, link = button
    link.value = PRESSED
    _release_after(link, 0.05)
    start = time.monotonic()
    assert b.wait_pressed_for(1.0) is False
    assert time.monotonic() - start < 0.5


def test_false_immediately_if_not_pressed(button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = RELEASED
    start = time.monotonic()
    assert b.wait_pressed_for(5) is False
    assert time.monotonic() - start < 0.1        # no waiting for a press


def test_it_waits_the_whole_time_before_saying_true(
        button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = PRESSED
    start = time.monotonic()
    assert b.wait_pressed_for(0.2) is True
    assert time.monotonic() - start >= 0.2       # not a moment early


def test_a_release_in_the_last_gap_is_not_missed(
        button: tuple[Button, MockLink]) -> None:
    """Released just before the deadline -> False, even between polls.

    With a coarse poll the naive loop would exit the loop and answer True
    without looking again; the final check has to land on the deadline.
    """
    b, link = button
    link.value = PRESSED
    _release_after(link, 0.18)
    assert b.wait_pressed_for(0.2, poll=0.1) is False


def test_a_release_after_the_deadline_is_still_a_long_press(
        button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = PRESSED
    _release_after(link, 0.3)
    assert b.wait_pressed_for(0.1) is True            # the 0.1 s were served


def test_wait_zero_is_just_is_pressed(button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = PRESSED
    assert b.wait_pressed_for(0) is True
    link.value = RELEASED
    assert b.wait_pressed_for(0) is False


def test_negative_is_refused(button: tuple[Button, MockLink]) -> None:
    b, _ = button
    with pytest.raises(ValueError, match="positive time"):
        b.wait_pressed_for(-1)


def test_works_without_a_pull_up(button: tuple[Button, MockLink]) -> None:
    # pull_up=False inverts the wiring: pressed drives the pin HIGH.
    _, link = button
    rp = Raspberry.current()
    board = rp.active_board
    b = Button(pin=5, pull_up=False, board=board)
    link.value = 1                                # HIGH == pressed here
    assert b.wait_pressed_for(0.05) is True
    link.value = 0
    assert b.wait_pressed_for(0.05) is False


# --- pressed_for(): instant, tracked on the instance -----------------------

def test_pressed_for_never_blocks(button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = PRESSED
    start = time.monotonic()
    for _ in range(5):
        b.pressed_for(10)
    assert time.monotonic() - start < 0.1        # five asks, no waiting


def test_pressed_for_becomes_true_once_the_hold_is_long_enough(
        button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = PRESSED
    assert b.pressed_for(0.15) is False          # the clock starts on this read
    time.sleep(0.2)
    assert b.pressed_for(0.15) is True


def test_stacked_thresholds(button: tuple[Button, MockLink]) -> None:
    """The motivating shape: several durations off ONE hold, in a loop."""
    b, link = button
    link.value = PRESSED
    fired: list[str] = []
    start = time.monotonic()
    while time.monotonic() - start < 0.35:
        if b.pressed_for(0.3) and "long" not in fired:
            fired.append("long")
        elif b.pressed_for(0.15) and "short" not in fired:
            fired.append("short")
        time.sleep(0.02)
    assert fired == ["short", "long"]            # 0.15 crossed first, then 0.3


def test_pressed_for_resets_when_let_go(button: tuple[Button, MockLink]) -> None:
    # A new press starts a new hold -- the old one must not carry over.
    b, link = button
    link.value = PRESSED
    b.is_pressed                                 # first sighting: clock starts HERE
    time.sleep(0.2)
    assert b.pressed_for(0.15) is True
    link.value = RELEASED
    assert b.pressed_for(0.15) is False          # up: no hold at all
    link.value = PRESSED
    assert b.pressed_for(0.15) is False          # pressed again: clock restarted
    time.sleep(0.2)
    assert b.pressed_for(0.15) is True           # ...and runs again from there


def test_pressed_for_is_false_while_up(button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = RELEASED
    assert b.pressed_for(0) is False
    assert b.pressed_for(5) is False


def test_pressed_for_zero_is_is_pressed(button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = PRESSED
    assert b.pressed_for(0) is True


def test_pressed_for_negative_is_refused(button: tuple[Button, MockLink]) -> None:
    b, _ = button
    with pytest.raises(ValueError, match="positive time"):
        b.pressed_for(-1)


def test_held_seconds_grows_while_down(button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = RELEASED
    assert b.held_seconds == 0.0                  # never pressed
    link.value = PRESSED
    b.is_pressed                                  # first sighting starts the clock
    time.sleep(0.15)
    first = b.held_seconds
    assert 0.1 < first < 0.5
    time.sleep(0.1)
    assert b.held_seconds > first                 # still down -> still growing


def test_held_seconds_freezes_on_release_and_stands(
        button: tuple[Button, MockLink]) -> None:
    """The press outlives the release -- that is what lets you act on the release.

    It must FREEZE at the length of the press, not keep counting: a button that
    has been up for an hour did not have an hour-long press.
    """
    b, link = button
    link.value = PRESSED
    b.is_pressed
    time.sleep(0.2)
    link.value = RELEASED
    b.is_pressed                                  # the read that sees the release
    held = b.held_seconds
    assert 0.15 < held < 0.5                      # the press it just was
    time.sleep(0.15)
    assert b.held_seconds == held                 # frozen, not still counting


def test_a_new_press_clears_the_last_one(button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = PRESSED
    b.is_pressed
    time.sleep(0.2)
    link.value = RELEASED
    assert b.held_seconds > 0.15                  # the old press stands...
    link.value = PRESSED
    assert b.held_seconds < 0.1                   # ...until this one replaces it


def test_act_on_the_release(button: tuple[Button, MockLink]) -> None:
    # The shape this exists for: decide once the button comes up.
    b, link = button
    link.value = PRESSED
    b.wait_for_press()
    _release_after(link, 0.2)
    b.wait_for_release()
    assert b.held_seconds >= 0.15
    assert b.pressed_for(0.15) is False           # ...but it is up NOW


def test_any_read_keeps_the_hold_clock_running(
        button: tuple[Button, MockLink]) -> None:
    # An ordinary `if button.is_pressed:` loop should feed pressed_for() without
    # the caller doing anything special.
    b, link = button
    link.value = PRESSED
    assert b.is_pressed is True                   # this read starts the clock
    time.sleep(0.2)
    assert b.pressed_for(0.15) is True            # ...and pressed_for sees it


def test_a_press_you_never_watched_is_not_counted(
        button: tuple[Button, MockLink]) -> None:
    """The honest limit of polling: the clock starts at the FIRST read.

    A button held for ages before you ever looked reads as a fresh press -- there
    is nothing in Python that saw it go down. Poll it (or use wait_pressed_for on
    a press you already have) rather than asking once, cold.
    """
    b, link = button
    link.value = PRESSED                          # held "for ages"...
    time.sleep(0.2)                               # ...but nobody read the pin
    assert b.pressed_for(0.15) is False           # so this read starts the clock
    time.sleep(0.2)
    assert b.pressed_for(0.15) is True            # now it has been watched long enough


# --- edge properties: fire once per press/release --------------------------

def test_was_pressed_fires_once_per_press(button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = RELEASED
    assert b.was_pressed is False
    link.value = PRESSED
    assert b.was_pressed is True             # the edge
    assert b.was_pressed is False            # consumed -- still down, but quiet
    assert b.was_pressed is False


def test_was_pressed_kills_the_repeat_problem(button: tuple[Button, MockLink]) -> None:
    """The motivating case: a held button must trigger the action exactly once.

    With `is_pressed` a 50 Hz loop fires 50x/second; that is what queued 95
    commands and ran the steppers away.
    """
    b, link = button
    link.value = PRESSED
    fired = sum(1 for _ in range(50) if b.was_pressed)   # a "held" button
    assert fired == 1


def test_a_new_press_fires_again(button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = PRESSED
    assert b.was_pressed is True
    link.value = RELEASED
    assert b.was_pressed is False
    link.value = PRESSED
    assert b.was_pressed is True             # a second, distinct press


def test_a_tap_between_polls_is_not_lost(button: tuple[Button, MockLink]) -> None:
    # Pressed and released before anyone asked was_pressed -- but a read DID see
    # it down, so the press is real and must still be reported.
    b, link = button
    link.value = PRESSED
    b.is_pressed                             # a poll sees it down...
    link.value = RELEASED
    b.is_pressed                             # ...and the next sees it up
    assert b.was_pressed is True             # the tap survived
    assert b.was_pressed is False


def test_was_released_fires_once_per_release(button: tuple[Button, MockLink]) -> None:
    b, link = button
    link.value = PRESSED
    b.is_pressed
    assert b.was_released is False           # still down
    link.value = RELEASED
    assert b.was_released is True
    assert b.was_released is False           # consumed


def test_was_released_composes_with_held_seconds(
        button: tuple[Button, MockLink]) -> None:
    # The long-press-on-release shape, end to end.
    b, link = button
    link.value = PRESSED
    b.is_pressed
    time.sleep(0.2)
    link.value = RELEASED
    assert b.was_released is True
    assert b.held_seconds > 0.15             # frozen at the press's length


def test_edges_and_levels_do_not_interfere(button: tuple[Button, MockLink]) -> None:
    # Polling is_pressed in a loop must not consume the edge.
    b, link = button
    link.value = PRESSED
    for _ in range(10):
        b.is_pressed
    assert b.was_pressed is True             # still there to be claimed


# --- normally-closed switches ---------------------------------------------

def test_normally_closed_inverts_every_reading(
        button: tuple[Button, MockLink]) -> None:
    """A NC switch conducts at rest, so the pin levels mean the opposite.

    Inverting once inside is_pressed has to carry the whole API with it.
    """
    _, link = button
    board = Raspberry.current().active_board
    nc = Button(pin=6, normally_closed=True, board=board)

    link.value = PRESSED        # LOW: closed circuit == AT REST for a NC switch
    assert nc.is_pressed is False
    assert nc.is_released is True

    link.value = RELEASED       # HIGH: circuit broken == ACTUATED
    assert nc.is_pressed is True


def test_normally_closed_carries_the_edge_and_clock(
        button: tuple[Button, MockLink]) -> None:
    _, link = button
    board = Raspberry.current().active_board
    nc = Button(pin=7, normally_closed=True, board=board)

    link.value = PRESSED                     # at rest
    assert nc.was_pressed is False
    link.value = RELEASED                    # actuated
    assert nc.was_pressed is True            # the edge follows the inversion
    assert nc.was_pressed is False
    assert nc.pressed_for(0) is True
    link.value = PRESSED                     # back to rest
    assert nc.was_released is True


def test_limit_switch_is_a_normally_closed_button(
        button: tuple[Button, MockLink]) -> None:
    _, link = button
    board = Raspberry.current().active_board
    stop = LimitSwitch(pin=8, board=board)
    assert stop.normally_closed is True
    link.value = PRESSED                     # closed == the axis is free
    assert stop.is_pressed is False
    link.value = RELEASED                    # opened == end reached
    assert stop.is_pressed is True
    assert repr(stop) == "LimitSwitch(pin=8)"


def test_a_plain_button_is_unchanged(button: tuple[Button, MockLink]) -> None:
    # The default must stay exactly as it was.
    b, link = button
    assert b.normally_closed is False
    link.value = PRESSED
    assert b.is_pressed is True
    link.value = RELEASED
    assert b.is_pressed is False
    assert repr(b) == "Button(pin=4)"
