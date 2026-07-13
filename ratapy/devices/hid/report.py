"""HID gamepad report descriptor + report packing -- pure, no I/O.

A USB gamepad tells the host what its reports look like via a *report
descriptor* (a little bytecode from the USB-HID spec), then sends fixed-length
*reports* carrying the live button/axis state. Both are built here from a simple
shape -- a button count and a list of axis names -- so the rest of the package
(and the tests) never hand-assemble HID bytes.

Report layout (no report ID):

    [ button bytes ][ one byte per axis ]

Buttons are packed LSB-first (button 0 = bit 0 of the first byte), padded up to a
whole number of bytes. Each axis is a single unsigned byte, 0..255, logical
centre 128.
"""

from __future__ import annotations

from typing import Final

# Axis name -> HID "Generic Desktop" usage id. The order the user lists axes in
# is the order of the bytes in the report; the name only picks the usage the host
# sees (X/Y/Z for the main stick, Rx/Ry/Rz for a second one, etc.).
AXIS_USAGE: Final[dict[str, int]] = {
    "x": 0x30,
    "y": 0x31,
    "z": 0x32,
    "rx": 0x33,
    "ry": 0x34,
    "rz": 0x35,
    "slider": 0x36,
    "dial": 0x37,
    "wheel": 0x38,
}

AXIS_CENTER: Final = 128     # logical centre of an idle axis (0..255)
MAX_BUTTONS: Final = 32      # a comfortable cap; keeps the report small
MAX_AXES: Final = len(AXIS_USAGE)


def normalize_axes(axes: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Validate + lower-case an axis-name list, raising on unknown/dupe names."""
    out: list[str] = []
    for name in axes:
        key = name.lower()
        if key not in AXIS_USAGE:
            raise ValueError(
                f"unknown axis {name!r}; valid axes: {sorted(AXIS_USAGE)}"
            )
        if key in out:
            raise ValueError(f"duplicate axis {name!r}")
        out.append(key)
    if len(out) > MAX_AXES:
        raise ValueError(f"at most {MAX_AXES} axes, got {len(out)}")
    return tuple(out)


def button_bytes(num_buttons: int) -> int:
    """How many whole bytes the button bitfield occupies."""
    return (num_buttons + 7) // 8


def report_length(num_buttons: int, num_axes: int) -> int:
    """Total length in bytes of one report for this shape."""
    return button_bytes(num_buttons) + num_axes


def build_gamepad_descriptor(num_buttons: int, axes: tuple[str, ...] | list[str]) -> bytes:
    """Build the HID report descriptor for a gamepad with these controls.

    `num_buttons` push-buttons (0..MAX_BUTTONS) followed by one 8-bit axis per
    name in `axes` (see AXIS_USAGE). Returns the descriptor bytes to hand to the
    USB gadget.
    """
    if not 0 <= num_buttons <= MAX_BUTTONS:
        raise ValueError(f"num_buttons must be 0..{MAX_BUTTONS}, got {num_buttons}")
    names = normalize_axes(axes)

    d = bytearray()
    d += bytes([0x05, 0x01])          # Usage Page (Generic Desktop)
    d += bytes([0x09, 0x05])          # Usage (Gamepad)
    d += bytes([0xA1, 0x01])          # Collection (Application)

    if num_buttons:
        pad = (8 - (num_buttons % 8)) % 8
        d += bytes([0x05, 0x09])                  # Usage Page (Button)
        d += bytes([0x19, 0x01])                  # Usage Minimum (1)
        d += bytes([0x29, num_buttons])           # Usage Maximum (num_buttons)
        d += bytes([0x15, 0x00])                  # Logical Minimum (0)
        d += bytes([0x25, 0x01])                  # Logical Maximum (1)
        d += bytes([0x75, 0x01])                  # Report Size (1)
        d += bytes([0x95, num_buttons])           # Report Count (num_buttons)
        d += bytes([0x81, 0x02])                  # Input (Data, Var, Abs)
        if pad:
            d += bytes([0x75, pad])               # Report Size (pad bits)
            d += bytes([0x95, 0x01])              # Report Count (1)
            d += bytes([0x81, 0x03])              # Input (Const, Var, Abs) -- padding

    if names:
        d += bytes([0x05, 0x01])                  # Usage Page (Generic Desktop)
        for name in names:
            d += bytes([0x09, AXIS_USAGE[name]])  # Usage (axis)
        d += bytes([0x15, 0x00])                  # Logical Minimum (0)
        d += bytes([0x26, 0xFF, 0x00])            # Logical Maximum (255)
        d += bytes([0x75, 0x08])                  # Report Size (8)
        d += bytes([0x95, len(names)])            # Report Count (num axes)
        d += bytes([0x81, 0x02])                  # Input (Data, Var, Abs)

    d += bytes([0xC0])                # End Collection
    return bytes(d)


def pack_report(buttons: list[bool], axes: list[int]) -> bytes:
    """Pack live state into a report matching a descriptor of the same shape.

    `buttons` is one bool per button (LSB-first); `axes` one int per axis, each
    clamped to 0..255.
    """
    out = bytearray(button_bytes(len(buttons)))
    for i, pressed in enumerate(buttons):
        if pressed:
            out[i // 8] |= 1 << (i % 8)
    for value in axes:
        out.append(max(0, min(255, int(value))))
    return bytes(out)
