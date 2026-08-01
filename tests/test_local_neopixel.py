"""PiNeoPixel's root guard.

rpi_ws281x maps /dev/mem (root-only) and SEGFAULTS on its own failed-init path,
so a non-root run used to crash instead of erroring. The guard must raise a clean
RataError before touching the C library. rpi_ws281x isn't installed off-Pi, so we
stub it and confirm it is never reached.
"""

from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def neopixel(monkeypatch: pytest.MonkeyPatch):
    """Import the neopixel module with rpi_ws281x stubbed to explode if used."""
    stub = types.ModuleType("rpi_ws281x")

    def _boom(*_a: object) -> object:
        raise AssertionError("reached the C library despite not being root")

    stub.PixelStrip = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rpi_ws281x", stub)
    monkeypatch.delitem(sys.modules, "ratapy.devices.local.neopixel", raising=False)
    import importlib
    return importlib.import_module("ratapy.devices.local.neopixel")


def test_not_root_raises_cleanly_instead_of_segfaulting(
        neopixel, monkeypatch: pytest.MonkeyPatch) -> None:
    from ratapy.protocol import RataError
    from ratapy.raspberry import Raspberry

    monkeypatch.setattr(neopixel.os, "geteuid", lambda: 1000)   # a normal user
    rp = Raspberry()
    strip = neopixel.PiNeoPixel(count=12, board=rp)
    with pytest.raises(RataError, match="needs root"):
        strip._hw()                                             # never hits _boom


def test_construction_does_not_touch_hardware(
        neopixel, monkeypatch: pytest.MonkeyPatch) -> None:
    # Building the object (and staging pixels) must not open the device -- only
    # _hw()/show() does, so a script can be assembled off a live Pi.
    from ratapy.raspberry import Raspberry

    monkeypatch.setattr(neopixel.os, "geteuid", lambda: 1000)
    rp = Raspberry()
    strip = neopixel.PiNeoPixel(count=12, board=rp)
    strip.fill((0, 40, 0))                                      # staging only
    assert strip._strip is None                                # nothing opened
