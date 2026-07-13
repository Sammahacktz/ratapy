"""NeoPixel -- an addressable WS2812/WS2811 LED strip on the master.

Addressable strips are clocked far too fast for the Arduino to share cycles
with, and the Pi has a dedicated library (`rpi_ws281x`) that drives them from
PWM/PCM/SPI DMA. So a NeoPixel strip plugs into the Pi and is a `LocalDevice`::

    rp = Raspberry()
    strip = NeoPixel(count=30, board=rp)

    strip.fill((0, 40, 0))          # whole strip dim green
    strip[0] = (255, 0, 0)          # first pixel red
    strip.show()                    # push the buffer to the LEDs
    strip.clear()                   # all off

Colors are ``(r, g, b)`` tuples, 0..255. A WS2812 strip is one **data pin**
plus a shared 5V/ground -- despite the "pixels" name there is a single GPIO, and
each LED is addressed by index (0..count-1), not by its own pin.

Driving the strip needs the `rpi_ws281x` library (`install.sh --pi`)
and usually root (DMA/PWM access). This module imports it at load time, so it is
loaded lazily by `ratapy.devices` -- importing RATA on a plain PC still works.
Default data pin is GPIO18 (PWM0).
"""

from __future__ import annotations

import time
from typing import Any

from rpi_ws281x import PixelStrip

from ...raspberry import Raspberry
from .base import LocalDevice

Color = tuple[int, int, int]


def _check_color(color: Color) -> Color:
    r, g, b = color
    for c in (r, g, b):
        if not 0 <= c <= 255:
            raise ValueError(f"color channels must be 0..255, got {color}")
    return (int(r), int(g), int(b))


class NeoPixel(LocalDevice):
    """A WS2812/WS2811 addressable LED strip driven from the Pi.

    Args:
        count: number of LEDs on the strip.
        pin: data GPIO (BCM numbering). Default 18 (PWM0); must be PWM/PCM/SPI
            capable. 18 or 12 for PWM, 21 for PCM, 10 for SPI.
        brightness: master brightness 0..255 applied to every pixel.
        board: the Raspberry to attach to (defaults to the current master).

    Set pixels with :meth:`set`, :meth:`fill` or ``strip[i] = (r, g, b)``, then
    call :meth:`show` to push the buffer to the hardware.
    """

    def __init__(
        self,
        count: int,
        pin: int = 18,
        brightness: int = 255,
        board: Raspberry | None = None,
    ) -> None:
        if count <= 0:
            raise ValueError(f"count must be positive, got {count}")
        if not 0 <= brightness <= 255:
            raise ValueError(f"brightness must be 0..255, got {brightness}")
        self.count: int = count
        self.pin: int = pin
        self.brightness: int = brightness
        self._buffer: list[Color] = [(0, 0, 0)] * count
        self._strip: Any = None
        super().__init__(board)

    def _hw(self) -> Any:
        """The started PixelStrip, opened on first use."""
        if self._strip is None:
            # (num, pin, freq_hz, dma, invert, brightness, channel)
            strip = PixelStrip(self.count, self.pin, 800000, 10, False, self.brightness, 0)
            strip.begin()
            self._strip = strip
        return self._strip

    def _release(self) -> None:
        if self._strip is not None:
            self.clear()

    def __len__(self) -> int:
        return self.count

    def _index(self, i: int) -> int:
        if not -self.count <= i < self.count:
            raise IndexError(f"pixel {i} out of range 0..{self.count - 1}")
        return i % self.count

    def set(self, i: int, color: Color) -> None:
        """Stage pixel `i` to `color` (call :meth:`show` to display). No I/O yet."""
        self._buffer[self._index(i)] = _check_color(color)

    def __setitem__(self, i: int, color: Color) -> None:
        self.set(i, color)

    def __getitem__(self, i: int) -> Color:
        return self._buffer[self._index(i)]

    def fill(self, color: Color) -> None:
        """Stage every pixel to `color` (call :meth:`show` to display)."""
        c = _check_color(color)
        self._buffer = [c] * self.count

    def show(self) -> None:
        """Push the staged buffer to the strip."""
        strip = self._hw()
        for i, (r, g, b) in enumerate(self._buffer):
            # rpi_ws281x packs a color as 0x00RRGGBB.
            strip.setPixelColor(i, (r << 16) | (g << 8) | b)
        strip.show()

    def clear(self) -> None:
        """Turn every pixel off and push it immediately."""
        self.fill((0, 0, 0))
        self.show()

    off = clear

    def set_brightness(self, brightness: int) -> None:
        """Change the master brightness (0..255) and push it."""
        if not 0 <= brightness <= 255:
            raise ValueError(f"brightness must be 0..255, got {brightness}")
        self.brightness = brightness
        self._hw().setBrightness(brightness)
        self.show()

    def wipe(self, color: Color, delay: float = 0.03) -> None:
        """Light pixels one by one in `color`, `delay` seconds apart (a classic demo)."""
        for i in range(self.count):
            self.set(i, color)
            self.show()
            if delay > 0:
                time.sleep(delay)

    def __repr__(self) -> str:
        return f"NeoPixel(count={self.count}, pin={self.pin})"
