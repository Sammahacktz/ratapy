"""Joystick-steered pan/tilt with a button-triggered gripper.

The two jobs have different shapes, so they get different threads:

* the **main loop** mirrors the joystick onto the servos and must never stall,
  or the servos go sticky;
* the **gripper** is a sequence -- close, wait for the motors, open -- and is
  much clearer written top-to-bottom with blocking `wait()` calls.

`BackgroundTasks` lets both be true: `wait()` blocks only the gripper task.
Ctrl-C leaves cleanly (the task is stopped and joined before the links close).
"""

import time

import ratapy as rtp
from ratapy.boards import AnalogPin, Mega
from ratapy.devices import Button, Joystick, Servo, StepperWithDriver
from ratapy.executor import ParallelExecutor
from ratapy.link import SerialLink
from ratapy.tasks import BackgroundTasks

MOVEMENT = 900          # steps to close (and then re-open) the gripper
STEPPER_SPEED = 1000    # steps/s
POLL = 0.02             # seconds between joystick samples


def value_to_angle(value: float) -> int:
    """Map a joystick axis (-1.0 .. 1.0) onto a servo angle (0 .. 180)."""
    return int(180 * min(1.0, max((value + 1) / 2, 0.0)))


def main() -> None:
    with rtp.Raspberry() as rp:
        mega = Mega("Mega", link=SerialLink())
        rp.register_arduino(mega)

        # --- devices: all created here, on the main thread, before any task
        # starts. Device registration is not atomic, so two threads creating
        # devices could claim the same id.
        #
        # Split by which thread will own it -- nothing is touched by both.
        servo_y = Servo(2, board=mega)                      # main loop
        servo_x = Servo(3, board=mega)                      # main loop
        joystick = Joystick(x_channel=AnalogPin.A1,         # main loop
                            y_channel=AnalogPin.A0, board=mega)

        trigger = Button(12, board=mega)                    # gripper task
        # IN1, IN3, IN2, IN4 -- the middle two are swapped on purpose. That is
        # the coil order AccelStepper expects; wiring order (4,5,6,7) fires the
        # coils out of sequence and most of the torque disappears.
        stepper_L = StepperWithDriver([4, 6, 5, 7], board=mega)
        stepper_R = StepperWithDriver([8, 10, 9, 11], board=mega)

        servo_x.angle(90)
        servo_y.angle(90)

        def drive_jaws(steps: int) -> None:
            """Run both jaws `steps` (mirrored) and return once they have stopped.

            ParallelExecutor puts both commands in ONE firmware pass, so the jaws
            start together rather than a few ms apart -- which is what keeps them
            symmetric. The waits are exact: the board reports when the move is
            done, so nothing has to guess a duration.
            """
            with ParallelExecutor():
                stepper_L.step(-steps, speed=STEPPER_SPEED)
                stepper_R.step(steps, speed=STEPPER_SPEED)
            stepper_L.wait()
            stepper_R.wait()

        with BackgroundTasks() as tasks:

            @tasks.run
            def gripper() -> None:
                """Close and re-open the jaws once per button press."""
                while not tasks.stopping:
                    # `was_pressed` is the EDGE -- true once per press, however
                    # long it is held. With `is_pressed` this would start a fresh
                    # cycle every POLL seconds for as long as a finger stayed down.
                    if trigger.was_pressed:
                        drive_jaws(MOVEMENT)      # close
                        drive_jaws(-MOVEMENT)     # and open again
                    tasks.sleep(POLL)

            # --- main loop: nothing here blocks, so the servos stay responsive
            # for the whole gripper cycle.
            try:
                while True:
                    servo_y.angle(value_to_angle(joystick.y))
                    servo_x.angle(value_to_angle(joystick.x))
                    time.sleep(POLL)
            except KeyboardInterrupt:
                print("\nstopping...")
        # leaving the block: the gripper task is asked to stop and joined,
        # and only then does `with Raspberry` close the serial link.


if __name__ == "__main__":
    main()
