"""Turn the Raspberry Pi into a USB gamepad fed by RATA inputs.

Wire some buttons, a potentiometer and a rotary encoder to an Arduino, and this
script makes the *Pi itself* show up on a host PC as a USB joystick whose controls
follow those physical inputs -- the JoystickXL idea, with the Linux Pi as the HID.

Setup (once): run scripts/setup-usb-gadget.sh + reboot, connect the Pi's USB-OTG
port to the host, and run this script as root. See docs/INSTALL.md.

Runs anywhere: on a machine that can't be a USB gadget (e.g. your laptop) it falls
back to a logged "simulated" mode, so you can try the wiring API before you're on a
Pi. Turn on INFO logging to watch what the gadget does.
"""

import logging

from ratapy import Raspberry
from ratapy.boards import Mega
from ratapy.devices import (
    Button,
    Gamepad,
    NeoPixel,
    Potentiometer,
    RotaryEncoder,
    Storage,
    Identity,
)


class Controller:
    """Extra hardware we drive ourselves, plus what one loop iteration does.

    Per-iteration state (here, edge detection on the button) lives on the object
    as an attribute -- no closure or global -- and :meth:`step` is handed to
    ``pad.run`` as a bound method.
    """

    def __init__(self, rp: Raspberry, ad: Mega) -> None:
        self.strip = NeoPixel(count=8, board=rp)        # WS2812 on the Pi (GPIO18)
        self.menu = Button(pin=7, board=ad)             # a button we react to ourselves
        self.storage = Storage(board=rp, shown=False)   # gamepad only until we reveal it
        self._prev_menu = False

    def step(self) -> None:
        """One pass: react to inputs by driving BOTH local hardware and the host."""
        # Light the strip green while the button is held (local hardware reaction).
        # The buttons/pots mapped to the pad are sent to the host by pad.update();
        # here we add our own effects on top.
        self.strip.fill((0, 40, 0) if self.menu.is_pressed else (0, 0, 0))
        self.strip.show()

        # On a fresh press (rising edge), also toggle the USB drive on the host.
        if self.menu.is_pressed and not self._prev_menu:
            self.storage.hide() if self.storage.is_shown else self.storage.show()
            print("drive", "shown" if self.storage.is_shown else "hidden")
        self._prev_menu = self.menu.is_pressed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # 1. The master. usb_device=True lets it present a USB gadget; without it,
    #    Gamepad/Storage would raise. usb_strict=True would make a non-gadget
    #    machine an error instead of falling back to the simulation.
    rp = Raspberry(port="/dev/ttyUSB0", usb_device=True)

    ad = Mega("A")
    rp.register_arduino(ad)

    # 2. Describe the gamepad's shape: how many buttons, and which axes (in report
    #    order). Axis names map to standard HID usages -- x/y is the main stick,
    #    z/rx/ry/rz a second stick or triggers, plus slider/dial/wheel.
    pad = Gamepad(board=rp, buttons=4, axes=("x", "y", "z"), identity=Identity(name="TestJoystick", manufacturer="Me"))

    # 3. Wire each control to something readable. A source is usually a RATA input
    #    device (the adapter knows how to read it) -- or any callable.
    pad.map_button(0, Button(pin=2, board=ad))
    pad.map_button(1, Button(pin=3, board=ad))
    pad.map_button(2, Button(pin=4, board=ad))

    # Button 3 from a callable: "turbo", on only while buttons 0 and 1 are held.
    b0 = Button(pin=2, board=ad)
    b1 = Button(pin=3, board=ad)
    pad.map_button(3, lambda: b0.is_pressed and b1.is_pressed)

    # X straight from a pot; Y from the pot's upper half (raw 512..1023 -> 0..255).
    pad.map_axis("x", Potentiometer(channel=0, board=ad))
    pad.map_axis("y", Potentiometer(channel=1, board=ad), lo=512, hi=1023)

    # Z from an encoder -- its count is unbounded, so lo/hi fence it onto the axis.
    pad.map_axis("z", RotaryEncoder(clk=5, dt=6, board=ad), lo=-20, hi=20)

    # 4. Our own hardware + loop logic (state lives on the controller object).
    controller = Controller(rp, ad)

    # 5. Hand the loop to the Gamepad. run() does update() + step() every pass at
    #    ~poll_hz and blocks until Ctrl-C -- no hand-written while loop needed.
    #    Single-threaded, so reading inputs inside step() is safe.
    try:
        print("Gamepad live -- hold the button to light the strip. Ctrl-C to stop.")
        pad.run(controller.step)
    finally:
        rp.close()                               # release inputs + strip + USB gadget


if __name__ == "__main__":
    main()
