"""Turn RATA inputs into gamepad controls.

A gamepad button/axis is fed by *something that can be read*: usually a RATA input
device (a `Button`, `Potentiometer`, `RotaryEncoder`, ...) but also any plain
callable. Each mapping becomes a `Binding` that knows how to produce its value:

- for a **device** source, the binding keeps the device plus a *decoder* that turns
  the device's raw value (a signed int16, exactly what the board returns) into the
  gamepad value -- a `bool` for a button, a `0.0..1.0` float for an axis. Keeping
  the decode separate from the read is what lets the gamepad batch every device's
  read into one frame (see `Gamepad._read_all` / `Arduino.read_many`).
- for a **callable** source, the binding just calls it (the raw arg is ignored).

So every binding exposes the same ``read(raw: int) -> value``: pass the device's
freshly-read raw value (or anything for a callable).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..complex_devices import AnalogInput, DigitalInput, RotaryEncoder

# What map_button / map_axis accept as a source.
ButtonSource = DigitalInput | Callable[[], bool]
AxisSource = AnalogInput | RotaryEncoder | Callable[[], float]


@dataclass
class ButtonBinding:
    """A gamepad button wired to a device (with a decoder) or a callable."""
    index: int
    device: DigitalInput | None          # None -> callable source (read ignores its arg)
    read: Callable[[int], bool]          # raw int16 -> pressed


@dataclass
class AxisBinding:
    """A gamepad axis wired to a device (with a decoder) or a callable."""
    index: int
    device: AnalogInput | RotaryEncoder | None
    read: Callable[[int], float]         # raw int16 -> 0.0..1.0


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def make_button_binding(index: int, source: ButtonSource) -> ButtonBinding:
    """Build a button binding.

    A `Button` (pull-up) reads inverted (pressed = LOW); any other `DigitalInput`
    reads its raw level. Anything else must be a callable returning a truthy value.
    (`hasattr(type(source), ...)` checks the *class* so we never trip the property
    getter -- which would do a serial read -- at mapping time.)
    """
    if isinstance(source, DigitalInput):
        if hasattr(type(source), "is_pressed") and source.pull_up:
            return ButtonBinding(index, source, lambda raw: not bool(raw))
        return ButtonBinding(index, source, lambda raw: bool(raw))
    if callable(source):
        fn = source
        return ButtonBinding(index, None, lambda _raw: bool(fn()))
    raise TypeError(
        f"button source must be a DigitalInput/Button or a callable, got {source!r}"
    )


def make_axis_binding(
    index: int,
    source: AxisSource,
    lo: float | None = None,
    hi: float | None = None,
) -> AxisBinding:
    """Build an axis binding whose ``read`` yields 0.0..1.0.

    - `Potentiometer`/`AnalogInput`: raw 0..1023 -> 0..1 by default; pass raw
      `lo`/`hi` to map a sub-range.
    - `RotaryEncoder`: signed position, mapped from `lo`/`hi` (default -127..127).
    - a callable: its value is used directly (assumed 0..1), or mapped from `lo`/`hi`.
    """
    if lo is not None and hi is not None and lo == hi:
        raise ValueError("axis lo and hi must differ")

    if isinstance(source, AnalogInput):
        if lo is None or hi is None:
            return AxisBinding(index, source, lambda raw: _clamp01(raw / 1023))
        span = hi - lo
        return AxisBinding(index, source, lambda raw: _clamp01((raw - lo) / span))

    if isinstance(source, RotaryEncoder):
        rlo = -127.0 if lo is None else lo
        rhi = 127.0 if hi is None else hi
        span = rhi - rlo
        return AxisBinding(index, source, lambda raw: _clamp01((raw - rlo) / span))

    if callable(source):
        fn = source
        if lo is None or hi is None:
            return AxisBinding(index, None, lambda _raw: _clamp01(float(fn())))
        span = hi - lo
        return AxisBinding(index, None, lambda _raw: _clamp01((float(fn()) - lo) / span))

    raise TypeError(
        f"axis source must be an AnalogInput/Potentiometer, RotaryEncoder, "
        f"or a callable, got {source!r}"
    )
