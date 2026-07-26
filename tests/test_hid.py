"""Tests for the USB-HID gamepad + storage layer (ratapy.devices.hid).

Everything runs against the *simulated* gadget backend (forced on via the
``force_sim`` fixture), so no USB hardware, root, or ConfigFS is needed. Real
input devices are exercised through the mock-link ``board`` fixture.
"""

from __future__ import annotations

import pytest

from ratapy.boards import Mega
from ratapy.devices import Button, Gamepad, Identity, Potentiometer, RotaryEncoder, Storage
from ratapy import protocol as p
from ratapy.devices.hid import gadget as gadget_mod
from ratapy.devices.hid.mapping import make_axis_binding, make_button_binding
from ratapy.devices.hid.report import (
    build_gamepad_descriptor,
    button_bytes,
    normalize_axes,
    pack_report,
    report_length,
)
from ratapy.protocol import RataError
from ratapy.raspberry import Raspberry

from .conftest import MockLink


@pytest.fixture
def force_sim(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force gadget capability detection to fail, so the sim backend is chosen."""
    monkeypatch.setattr(gadget_mod, "gadget_incapable_reason", lambda: "forced in tests")


@pytest.fixture
def usb_rp(force_sim: None) -> Raspberry:
    return Raspberry(usb_device=True)


# --- report descriptor + packing (pure) ------------------------------------

def test_descriptor_wraps_gamepad_collection() -> None:
    d = build_gamepad_descriptor(4, ("x", "y"))
    assert d[:6] == bytes([0x05, 0x01, 0x09, 0x05, 0xA1, 0x01])  # Usage Page/Gamepad, Collection
    assert d[-1] == 0xC0                                          # End Collection


def test_report_length_and_button_bytes() -> None:
    assert button_bytes(0) == 0
    assert button_bytes(1) == 1
    assert button_bytes(8) == 1
    assert button_bytes(9) == 2
    assert report_length(4, 2) == 3     # 1 button byte + 2 axis bytes
    assert report_length(10, 3) == 5    # 2 button bytes + 3 axis bytes


def test_pack_report_bit_and_byte_order() -> None:
    # button 0 and 2 pressed -> 0b0000_0101 = 0x05; axes as given, clamped.
    assert pack_report([True, False, True, False], [0, 255]) == bytes([0x05, 0x00, 0xFF])
    assert pack_report([], [300, -5]) == bytes([0xFF, 0x00])   # clamp high/low
    assert pack_report([False] * 9, []) == bytes([0x00, 0x00])  # 9 buttons -> 2 bytes


def test_normalize_axes_rejects_bad_names() -> None:
    assert normalize_axes(("X", "Y")) == ("x", "y")
    with pytest.raises(ValueError):
        normalize_axes(("x", "x"))
    with pytest.raises(ValueError):
        normalize_axes(("nope",))


# --- input adapters (pure decoders: raw int16 -> value) --------------------

def test_button_binding_honours_pullup(board: Mega) -> None:
    btn = Button(pin=4, board=board)            # pull_up=True by default
    b = make_button_binding(0, btn)
    assert b.device is btn
    assert b.read(0) is True                    # LOW -> pressed (pull-up)
    assert b.read(1) is False                   # HIGH -> released


def test_axis_binding_from_potentiometer(board: Mega) -> None:
    pot = Potentiometer(channel=0, board=board)
    a = make_axis_binding(0, pot)
    assert a.read(0) == pytest.approx(0.0)
    assert a.read(1023) == pytest.approx(1.0)


def test_axis_binding_encoder_needs_range(board: Mega) -> None:
    enc = RotaryEncoder(clk=2, dt=3, board=board)
    a = make_axis_binding(0, enc, lo=-10, hi=10)
    assert a.read(0) == pytest.approx(0.5)      # centre of [-10, 10]
    assert a.read(10) == pytest.approx(1.0)
    assert a.read(-100) == pytest.approx(0.0)   # clamps


def test_axis_binding_callable_with_range() -> None:
    v = {"n": 50.0}
    a = make_axis_binding(0, lambda: v["n"], lo=0, hi=100)
    assert a.device is None
    assert a.read(0) == pytest.approx(0.5)      # arg ignored for a callable


# --- Gamepad ---------------------------------------------------------------

def test_gamepad_requires_usb_device(force_sim: None) -> None:
    rp = Raspberry()                            # usb_device defaults to False
    with pytest.raises(RataError):
        Gamepad(board=rp, buttons=1)


def test_gamepad_update_sends_mapped_state(usb_rp: Raspberry) -> None:
    pad = Gamepad(board=usb_rp, buttons=2, axes=("x", "y"))
    state = {"b": False, "x": 0.0}
    pad.map_button(0, lambda: state["b"])
    pad.map_axis("x", lambda: state["x"])

    pad.update()
    backend = usb_rp.gadget._backend
    # button off, x=0 -> 0x00; y unmapped -> centre 0x80.
    assert backend.last_report == bytes([0x00, 0x00, 0x80])

    state["b"] = True
    state["x"] = 1.0
    pad.update()
    assert backend.last_report == bytes([0x01, 0xFF, 0x80])


def test_gamepad_identity_sets_gadget_name(usb_rp: Raspberry) -> None:
    pad = Gamepad(board=usb_rp, buttons=1,
                  identity=Identity(name="My Pad", manufacturer="Me", serial="42"))
    pad.map_button(0, lambda: False)
    pad.update()
    ident = usb_rp.gadget._backend.identity
    assert (ident.name, ident.manufacturer, ident.serial) == ("My Pad", "Me", "42")


def test_gamepad_default_identity(usb_rp: Raspberry) -> None:
    pad = Gamepad(board=usb_rp, buttons=1)
    pad.map_button(0, lambda: False)
    pad.update()
    assert usb_rp.gadget._backend.identity.name == "RATA Gamepad"


def test_gamepad_batches_device_reads(usb_rp: Raspberry, board: Mega, link: MockLink) -> None:
    pad = Gamepad(board=usb_rp, buttons=1, axes=("x",))
    btn = Button(pin=2, board=board)
    pot = Potentiometer(channel=0, board=board)
    pad.map_button(0, btn)
    pad.map_axis("x", pot)
    link.values = {btn._id: 0, pot._id: 1023}   # button LOW=pressed, pot at max

    pad.update()
    # button pressed -> bit 0; x = 1.0 -> 0xFF
    assert usb_rp.gadget._backend.last_report == bytes([0x01, 0xFF])
    # both inputs read in ONE batched frame -- no per-device CMD_READ
    assert sum(f.cmd == p.CMD_READ_MULTI for f in link.sent) == 1
    assert sum(f.cmd == p.CMD_READ for f in link.sent) == 0


def test_gamepad_only_writes_on_change(usb_rp: Raspberry) -> None:
    pad = Gamepad(board=usb_rp, buttons=1)
    pad.map_button(0, lambda: False)
    pad.update()
    pad.update()
    pad.update()
    assert usb_rp.gadget._backend.report_count == 1


def test_gamepad_map_rejects_bad_index_and_axis(usb_rp: Raspberry) -> None:
    pad = Gamepad(board=usb_rp, buttons=2, axes=("x",))
    with pytest.raises(ValueError):
        pad.map_button(5, lambda: False)
    with pytest.raises(ValueError):
        pad.map_axis("z", lambda: 0.0)


def test_gamepad_run_calls_step_then_stops(usb_rp: Raspberry) -> None:
    pad = Gamepad(board=usb_rp, buttons=1)
    pad.map_button(0, lambda: False)
    calls = {"n": 0}

    def step() -> None:
        calls["n"] += 1
        if calls["n"] >= 3:
            pad.stop()          # break out of the blocking loop from inside step

    pad.run(step, hz=1000)
    assert calls["n"] == 3


def test_gamepad_run_forwards_args_to_step(usb_rp: Raspberry) -> None:
    pad = Gamepad(board=usb_rp, buttons=1)
    pad.map_button(0, lambda: False)
    seen: list[tuple[object, ...]] = []

    def step(tag: str) -> None:
        seen.append((tag,))
        pad.stop()

    pad.run(step, "hi", hz=1000)
    assert seen == [("hi",)]


def test_gamepad_strict_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gadget_mod, "gadget_incapable_reason", lambda: "no UDC")
    rp = Raspberry(usb_device=True, usb_strict=True)
    pad = Gamepad(board=rp, buttons=1)
    with pytest.raises(RataError):
        pad.start()


# --- Storage ---------------------------------------------------------------

def test_storage_show_hide_toggles_gadget(usb_rp: Raspberry) -> None:
    st = Storage(board=usb_rp, shown=False)
    assert st.is_shown is False
    st.show()
    assert st.is_shown is True
    assert usb_rp.gadget._backend.storage_shown is True
    st.hide()
    assert st.is_shown is False
    assert usb_rp.gadget._backend.storage_shown is False


def test_storage_shown_by_default(usb_rp: Raspberry) -> None:
    st = Storage(board=usb_rp)
    assert st.is_shown is True
    assert usb_rp.gadget._backend.storage_shown is True


def test_close_tears_down_gadget(usb_rp: Raspberry) -> None:
    pad = Gamepad(board=usb_rp, buttons=1)
    pad.map_button(0, lambda: True)
    pad.start()
    usb_rp.close()
    assert pad.is_running is False
