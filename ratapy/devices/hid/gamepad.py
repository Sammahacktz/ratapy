"""Gamepad -- the Pi presented to a host PC as a USB joystick.

The Raspberry becomes a USB gamepad (see :mod:`ratapy.devices.hid.gadget`) whose
buttons and axes are driven by ordinary RATA input devices -- a `Button` here, a
`Potentiometer` there -- read over the wire and forwarded as HID reports. This is
the JoystickXL idea with the Linux Pi as the HID::

    rp  = Raspberry(port="/dev/ttyUSB0", usb_device=True)
    ad  = Mega("A"); rp.register_arduino(ad)
    pad = Gamepad(board=rp, buttons=4, axes=("x", "y"))

    pad.map_button(0, Button(pin=2, board=ad))
    pad.map_axis("x", Potentiometer(channel=0, board=ad))
    pad.start()      # host now sees a live gamepad; a thread polls the inputs
    ...
    pad.stop()

`start()` runs a background poller (``poll_hz`` times a second) that reads every
mapped input, builds a report and sends it when it changes. Use `update()` to push
a single report yourself instead.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable

from ...boards import Arduino
from ...protocol import RataError
from ...raspberry import Raspberry
from ..local.base import LocalDevice
from .gadget import Identity
from .mapping import (
    AxisBinding,
    AxisSource,
    ButtonBinding,
    ButtonSource,
    make_axis_binding,
    make_button_binding,
)
from .report import (
    AXIS_CENTER,
    build_gamepad_descriptor,
    normalize_axes,
    pack_report,
    report_length,
)


class Gamepad(LocalDevice):
    """A USB gamepad hosted by the Raspberry, fed from RATA input devices.

    Args:
        board: the Raspberry to attach to .
        buttons: number of gamepad buttons (0..32).
        axes: ordered axis names (see :data:`report.AXIS_USAGE`), e.g.
            ``("x", "y")``. Each becomes one 8-bit axis in report order.
        poll_hz: how often the background poller reads inputs and sends reports.
    """

    def __init__(
        self,
        board: Raspberry | None = None,
        buttons: int = 0,
        axes: tuple[str, ...] = (),
        poll_hz: float = 60.0,
        identity: Identity | None = None,
    ) -> None:
        super().__init__(board)
        if poll_hz <= 0:
            raise ValueError(f"poll_hz must be positive, got {poll_hz}")
        self._buttons = buttons
        self._axes = normalize_axes(axes)
        self._poll_hz = poll_hz
        self._button_bindings: dict[int, ButtonBinding] = {}
        self._axis_bindings: dict[int, AxisBinding] = {}
        self._last: bytes | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._identity = identity or Identity()
        # Register our HID function on the Pi's shared gadget (raises a clear
        # error if the Raspberry was not created with usb_device=True).
        desc = build_gamepad_descriptor(buttons, self._axes)
        self._report_len = report_length(buttons, len(self._axes))
        self.board.gadget.request_hid(desc, self._report_len, self._identity)


    def map_button(self, index: int, source: ButtonSource) -> "Gamepad":
        """Wire gamepad button `index` (0-based) to a `Button`/`DigitalInput` or callable."""
        if not 0 <= index < self._buttons:
            raise ValueError(f"button index {index} out of range 0..{self._buttons - 1}")
        self._button_bindings[index] = make_button_binding(index, source)
        return self

    def map_axis(self, name: str, source: AxisSource,
                 lo: float | None = None, hi: float | None = None) -> "Gamepad":
        """Wire axis `name` to a `Potentiometer`/`AnalogInput`, `RotaryEncoder`, or callable.

        `lo`/`hi` set the source range that maps onto the axis (see
        :func:`mapping.make_axis_binding`).
        """
        key = name.lower()
        if key not in self._axes:
            raise ValueError(f"no axis {name!r} on this gamepad (axes: {list(self._axes)})")
        index = self._axes.index(key)
        self._axis_bindings[index] = make_axis_binding(index, source, lo, hi)
        return self


    def _read_all(self) -> tuple[list[bool], list[int]]:
        """Read every mapped device in one batched frame per board, then decode.

        All device-backed bindings on a board are read with a single
        ``read_many`` (one round-trip);
        """
        # Gather the device ids to read, grouped by the board they live on.
        ids_by_board: dict[Arduino, list[int]] = defaultdict(list)
        for b in self._button_bindings.values():
            if b.device is not None:
                ids_by_board[b.device._board].append(b.device._id)
        for a in self._axis_bindings.values():
            if a.device is not None:
                ids_by_board[a.device._board].append(a.device._id)
        raw = {board: board.read_many(ids) for board, ids in ids_by_board.items()}

        buttons = [False] * self._buttons
        for i, b in self._button_bindings.items():
            value = raw[b.device._board][b.device._id] if b.device is not None else 0
            buttons[i] = b.read(value)
        axes = [AXIS_CENTER] * len(self._axes)
        for i, a in self._axis_bindings.items():
            value = raw[a.device._board][a.device._id] if a.device is not None else 0
            axes[i] = round(a.read(value) * 255)
        return buttons, axes

    def update(self) -> None:
        """Read every mapped input once and send a report if it changed."""
        buttons, axes = self._read_all()
        report = pack_report(buttons, axes)
        if report != self._last:
            self.board.gadget.hid_write(report)
            self._last = report

    def run(self, step: Callable[..., None] | None = None, *args: object,
            hz: float | None = None, **kwargs: object) -> None:
        """Own the report loop for you -- blocks until Ctrl-C (or `stop()`).

        Each pass sends a report (via :meth:`update`) and then calls your optional
        `step`. It runs single-threaded, so -- unlike the background :meth:`start`
        poller -- it is safe to *read inputs inside* `step` and act on them: check
        a `Button`, drive a `NeoPixel`, toggle `Storage`, etc.

        Any extra ``*args`` / ``**kwargs`` are forwarded to `step` each pass, so it
        can be a plain function given its dependencies rather than a closure::

            pad.run(controller.step)         # a bound method holding its own state
            pad.run(step, strip, storage)    # or a function: step(strip, storage)

        Note state that must persist *between* passes (edge detection, counters)
        lives on your object/closure, not in these per-call args. `hz` overrides
        the loop rate for this run.
        """
        period = 1.0 / (hz if hz else self._poll_hz)
        self.board.gadget.activate()
        self._stop.clear()
        self._last = None
        try:
            while not self._stop.is_set():
                self.update()
                if step is not None:
                    step(*args, **kwargs)
                time.sleep(period)
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()

    def start(self) -> None:
        """Bring the gamepad up on the host and start the background poller."""
        if self._thread is not None and self._thread.is_alive():
            return
        self.board.gadget.activate()
        self._stop.clear()
        self._last = None
        self._thread = threading.Thread(target=self._loop, name="rata-gamepad", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background poller (the gadget stays up until close())."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        period = 1.0 / self._poll_hz
        while not self._stop.wait(0.0 if self._last is None else period):
            try:
                self.update()
            except RataError:
                continue

    def _release(self) -> None:
        self.stop()

    def __repr__(self) -> str:
        return f"Gamepad(buttons={self._buttons}, axes={list(self._axes)})"
