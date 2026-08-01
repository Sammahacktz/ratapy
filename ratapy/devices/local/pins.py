"""Pi GPIO pin labels -- name a pin so you can't confuse the two numberings.

On a Raspberry Pi "pin 17" is ambiguous: it could mean **BCM GPIO17** (what code
and the pinout diagrams call ``GPIO17``) or **physical header pin 17** (a 3.3 V
power pin!). RATA -- like gpiozero -- always means the BCM number, and `PiPin`
makes that explicit at the call site::

    from ratapy.devices import PiLED, PiPin

    PiLED(PiPin.GPIO17)          # unambiguous: BCM GPIO17 (header pin 11)
    PiLED(17)                    # the same -- a plain int is read as BCM too

`PiPin` is an ``IntEnum`` whose value *is* the BCM number, so a member can be used
anywhere a pin int is expected (``int(PiPin.GPIO17) == 17``).

Members are the 26 general-purpose pins on the 40-pin header, ``GPIO2``..``GPIO27``
(``GPIO0``/``GPIO1`` are reserved for HAT ID EEPROM and are left out). Some carry a
fixed alternate function worth knowing when you pick one:

    - I2C-1:        GPIO2 (SDA), GPIO3 (SCL)
    - UART:         GPIO14 (TXD), GPIO15 (RXD)
    - SPI-0:        GPIO7-GPIO11 (CE1, CE0, MISO, MOSI, SCLK)
    - hardware PWM: GPIO12, GPIO13, GPIO18, GPIO19  (best for `PiServo` / `PiPWM`)

Physical-header position is deliberately NOT modelled -- offering both numberings
would reintroduce exactly the ambiguity this exists to remove.
"""

from __future__ import annotations

from enum import IntEnum


class PiPin(IntEnum):
    """A Raspberry Pi GPIO pin by its BCM number. See the module docstring."""

    GPIO2 = 2
    GPIO3 = 3
    GPIO4 = 4
    GPIO5 = 5
    GPIO6 = 6
    GPIO7 = 7
    GPIO8 = 8
    GPIO9 = 9
    GPIO10 = 10
    GPIO11 = 11
    GPIO12 = 12
    GPIO13 = 13
    GPIO14 = 14
    GPIO15 = 15
    GPIO16 = 16
    GPIO17 = 17
    GPIO18 = 18
    GPIO19 = 19
    GPIO20 = 20
    GPIO21 = 21
    GPIO22 = 22
    GPIO23 = 23
    GPIO24 = 24
    GPIO25 = 25
    GPIO26 = 26
    GPIO27 = 27


# What a Pi GPIO device accepts for a pin: a BCM number (17) or a label
# (PiPin.GPIO17). A PiPin *is* an int, so `int(pin)` resolves either.
GPIOLike = int | PiPin
