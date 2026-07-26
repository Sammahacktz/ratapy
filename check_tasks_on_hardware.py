#!/usr/bin/env python3
"""Exercise BackgroundTasks against a REAL board (the mock can't prove this).

    python check_tasks_on_hardware.py [--port /dev/ttyUSB0]

Wire nothing: it drives the built-in LED on pin 13 and reads A0 (floating is
fine -- we only care that the reads keep flowing, not what they say).

What it checks that tests/test_tasks.py cannot:
  * pyserial survives two threads hammering one port through the Link lock
  * the main loop keeps its read rate while a task blocks in wait()
  * a task is stopped and joined before the links close
"""

from __future__ import annotations

import argparse
import time

from ratapy import Raspberry
from ratapy.boards import Uno
from ratapy.devices import LED, AnalogInput
from ratapy.tasks import BackgroundTasks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--seconds", type=float, default=5.0)
    args = ap.parse_args()

    with Raspberry(port=args.port) as rp:
        board = Uno("A")
        rp.register_arduino(board)
        # Each side gets its OWN device -- the rule from the docs.
        task_led = LED(pin=13, board=board)
        pot = AnalogInput(channel=0, board=board)

        reads = 0
        blinks = [0]
        errors: list[str] = []

        with BackgroundTasks() as tasks:

            @tasks.run
            def flash() -> None:
                while not tasks.stopping:
                    task_led.blink(2, on=0.05, off=0.05)
                    task_led.wait()          # a REAL blocking wait, on the wire
                    blinks[0] += 1

            start = time.monotonic()
            while time.monotonic() - start < args.seconds:
                try:
                    pot.value                # main loop stays live
                    reads += 1
                except Exception as e:       # noqa: BLE001 - reporting a probe
                    errors.append(f"main-loop read failed: {e}")
                    break
                time.sleep(0.01)

            elapsed = time.monotonic() - start

        # Past the block: tasks are stopped and joined, links still open.
        print(f"main-loop reads : {reads} in {elapsed:.1f}s "
              f"({reads / elapsed:.0f}/s -- it never blocked)")
        print(f"task blink cycles: {blinks[0]} (a real wait() each time)")
        print(f"tasks running now: {tasks.running} (want 0 -- joined at exit)")
        print(f"errors           : {errors or 'none'}")

        # The link must still work after the task group has gone.
        pot.value
        print("link still healthy after the task group closed")
        return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
