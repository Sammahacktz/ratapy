"""Raspberry -- the master.

Registers your boards and keeps track of which one is the default. Each board
carries its own `Link` (serial or I2C), so a single Raspberry can talk to some
Arduinos over serial and others over I2C at the same time.

    rp = Raspberry(port="/dev/ttyUSB0")   # a default serial link, for convenience
    a1 = Mega("A")                        # uses the default serial link
    a2 = Uno(0x08, link=I2CLink(bus=1))   # this one is on I2C
    rp.register_arduino(a1, a2)

`port=` (or `link=`) is only a convenience default for boards created without an
explicit `link`. Pure-I2C setups can leave it out and give every board a link.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from .protocol import RataError
from .link import Link, SerialLink
from .scheduler import Scheduler

if TYPE_CHECKING:
    from .boards import Arduino
    from .devices.local import LocalDevice
    from .devices.hid.gadget import UsbGadget


class Raspberry:
    # The most recently created Raspberry; lets `LED(pin=2)` find a default
    # board without any module-level globals floating around.
    _current: ClassVar["Raspberry | None"] = None

    def __init__(self, link: Link | None = None, port: str | None = None,
                 baud: int = 115200, usb_device: bool = False,
                 usb_strict: bool = False) -> None:
        # Optional default link for boards created without their own `link=`.
        # Give a `link`, or a `port` (-> SerialLink), or neither (pure I2C, where
        # every board brings its own link).
        if link is not None:
            self._default_link: Link | None = link
        elif port is not None:
            self._default_link = SerialLink(port, baud)
        else:
            self._default_link = None
        self._boards: list[Arduino] = []
        self._active_board: Arduino | None = None
        # Devices wired to the Pi itself (Camera, NeoPixel, ...), tracked so
        # close() can release their hardware. See ratapy.devices.local.
        self._local_devices: list[LocalDevice] = []
        # USB gadget support: when usb_device=True the Pi can present itself to a
        # host PC as a gamepad + drive (ratapy.devices.hid)
        self._usb_device: bool = usb_device
        self._usb_strict: bool = usb_strict
        self._usb_gadget: UsbGadget | None = None
        # Runs commands a device's sleep() put in the future. Created on first
        # use, so a script that never sleeps never starts a thread.
        self._scheduler: Scheduler | None = None
        Raspberry._current = self

    @classmethod
    def current(cls) -> "Raspberry":
        """The most recently created Raspberry (the usual single-master case)."""
        if cls._current is None:
            raise RataError("no Raspberry exists -- create one before adding devices")
        return cls._current

    @property
    def active_board(self) -> "Arduino":
        """The most recently registered board -- the default for new devices."""
        if self._active_board is None:
            raise RataError(
                "no board registered on this Raspberry -- "
                "call register_arduino(...) first"
            )
        return self._active_board

    def register_arduino(self, *boards: "Arduino", verify: bool = True,
                         clear: bool = True) -> "Raspberry":
        """Register one or more Arduinos so their devices can reach the bus.

        Each board is bound to its link (its own, or this Raspberry's default).
        By default each is then pinged to confirm the flashed firmware matches
        the model class (pass verify=False to skip, e.g. in offline tests).
        The last board registered becomes this Raspberry's active board.

        ``clear=True`` (default) resets each board's device registry first, so
        your script starts from a clean slate and the devices you create are the
        *only* ones on the board -- otherwise a board that booted with devices
        saved from an earlier run (see ``Arduino.save_devices``) would keep those
        alongside yours. Pass ``clear=False`` to add to whatever is already there.
        """
        for b in boards:
            b._attach(self)
            self._boards.append(b)
            self._active_board = b
            if verify:
                b.verify()
            if clear:
                b.reset() # start from an empty registry (clears boot-loaded devices)
        return self

    def _register_local(self, device: "LocalDevice") -> None:
        """Track a master-attached device so close() can release it. Internal."""
        self._local_devices.append(device)

    @property
    def gadget(self) -> "UsbGadget":
        """The Pi's USB gadget, created on first use (needs ``usb_device=True``).

        Shared by every HID device on this master (`Gamepad`, `Storage`) so they
        compose into one USB device. Raises if the Raspberry wasn't opted in.
        """
        if not self._usb_device:
            raise RataError(
                "USB gadget features are off -- create the Raspberry with "
                "usb_device=True to use Gamepad / Storage"
            )
        if self._usb_gadget is None:
            from .devices.hid.gadget import UsbGadget
            self._usb_gadget = UsbGadget(strict=self._usb_strict)
        return self._usb_gadget


    @property
    def scheduler(self) -> Scheduler:
        """The queue running commands that a device's ``sleep()`` deferred."""
        if self._scheduler is None:
            self._scheduler = Scheduler()
        return self._scheduler

    def wait(self, timeout: float | None = None) -> bool:
        """Block until every command deferred by a ``sleep()`` has been sent.

        A device's ``sleep()`` returns immediately, so a script can reach its end
        with commands still due -- this is how you stay until they've run::

            led.on(); led.sleep(3); led.off()
            rp.wait()                          # ~3 s, then the LED is off

        ``close()`` (so also leaving a ``with Raspberry()`` block) does this for
        you. Returns True if the queue emptied, False on timeout. Re-raises the
        first error a deferred command hit -- nothing else could report it.
        """
        if self._scheduler is None:
            return True
        return self._scheduler.drain(timeout)

    def close(self) -> None:
        """Release master-attached devices, then close every distinct link.

        Deferred commands are given their moment first: a ``led.sleep(3)`` that
        is still pending would otherwise be dropped on the floor here, leaving
        the LED on forever.
        """
        if self._scheduler is not None:
            try:
                self._scheduler.drain()
            finally:
                self._scheduler.close()
                self._scheduler = None
        for device in self._local_devices:
            try:
                device.close()
            except Exception:  # best effort -- keep tearing down
                pass
        # Devices are down (poll threads stopped); now unbind + remove the gadget.
        if self._usb_gadget is not None:
            try:
                self._usb_gadget.teardown()
            except Exception:
                pass
            self._usb_gadget = None
        seen: set[int] = set()
        links: list[Link] = []
        if self._default_link is not None:
            links.append(self._default_link)
        links.extend(b._link for b in self._boards if b._link is not None)
        for link in links:
            if id(link) not in seen:
                seen.add(id(link))
                link.close()
        if Raspberry._current is self: # a closed master is no default
            Raspberry._current = None

    def __enter__(self) -> "Raspberry":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
