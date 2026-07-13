# RATA — Raspberry-pi Attached Arduinos

Control LEDs, stepper motors and more on one or more Arduinos from Python. You
describe your hardware in code; the Arduino is configured **at runtime** — no
re-flashing when you add a device. Every command is **non-blocking**, so many
devices can act at once.

```python
from ratapy import Raspberry
from ratapy.boards import Mega
from ratapy.devices import LED

rp = Raspberry(port="/dev/ttyUSB0")
board = Mega("A")
rp.register_arduino(board)

led = LED(pin=2, board=board)
led.on()
led.blink(3)
```

> **Imports:** only `Raspberry` and `RataError` live at the top level. Boards
> come from `ratapy.boards`, everything you attach to a board (devices *and*
> ready-made parts) from `ratapy.devices`, and transports from `ratapy.link`.

> **New here?** This README is the **user guide** (how to *use* RATA). For how
> it works under the hood, read [EXPLANATION.md](EXPLANATION.md). For working on
> the codebase, see [AGENTS.md](AGENTS.md).

> **Prefer a menu?** Run **`./ratapyui`** for a terminal control panel that
> installs dependencies, lists connected boards, shows firmware/device storage,
> and flashes Arduinos — all interactively. Each of those is also a standalone
> script. See [ratapyUI/README.md](ratapyUI/README.md).

---

## Table of contents

1. [How it works (the short version)](#1-how-it-works-the-short-version)
2. [One-time setup](#2-one-time-setup)
3. [Your first script](#3-your-first-script)
4. [Concepts: Raspberry, board, device](#4-concepts-raspberry-board-device)
5. [Pins: numbers or labels](#5-pins-numbers-or-labels)
6. [Devices](#6-devices)
   - [DigitalOutput](#digitaloutput)
   - [PWM](#pwm)
   - [Servo](#servo)
   - [DigitalInput](#digitalinput)
   - [AnalogInput](#analoginput)
   - [Ultrasonic (HC-SR04)](#ultrasonic-hc-sr04)
   - [DHT (temperature + humidity)](#dht-temperature--humidity)
   - [RotaryEncoder](#rotaryencoder)
   - [StepperWithDriver](#stepperwithdriver)
   - [Ready-made components](#ready-made-components)
   - [Devices on the Pi itself (Camera, NeoPixel)](#devices-on-the-pi-itself-camera-neopixel)
   - [The Pi as a USB gamepad (Gamepad, Storage)](#the-pi-as-a-usb-gamepad-gamepad-storage)
7. [Non-blocking: everything runs in the background](#7-non-blocking-everything-runs-in-the-background)
8. [Starting actions together (ParallelExecutor)](#8-starting-actions-together-parallelexecutor)
9. [Multiple boards & I2C](#9-multiple-boards--i2c)
10. [Supported boards](#10-supported-boards)
11. [Errors you might see](#11-errors-you-might-see)
12. [Troubleshooting](#12-troubleshooting)
13. [API cheat sheet](#13-api-cheat-sheet)

---

## 1. How it works (the short version)

There are two programs:

- **The firmware** runs on the Arduino. It boots knowing *nothing* about your
  hardware and waits for instructions.
- **`ratapy`** runs on your PC / Raspberry Pi. It tells the Arduino what devices
  exist ("an LED on pin 2") and then drives them.

They talk over **USB serial** or an **I2C bus** (many Arduinos on two wires) —
see [Multiple boards & I2C](#9-multiple-boards--i2c). You only ever touch the
Python side.

```
your script  →  ratapy  →  USB cable  →  Arduino firmware  →  the pin/motor
```

---

## 2. One-time setup

> **Fastest path (Debian/Ubuntu/Raspberry Pi OS):** the one-command installer sets
> up a private Python runtime, the RATA env, Arduino CLI + core/libraries, serial
> permissions and the `rata` / `ratapyui` commands — then runs `rata doctor`.
> On a fresh machine you don't even need the repo (only `curl`):
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/Sammahacktz/ratapy/main/install.sh | bash
> # with flags:
> curl -fsSL https://raw.githubusercontent.com/Sammahacktz/ratapy/main/install.sh | bash -s -- --pi --usb-gadget
> ```
>
> That URL is stable and always installs the newest **release**. From a checkout,
> the same script:
>
> ```bash
> bash install.sh                     # base
> bash install.sh --pi --usb-gadget   # + Pi camera/NeoPixel + USB gamepad
> ```
>
> Afterwards, keep it current with `rata check` / `rata update` (or the control
> panel's **Find updates** page).
>
> You still flash the firmware onto each Arduino (below). Full details and the
> manual/developer setup: [docs/INSTALL.md](docs/INSTALL.md).

### a) Flash the firmware onto the Arduino

RATA uses the standalone **arduino-cli** (not the VS Code extension). Install it
once, add the AVR core and the firmware libraries, then flash with
`firmware/flash.sh`:

```bash
# once: install arduino-cli into ~/.local/bin
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh \
    | BINDIR="$HOME/.local/bin" sh
arduino-cli core update-index
arduino-cli core install arduino:avr
arduino-cli lib install AccelStepper DHTStable

# flash (choose your board model)
./firmware/flash.sh --board mega
./firmware/flash.sh --board uno --port /dev/ttyUSB0
```

Boards: `mega`, `uno`, `nano`, `leonardo`, `micro`. Any other AVR board works
too — pass its arduino-cli FQBN instead of `--board`, e.g.
`./firmware/flash.sh --fqbn arduino:avr:pro:cpu=8MHzatmega328` (the firmware
auto-tunes to the chip). Your serial port may be `/dev/ttyUSB0` or `/dev/ttyACM0`
(see [Troubleshooting](#12-troubleshooting)). For an I2C board, add
`--i2c <address>` — see [Multiple boards & I2C](#9-multiple-boards--i2c).

> You only re-flash when the **firmware** changes — not when you add or change
> devices in your Python script.

### b) Use RATA from your own project

`install.sh` gives you the **tools** (`rata`, `ratapyui`) in a private environment
of their own — it does **not** put `ratapy` on your system Python. Your own
project gets the `ratapy` **library** as an ordinary dependency, in **its own
virtual environment**. That way you add whatever packages you like next to it, and
your editor resolves `ratapy` with no extra configuration.

> **Why a venv at all?** On Debian 12 / Raspberry Pi OS **Bookworm** the system
> Python is *externally managed* ([PEP 668](https://peps.python.org/pep-0668/)):
> a plain `pip install anything` is refused with `error:
> externally-managed-environment`. A venv is the supported way around it — this is
> a Debian/Raspberry Pi policy, not a RATA one. RATA needs **Python ≥ 3.11**, which
> is exactly what Bookworm ships, so its own `python3` is good enough.

#### The quickest way — let RATA scaffold it

```bash
rata start-project myapp
```

That does the whole dance below for you and leaves you ready to code:

```
myapp/
  myapp_venv/         its own environment, with ratapy already installed
  main.py             a starter script (blink an LED)
  .vscode/            points VS Code at it, so imports resolve immediately
  .gitignore
```

```bash
cd myapp
source myapp_venv/bin/activate   # now plain `python` / `pip` mean this project's
python main.py
pip install requests             # your own packages, as usual
```

`ratapy` is installed **editable** from the RATA install, so there is no second
copy of the source and `rata update` reaches your project too — **updating is
just `rata update`, with nothing to do in the project itself**. The one exception
is an update that adds a *new dependency*: `rata update` only re-syncs RATA's own
environment, so re-run `pip install -e ~/.local/share/rata` in your activated
project venv if an import starts failing afterwards. The venv is built
with RATA's own interpreter, so it is new enough regardless of what `python3`
points at, and it is named after the project — so an activated shell says
`(myapp_venv)` rather than a `(.venv)` shared by every project you have open.
Omit the name (`rata start-project`) to scaffold into the current directory. The
rest of this section is the same thing done by hand.

#### The simple way — plain `venv` + `pip` (no uv, no poetry)

```bash
# 1. one-time: Debian/Pi OS ships venv separately
sudo apt install -y python3-venv

# 2. make your project and its environment
mkdir -p ~/myproject && cd ~/myproject
python3 -m venv .venv

# 3. activate it -- your prompt gains a (.venv) prefix
source .venv/bin/activate

# 4. install RATA into it (pip now works: you are inside a venv, PEP 668 no longer applies)
pip install "ratapy @ git+https://github.com/Sammahacktz/ratapy.git@v1.0.0"

# 5. ...and whatever else your project needs
pip install requests

# 6. write and run your code with plain `python`
python my_script.py
```

That is the whole thing. While the venv is active, `python` and `pip` mean *this
project's* Python and pip; `deactivate` returns you to the system one. You only
have to `source .venv/bin/activate` again in each new terminal.

**VS Code / Pylance:** open the `~/myproject` folder, then
*Ctrl+Shift+P → “Python: Select Interpreter”* → pick `./.venv/bin/python`. Pylance
then resolves `from ratapy import Raspberry` and gives you autocomplete. (It
usually offers `.venv` automatically.)

#### With uv or Poetry

Same idea, less typing — they create and manage the venv for you:

```bash
uv init myproject && cd myproject

# either: pin a release (portable -- this pyproject.toml works on any machine)
uv add "git+https://github.com/Sammahacktz/ratapy.git@v1.0.0"

# or: follow the system install (no second copy; tracks `rata update`)
uv add --editable ~/.local/share/rata

uv add requests                  # your own dependencies, as usual
uv run python my_script.py       # no activate needed
```

Poetry: `poetry add git+https://github.com/Sammahacktz/ratapy.git#v1.0.0`.

> **Don't install your project's packages into `~/.local/share/rata/.venv`.** That
> environment belongs to the installer: `rata update` runs `uv sync`, which makes
> it match RATA's lockfile *exactly* and **silently uninstalls** anything else.
> Keep your project in its own venv, as above.

To hack on RATA itself from a source checkout, `uv sync` in the checkout and run
with `uv run python your_script.py`.

> Driving Arduinos needs nothing more. For **Camera / NeoPixel on a Raspberry
> Pi**, your project venv also needs to see apt's `python3-picamera2` — create it
> with `python3 -m venv --system-site-packages .venv` (or `uv venv
> --system-site-packages`) and add `pip install rpi_ws281x`. See
> [Devices on the Pi itself](#devices-on-the-pi-itself-camera-neopixel) and
> [docs/INSTALL.md](docs/INSTALL.md).

---

## 3. Your first script

Blink an LED wired to pin 2 (via a resistor to ground). This is
[example.py](example.py):

```python
import time
from ratapy import Raspberry
from ratapy.boards import Mega
from ratapy.devices import LED

rp = Raspberry(port="/dev/ttyUSB0")   # connect to the board
board = Mega("A")                     # say which model it is
rp.register_arduino(board)            # register + sanity-check the firmware

led = LED(pin=2, board=board)         # declare the LED

led.on()
time.sleep(2)
led.off()

led.blink(10, on=0.2, off=0.1)        # 10 fast blinks
```

```bash
uv run python example.py       # or just: python example.py (after install.sh)
```

---

## 4. Concepts: Raspberry, board, device

RATA mirrors your physical setup with three kinds of object:

| Object | Represents | You write |
|--------|-----------|-----------|
| **`Raspberry`** | the controller/PC that owns the connection | `rp = Raspberry(port="/dev/ttyUSB0")` |
| **board** (`Mega`, `Uno`, `Nano`) | one Arduino | `board = Mega("A")` |
| **device** (`LED`, `StepperWithDriver`) | one thing plugged into the board | `led = LED(pin=2, board=board)` |

**The `"A"` is a name/address for the board.** On serial it's just a label. On
I2C it's the board's real 7-bit bus address (an `int` like `0x08`) — see
[Multiple boards & I2C](#9-multiple-boards--i2c).

**`register_arduino` does two things:** it links the board to the connection,
and it pings the Arduino to check the flashed firmware matches the model you
declared (warns you if, say, you put `Uno(...)` but flashed a Mega).

**The `board=` argument is optional.** If you leave it out, the device attaches
to the most recently registered board:

```python
rp = Raspberry(port="/dev/ttyUSB0")
board = Mega("A")
rp.register_arduino(board)

led = LED(pin=2)          # same as LED(pin=2, board=board)
```

Pass `board=` explicitly once you have more than one board.

### Cleaning up

`Raspberry` is a context manager, so you can let it close the port for you:

```python
with Raspberry(port="/dev/ttyUSB0") as rp:
    board = Mega("A")
    rp.register_arduino(board)
    LED(pin=2).blink(3)
# port closed automatically here
```

### Remembering devices after the script ends

Normally a board forgets its devices when it loses power or resets (the setup
lives only in its RAM). Call **`board.save_devices()`** once after configuring
them and the board writes the list to its **EEPROM** and re-creates them on every
boot — so the wiring survives a power-cycle, and tools like the control panel can
still list what's attached to a board that no script is driving:

```python
board = Mega("A")
rp.register_arduino(board)
LED(pin=13, board=board)
Servo(pin=9, board=board)
board.save_devices()          # persist -> survives reset / power-cycle
```

It saves the device *configuration* (pins, types), not runtime state (an LED's
on/off). EEPROM has a finite (~100k) write life, so call it when your setup
changes, not in a loop. To forget the saved set: `board.reset()` then
`board.save_devices()` again.

---

## 5. Pins: numbers or labels

Anywhere a device takes a pin you can give it the number, or the **label printed
on the board** — `AnalogPin.A0` for the pin marked A0:

```python
from ratapy.boards import AnalogPin

LED(pin=13, board=board)            # a pin number
LED(pin=AnalogPin.A0, board=board)  # the pin marked A0
```

A label is resolved against **the board the device is on**, because the same
label is a different pin number on each model — A0 is pin 14 on an Uno, 54 on a
Mega, 18 on a Leonardo. You never have to look that up, and the same
`AnalogPin.A0` is right on every board. Asking for a pin the board doesn't have
is an error you get before anything is sent:

```
>>> LED(pin=AnalogPin.A6, board=uno)
ValueError: uno has no A6 (it has A0..A5)
```

For analog **reads**, the same label means the channel, which is what those
devices want:

```python
Potentiometer(channel=AnalogPin.A2, board=board)   # channel 2 on every model
Potentiometer(channel=2, board=board)              # the same
```

> **Nano quirk.** A6/A7 are ADC-only — real analog channels with no digital pin
> number at all. `Potentiometer(channel=AnalogPin.A6)` works;
> `LED(pin=AnalogPin.A6)` tells you why it can't.

---

## 6. Devices

### DigitalOutput

A single on/off output on **any** digital pin — an LED, a relay, a MOSFET.

```python
from ratapy.devices import DigitalOutput

out = DigitalOutput(pin=2, board=board)

out.on()                       # pin HIGH
out.off()                      # pin LOW
out.toggle()                   # flip it
out.is_on                      # -> True / False (local state)

out.blink(5)                   # blink 5 times (0.5 s on, 0.5 s off)
out.blink(5, on=0.1, off=0.1)  # faster
out.blink(0)                   # blink forever (until on()/off())
out.wait()                     # block until a finite blink finishes
```

`blink()` is **non-blocking**: the board does the blinking on its own, so
`blink()` returns immediately, several devices blink at once, and it works inside
a `ParallelExecutor`. Use `wait()` (or `is_busy`) when you want to wait for it.

> For readable code, use the friendly names built on `DigitalOutput` from
> `ratapy.devices`: **`LED`**, **`Relay`**, **`Buzzer`** — same thing, clearer
> intent. `from ratapy.devices import LED` then `LED(pin=2)`.

### PWM

A variable-brightness / variable-power output (`analogWrite`) — LED dimming, DC
motor speed via a driver, buzzer volume. Must be on a **PWM-capable pin**
(checked for you against the board).

```python
dimmer = PWM(pin=9, board=board)

dimmer.set(128)              # duty 0..255
dimmer.fraction(0.25)        # 0.0..1.0
dimmer.off()                 # = set(0)

dimmer.fade(255, duration=1) # smooth ramp — non-blocking; dimmer.wait()
dimmer.pulse(3, period=2)    # "breathe" 3x (0 = forever)
dimmer.blink(5, on=0.2)      # blink between full and off
```

### Servo

A hobby servo. Non-blocking — the board holds the position.

```python
servo = Servo(pin=9, board=board)

servo.angle(90)            # snap to 90 (0..180)
servo.move(0, duration=1)  # sweep smoothly to 0 over 1 s — non-blocking
servo.wait()               # block until it arrives
```

> On an Uno, the Servo library uses Timer1, which disables `PWM` on pins 9 & 10
> while any servo is attached. Put PWM outputs elsewhere if you also use servos.

### DigitalInput

A button, switch, PIR motion sensor, or limit switch. `read()` / `.value` returns
`True` for HIGH, `False` for LOW.

```python
button = DigitalInput(pin=4, pull_up=True, board=board)

if button.value:       # reads the pin right now
    print("HIGH")
```

With `pull_up=True` the internal resistor is enabled, so a button wired to
ground reads `True` when released and `False` when pressed (no external resistor
needed).

**Pull-up vs pull-down.** A floating input pin picks up noise and reads randomly,
so it needs a resistor to hold it at a known level until something drives it. You
have two choices:

| | wiring | at rest | when pressed | `pull_up=` |
|---|---|---|---|---|
| **pull-up** | button to **GND** | HIGH (`True`) | LOW (`False`) | `True` — internal, nothing to add |
| **pull-down** | button to **VCC** | LOW (`False`) | HIGH (`True`) | `False` + an **external** ~10 kΩ pin→GND resistor |

Arduino (AVR) chips have an internal pull-**up** but **no internal pull-down** —
the silicon simply doesn't have one. So for a pull-down you supply the resistor
yourself and use `pull_up=False` (a plain floating input). `Button` is the
friendly wrapper for the common pull-up case; for pull-down wiring use
`DigitalInput` and read `.value` directly (`True` == pressed).

### AnalogInput

A potentiometer, LDR, or any sensor that outputs a voltage. `channel` is the
analog channel number — `0` for **A0**, `1` for **A1**, and so on.

```python
pot = AnalogInput(channel=0, board=board)   # A0

pot.value        # raw ADC reading, 0..1023
pot.fraction     # 0.0..1.0
pot.voltage()    # volts (pass vref=3.3 if your board runs at 3.3 V)
```

The firmware returns the **raw** reading; you convert to real units
(temperature, distance, lux…) here in Python — that's where the sensor-specific
math belongs. Each access (`.value`, `.voltage()`) reads the pin fresh.

### Ultrasonic (HC-SR04)

A cheap ultrasonic distance sensor.

```python
sonar = Ultrasonic(trigger=7, echo=8, board=board)

sonar.distance_mm    # millimetres (int), or None if nothing echoed back
sonar.distance_cm    # centimetres (float), or None
```

Reading waits for the echo, which briefly blocks the board (up to ~25 ms) — fine
on demand, but don't poll it in a tight loop that also drives motors.

### DHT (temperature + humidity)

A DHT11 or DHT22 (AM2302) sensor. Both values come back in **one** read.

```python
dht = DHT(pin=4, kind=22, board=board)   # kind is 11 or 22

reading = dht.read()
print(reading.temperature, "°C", reading.humidity, "%")
```

A DHT is slow — leave ~2 s between reads or it reports an error (raised as
`RataError`). This is the first **multi-value** sensor; the wire protocol was
generalized so one read returns any number of values (see EXPLANATION.md).

### RotaryEncoder

An incremental rotary encoder (quadrature, e.g. a KY-040 module).

```python
from ratapy.devices import RotaryEncoder

knob = RotaryEncoder(clk=2, dt=3, board=board)

knob.position      # signed count since the last reset (+/- as you turn)
knob.detents       # whole clicks (position / steps_per_detent)
knob.reset()       # zero the count
```

The **board** decodes the pulses — they arrive far faster than the master could
poll — and you just read the running total. Most encoders emit ~4 counts per
physical click; set `steps_per_detent=` if yours differs. The push button on a
KY-040 is a separate `Button` on its SW pin.

### StepperWithDriver

A 4-wire stepper motor on a driver board (e.g. the common **28BYJ-48 + ULN2003**
kit).

```python
stepper = StepperWithDriver(pins=[8, 10, 9, 11], board=board)

stepper.step(200, speed=100)   # +200 steps at 100 steps/second (non-blocking!)
stepper.step(-50)              # 50 steps backwards (default speed 200)

stepper.is_moving              # -> True while the motor is still turning
stepper.wait()                 # block here until the current move finishes
stepper.wait(timeout=5)        # ...or give up after 5 s (raises RataError)

stepper.run(300)               # spin continuously at 300 steps/s (−ve = reverse)
stepper.stop()                 # halt a move or a run, and release the coils
```

- `steps` is a **relative** move; negative reverses direction. Range: a signed
  16-bit int (−32768…32767).
- `speed` is in **steps per second** (1…65535).
- `step()` returns in a few milliseconds — the motor keeps turning in the
  background. Use `is_moving` / `wait()` to know when it's done.
- `run(speed)` turns **forever** (for wheels/conveyors) until `stop()` — don't
  `wait()` on it, it never ends. `stop()` also halts a `step()` move early.

> **Pin order matters.** For a 28BYJ-48 on a ULN2003 board, pass the pins in
> **IN1, IN3, IN2, IN4** order — that's the coil sequence the underlying library
> expects. If the motor buzzes without turning, swap the middle two.

### Ready-made components

For common parts there are friendlier classes built on the primitives above —
same wiring, nicer methods. Use these first; drop to the primitive when you need
something they don't cover.

| Component | Built on | Highlights |
|-----------|----------|------------|
| `LED(pin)` | DigitalOutput | `on/off/toggle`, `blink()` (the friendly on/off LED) |
| `DimmableLED(pin)` | PWM | `on/off/toggle`, `brightness(%)`, `fade_to(%, secs)`, `blink()`, `pulse()` |
| `DCMotor(pin)` | PWM | `speed(%)`, `stop()`, `is_running` (one direction) |
| `Mosfet(pin)` | PWM | `on/off/toggle`, `level(%)`, `fade_to(%, secs)` — a silent relay that can do partial power |
| `Relay(pin, active_low=)` | LED | `on/off/toggle` on any digital pin (mechanical switch) |
| `Buzzer(pin)` | LED | `beep(duration, times)` (active buzzer) |
| `ContinuousServo(pin)` | Servo | `speed(-100..100)`, `stop()` (continuous-rotation servo) |
| `Potentiometer(channel)` | AnalogInput | `percent`, `map_to(low, high)` |
| `LightSensor(channel)` | AnalogInput | `level` (0–100), `is_dark()`, `is_bright()` |
| `TMP36(channel)` | AnalogInput | `celsius`, `fahrenheit` (TMP36 temperature sensor) |
| `SoilMoisture(channel, dry=, wet=)` | AnalogInput | `moisture` (0–100, calibrated) |
| `Button(pin)` | DigitalInput | `is_pressed` (level), **`was_pressed`/`was_released`** (edge, once per press), `held_seconds`, `pressed_for(s)`, `wait_for_press()`, `wait_pressed_for(s)` |
| `LimitSwitch(pin)` | Button | same API, but **closed at rest** (end-stops, e-stops, reed switches) |
| `MotionSensor(pin)` | DigitalInput | `motion_detected`, `wait_for_motion()` (PIR) |
| `RotarySwitch(pins=[...])` | N× DigitalInput | `position` (selected index), `count` (composite) |
| `RGBLED(red, green, blue)` | 3× PWM | `color(r, g, b)`, `off()` (composite) |
| `Joystick(x_channel, y_channel, button_pin=)` | 2× pot + button | `x`, `y` (−1..1), `is_pressed` (composite) |

```python
from ratapy.devices import DimmableLED, Potentiometer, Button

light = DimmableLED(pin=9)
knob  = Potentiometer(channel=0)
button = Button(pin=4)

light.brightness(knob.percent)     # dial the knob to set brightness
if button.is_pressed:
    light.pulse()
```

#### Buttons: level vs edge

The single most common bug with a button is using `is_pressed` in a loop.
It is a **level** — true on *every* poll while a finger is down — so a 50 Hz
loop fires the same action fifty times a second:

```python
while True:
    if button.is_pressed:      # DON'T -- fires ~50x per press
        gripper.close()
    time.sleep(0.02)
```

**`was_pressed` is the edge**: true *once* per press, however long it is held.
Reading it consumes that press.

```python
while True:
    if button.was_pressed:     # DO -- exactly once per press
        gripper.close()
    time.sleep(0.02)
```

That replaces the usual `was_pressed = pressed` bookkeeping, and there is no
"now wait for them to let go" loop to remember. A quick tap that starts *and*
ends between two reads is still reported — nothing is lost, as long as some read
saw the button down.

`was_released` is the pair, for acting when the finger comes off. It reads well
with `held_seconds`, which freezes at the length of the press that just ended:

```python
if button.was_released:
    if button.held_seconds > 2:
        factory_reset()        # it was a long press
    else:
        next_channel()         # a tap
```

Acting on the release is usually what you want for a long press, because nothing
fires while the finger is still down.

#### Long presses: two shapes

`Button` can tell a long press from a tap two ways — the difference is who does
the waiting.

**`pressed_for(seconds)` asks about right now** and returns immediately. Call it
in your loop: thresholds stack, and nothing else is held up.

```python
while True:
    if button.pressed_for(6):
        power_off()
    elif button.pressed_for(4):
        reboot()
    camera.update()                # keeps running -- the button blocks nothing
```

It times the hold from the first read that *saw* the button down, so it only
knows about presses it was watching — ask once, cold, and the answer is False
however long the button has really been held. (Any read keeps that clock
running, including your own `if button.is_pressed:`.)

**`wait_pressed_for(seconds)` sits and watches**, for when you already have a
press in your hands:

```python
button.wait_for_press()

if button.wait_pressed_for(2):
    light.off()                    # held 2 s
else:
    light.toggle()                 # let go early — a quick tap
```

That one blocks (up to `seconds`), but returns the moment the answer is known —
False as soon as the button comes up, rather than sitting out the full wait.

#### Switches that are closed at rest

A push button is *normally open*: the circuit is broken until you press it. Limit
switches, e-stops and reed switches are the opposite — **normally closed**, so
they conduct at rest and break when actuated. Every reading inverts.

Pass `normally_closed=True`, or use `LimitSwitch`, which is the same class with
that default flipped:

```python
from ratapy.devices import LimitSwitch

stop = LimitSwitch(pin=5)          # closed while the axis is free

while stepper.is_moving:
    if stop.is_pressed:            # the switch opened: end reached
        stepper.stop()
        break
```

The inversion happens in one place, so everything else — `was_pressed`,
`held_seconds`, `wait_for_press` — is correct without doing anything special.

> Wire it like a button (switch between the pin and GND, internal pull-up on).
> At rest the switch pulls the pin LOW, which means **a broken wire reads the
> same as "actuated"** — the safe way round for an end-stop, and the reason this
> is the convention.

Because they inherit the primitives, they still work with `ParallelExecutor` and
carry the same pin validation (a `DimmableLED` must be on a PWM pin, etc.).

**Switching a load: `Relay` or `Mosfet`?** A `Relay` is the mechanical one — any
digital pin, on or off, and it can switch AC or an isolated circuit. A `Mosfet`
is solid-state: silent, and fast enough to be driven by PWM, so it also does
*partial* power. That's the reason to pick one, and it's why it needs a
PWM-capable pin:

```python
from ratapy.devices import Mosfet

pump = Mosfet(pin=9)               # load between V+ and drain, gate on pin 9
pump.on()                          # full power
pump.level(40)                     # ...or 40 % of it
pump.fade_to(0, 2)                 # ramp down over 2 s
```

Use a **logic-level** MOSFET — an ordinary one won't turn fully on from 5 V (let
alone 3.3 V) and will overheat half-open. A MOSFET you only ever slam fully on
and off is just a `DigitalOutput` on any pin.

> **Active-low relays can't `blink()`.** `active_low=True` inverts the byte in
> Python, but a blink is run *by the board*, which knows nothing about the
> inversion — every phase would come out backwards and it would finish
> **energised**. RATA refuses it rather than leave your pump switched on; drive
> it with `on()`/`off()`, which do honour the inversion.

### Devices on the Pi itself (Camera, NeoPixel)

Some hardware is too heavy for a little Arduino — a camera, an addressable LED
strip. Those plug straight into the **Raspberry Pi** and run in Python there. The
API is the same; you just pass the Raspberry as the board:

```python
from ratapy import Raspberry
from ratapy.devices import Cam, NeoPixel

rp = Raspberry()                     # no Arduino needed for these

cam = Cam(board=rp)                  # Pi Camera (Picamera2 + OpenCV)
cam.snapshot("photo.jpg")           # grab a frame and save it
cam.record("clip.mp4", 5)           # record 5 seconds
cam.stream()                        # live preview window; press q to quit
for frame in cam.frames(limit=100): # BGR OpenCV images for your own code
    ...

strip = NeoPixel(count=30, board=rp)  # WS2812 strip on GPIO18 (one data pin)
strip.fill((0, 40, 0))              # stage the buffer...
strip[0] = (255, 0, 0)
strip.show()                        # ...then push it to the LEDs
strip.clear()

rp.close()                          # stops the camera, clears the strip
```

These run only on a Raspberry Pi and need extra libraries. The easy way is
`bash install.sh --pi`; the manual equivalent:

```bash
sudo apt install -y python3-picamera2 python3-libcamera libcap-dev
uv venv --system-site-packages        # let the venv see apt's libcamera
uv sync --frozen
uv pip install rpi_ws281x             # NeoPixel driver, built on the Pi
```

The NeoPixel strip usually needs **root** (run with `sudo`). RATA loads these
devices lazily, so importing `ratapy` on a plain laptop still works — you only
hit the missing libraries if you actually create a `Camera`/`NeoPixel` there. Full
details in [docs/INSTALL.md](docs/INSTALL.md); runnable demo in
[example_local.py](example_local.py).

### The Pi as a USB gamepad (Gamepad, Storage)

The Raspberry Pi can also present *itself* to a host PC as a **USB gamepad**, with
its buttons and axes driven by ordinary RATA inputs — the JoystickXL idea, with the
Pi as the HID. Opt in with `usb_device=True` and wire controls to input devices:

```python
rp = Raspberry(port="/dev/ttyUSB0", usb_device=True)
ad = Mega("A")
rp.register_arduino(ad)

pad = Gamepad(board=rp, buttons=2, axes=("x", "y"))
pad.map_button(0, Button(pin=2, board=ad))
pad.map_axis("x", Potentiometer(channel=0, board=ad))
pad.start()          # host now sees a live gamepad; a thread polls the inputs
...
pad.stop()

# The Pi also shows up as a drive; hide it so only the gamepad is exposed:
storage = Storage(board=rp)
storage.hide()       # storage.show() brings the drive back
```

This uses Linux USB gadget mode, so it needs a Pi with **USB-OTG**, a one-time
`sudo ./scripts/setup-usb-gadget.sh` (+ reboot), and **root** to run. On any other
machine it falls back to a logged **simulation** (or pass `usb_strict=True` to make
that an error). See [docs/INSTALL.md](docs/INSTALL.md#5-usb-gamepad--storage-raspberry-pi-gadget)
and [example_gamepad_pi.py](example_gamepad_pi.py).

---

## 7. Non-blocking: everything runs in the background

Every command returns almost immediately — it just hands the goal to the Arduino
(the only things that block on purpose are `wait()` and a sensor read). The Arduino
does the slow work (turning a motor) on its own while staying responsive.

That means devices overlap for free — **no threads, no async needed**:

```python
stepper.step(400, speed=100)   # ~4 s move, returns instantly
led.blink(3)                   # runs WHILE the motor turns
stepper.wait()                 # wait for the motor only when you want to
```

**Every device has `wait()`** (and `is_busy()`), so the same loop shape works for
all of them — it blocks until a background action finishes, and returns
immediately for devices whose commands complete at once (an LED is already done
when `blink()` returns):

```python
while True:
    stepper.step(400)
    stepper.wait()                  # waits for the move

    led.blink(3)
    led.wait()                      # returns at once — nothing to await
```

You do **not** need `ParallelExecutor` for this. Concurrency is automatic. The
executor is only for the *next* section.

### Timing without stopping everything: `sleep()`

`time.sleep()` blocks your whole script, so every device waits with it. That's
usually not what you mean:

```python
led.on()
led2.on()

time.sleep(3)                 # led2 is stuck here too...
led.off()

time.sleep(1)
led2.off()                    # ...so led2 only goes off at t+4
```

**Every device has `sleep(seconds)`**, which delays only *that device's* next
command and returns straight away. Each device keeps its own clock:

```python
led.on()
led2.on()

led.sleep(3)
led.off()                     # led  off at t+3

led2.sleep(1)
led2.off()                    # led2 off at t+1 — it didn't wait for led
```

Both `sleep()` calls return instantly; the commands go out when they're due.
Because they run after your script has moved on, **it has to still be there when
they do** — leave a `with Raspberry()` block (it waits for them), or call
`rp.wait()`:

```python
with Raspberry(port="/dev/ttyUSB0") as rp:
    ...
    led.sleep(3)
    led.off()
# the block exits ~3 s later, once the LED is actually off
```

`rp.wait()` blocks until every deferred command has been sent, and re-raises
anything that went wrong in one (nothing else could tell you). Notes:

- It defers **commands**, not reads: `sensor.value` is always read now, because
  a value has to come back when you ask.
- `sleep()` and `ParallelExecutor` are opposites — one makes a gap, the other
  removes them — so `sleep()` inside an executor block is an error.
- No `sleep()` in your script means no background thread is ever started.

### Whole sequences in the background: `BackgroundTasks`

`sleep()` is a *guess* at how long something takes. For a stepper you can do
better, because `wait()` knows exactly — it just blocks your whole script, which
kills the loop you were reading a joystick in.

Put the sequence on a thread and you get both: `wait()` blocks **that thread**,
and your main loop keeps running.

```python
from ratapy.tasks import BackgroundTasks

with BackgroundTasks() as tasks:

    @tasks.run
    def arm():
        while not tasks.stopping:
            stepper.step(500)
            stepper.wait()              # exact, and blocks only this task
            stepper.step(-500)
            stepper.wait()

    while True:                         # the joystick stays live throughout
        servo.angle(angle_from(joystick.y))
        time.sleep(0.02)
```

Nothing is deferred or rewritten — inside a task every RATA call behaves exactly
as it always does. The block just owns the lifecycle: tasks start when submitted,
are asked to stop when it exits, and are joined before it returns.

**Passing devices to a task.** The decorator form closes over whatever it needs,
but you can also hand `run` the arguments and let it forward them — the tidy way
to give each task exactly the devices it owns, with no globals:

```python
def gripper(trigger, left, right):
    while not tasks.stopping:
        if trigger.was_pressed:
            left.step(500); right.step(-500)
            left.wait(); right.wait()
        tasks.sleep(0.02)

tasks.run(gripper, btn, stepper_L, stepper_R)              # positional
tasks.run(gripper, trigger=btn, left=stepper_L, right=stepper_R)   # or by name
```

The same function can be started more than once with different arguments — one
task per limb — since each call gets its own thread.

**The main reason to use this over a bare `threading.Thread`:** a raw thread whose
target raises prints a traceback to stderr and dies, while your program carries on
with no idea a limb stopped moving. `BackgroundTasks` captures the exception and
re-raises it when the block exits. One failing task also stops its siblings.

A few rules:

- A long-running task must check **`tasks.stopping`**, and use **`tasks.sleep(s)`**
  instead of `time.sleep(s)` so a long pause doesn't hold up shutdown. A task that
  ignores both is reported at exit rather than hanging you.
- **Create your devices on the main thread**, before starting tasks — device
  registration isn't atomic, so two threads can claim the same id.
- **Give each task its own devices** where you can. Sharing one device across
  threads is safe on the wire (the link is locked), but its Python-side
  bookkeeping — an LED's `is_on`, a Button's hold clock — can interleave.
- Keep the block **inside** your `with Raspberry(...)` block, so tasks stop before
  the links close.

**How many tasks?** A thread costs an OS stack (8 MB of *address space*, but only
the few KB it actually touches). The ceiling is memory, not a quota — even a Pi
Zero handles dozens. What goes wrong is spawning one per *event*:

```python
while True:                          # DON'T -- a new thread every 20 ms
    if button.was_pressed:
        tasks.run(do_the_thing)
```

Use a few **long-lived** tasks that loop instead — one per thing that moves:

```python
@tasks.run                           # DO
def arm():
    while not tasks.stopping:
        if button.was_pressed:
            do_the_thing()
        tasks.sleep(0.02)
```

A finished task frees its thread by itself, so you never release anything by
hand. To make the mistake fail loudly rather than gradually, cap it:
`BackgroundTasks(max_workers=4)` refuses to start a fifth *concurrent* task.

#### Without a `with` block

The context manager is the right default — it stops and joins your tasks even
when your code raises. But if the group has to outlive one scope — owned by a
class, closed in its own teardown — open it with `start()` and **you** are then
responsible for `close()`:

```python
tasks = BackgroundTasks().start()
tasks.run(arm, stepper)

try:
    ...                              # your main loop
finally:
    tasks.close()                    # REQUIRED: stops, joins, re-raises task errors
```

`close()` does everything leaving the block did: signals `stopping`, joins every
task, and re-raises the first exception a task hit. It is safe to call twice, and
the group won't accept new tasks afterwards. Skip it and your tasks keep running
as daemon threads until the process exits — and any error they hit is lost, which
is the whole thing `BackgroundTasks` exists to prevent. Put it in a `finally`.

In a class:

```python
class Robot:
    def __init__(self, rp):
        self._tasks = BackgroundTasks().start()
        self._tasks.run(self._arm_loop)

    def close(self):
        self._tasks.close()          # called from the owner's own teardown
```

`close(reraise=False)` tears down without re-raising a task's error — only for
when you're already handling a failure of your own and don't want it masked.

Use `sleep()` for "wait a fixed time"; use a task with `wait()` for "wait until
this actually finishes."

---

## 8. Starting actions together (ParallelExecutor)

Two normal commands start a few milliseconds apart (each is a separate message).
Usually invisible — but when motions must be **synchronized** (say, two wheels
driving straight), use a `ParallelExecutor`. It collects the commands and starts
them all in the same instant.

**Style 1 — `with` block (simplest):**

```python
from ratapy.executor import ParallelExecutor

with ParallelExecutor():
    stepper1.step(200, speed=100)
    stepper2.step(200, speed=100)
# both motors start together right here, on exiting the block

stepper1.wait()
stepper2.wait()
```

Everything inside the block is queued, then fired at the end. If the block
raises an exception, nothing is sent (no half-started motion).

**Style 2 — bind an executor to devices (explicit control):**

```python
pe = ParallelExecutor()
stepper1.set_executor(pe)
stepper2.set_executor(pe)

stepper1.step(200, speed=100)   # queued — motor does NOT move yet
stepper2.step(200, speed=100)   # queued
pe.execute()                    # both start together, now

stepper1.remove_executor()      # back to immediate commands
stepper2.remove_executor()
```

Only "do this now" commands belong in an executor (`step`, `on`, `off`). Don't
put `blink()` in one — it sleeps between writes and wouldn't make sense batched.

---

## 9. Multiple boards & I2C

One `Raspberry` can drive **several Arduinos at once**, mixing transports. Each
board declares *how* it's connected when you create it — via `link=`.

### Serial (one USB cable per Arduino)

```python
from ratapy import Raspberry
from ratapy.boards import Mega, Uno
from ratapy.link import SerialLink

rp = Raspberry()
a1 = Mega("A", link=SerialLink("/dev/ttyUSB0"))
a2 = Uno("B",  link=SerialLink("/dev/ttyUSB1"))
rp.register_arduino(a1, a2)
```

(The single-board shortcut `Raspberry(port="/dev/ttyUSB0")` just sets a *default*
link, used by any board created without its own `link=`.)

### I2C (many Arduinos on one 2-wire bus)

Share **one** `I2CLink` across all boards on the bus; each board has a distinct
7-bit address (`0x08`–`0x77`):

```python
from ratapy import Raspberry
from ratapy.boards import Uno, Mega
from ratapy.link import I2CLink

bus = I2CLink(bus=1)               # /dev/i2c-1 on a Raspberry Pi
rp = Raspberry()
a1 = Uno(8, link=bus)              # address is a plain number (0x08 also works)
a2 = Mega(9, link=bus)
rp.register_arduino(a1, a2)

led = LED(pin=13, board=a1)        # exactly the same device API
led.on()
```

### Mixing both at once

```python
rp = Raspberry(port="/dev/ttyUSB0")     # default serial link
bus = I2CLink(bus=1)

usb_board = Mega("A")                    # on the default serial link
i2c_board = Uno(8, link=bus)             # on I2C, address 8
rp.register_arduino(usb_board, i2c_board)
```

**I2C requires a matching firmware build.** A serial Arduino runs the default
firmware; an I2C Arduino must be flashed *with its address* so it joins the bus
as a slave. The flash helper does this from a plain number:

```bash
./firmware/flash.sh --board uno --i2c 8        # flash an I2C slave at address 8
./firmware/flash.sh --board mega               # (a serial board, for comparison)
```

The `8` here must equal the address you pass in Python (`Uno(8, link=bus)`) —
just an ordinary number, no hex or bytes required. Wiring: connect the Pi's
SDA/SCL/GND to every Arduino's SDA/SCL/GND (a shared bus), with pull-up
resistors on SDA and SCL. Keep I2C messages small — frames must fit the
Arduino's 32-byte I2C buffer (they normally do).

> ## ⚠️ Use a level shifter — 5 V on a Pi pin can destroy it
>
> **A Raspberry Pi's GPIO is 3.3 V and is _not_ 5 V-tolerant. A 5 V Arduino
> (Uno, Nano, Mega) drives its I2C lines to 5 V. Wire the two together directly
> and you can permanently damage the Pi.** Always put a **bi-directional I2C
> level shifter** between a 3.3 V master and a 5 V board: the Pi's SDA/SCL to the
> shifter's LV side, the Arduino's to the HV side, with a **common ground**. This
> is not optional and there is no software setting that makes it safe — it is a
> hardware requirement. (Two boards at the same voltage — e.g. all 3.3 V, or an
> AVR master over serial — don't need one.)

> On I2C, the board `address` is the real bus address (an `int`). On serial it's
> just a label (any string).

---

## 10. Supported boards

| Class | Board | Digital pins | Max devices |
|-------|-------|--------------|-------------|
| `Mega` | Arduino Mega 2560 | 0–69 | 32 |
| `Uno`  | Arduino Uno       | 0–19 (A0–A5 = 14–19) | 12 |
| `Nano` | Arduino Nano      | 0–21 (A0–A7 = 14–21) | 12 |
| `Leonardo` | Arduino Leonardo (ATmega32U4) | 0–30 | 12 |
| `Micro` | Arduino Micro (ATmega32U4) | 0–30 | 12 |
| `Arduino` | generic / other | (no validation) | 8 |

The board class knows its pin layout, so mistakes are caught in Python before
anything is sent:

```python
LED(pin=999, board=Mega("A"))
# ValueError: mega has no pin 999 (valid: 0..69)
```

Use the specific model when you can; `Arduino` is a permissive fallback for
boards not listed here.

### Using a board that isn't listed

The RATA firmware auto-tunes to whatever AVR chip it's compiled for (see
`firmware/rata/BoardConfig.h`), so **any board in the `arduino:avr` core works** —
it just isn't one of the named shortcuts. Two steps:

**1. Flash it** with the `--fqbn` escape hatch instead of `--board` (pass the
board's arduino-cli FQBN — find it with `arduino-cli board listall`):

```bash
./firmware/flash.sh --fqbn arduino:avr:pro:cpu=8MHzatmega328 --port /dev/ttyUSB0
```

**2. Drive it** with the base `Arduino` class — no custom class needed:

```python
from ratapy import Raspberry
from ratapy.boards import Arduino

rp = Raspberry(port="/dev/ttyUSB0")
ad = Arduino("A")            # "A" is just a serial label, not a model name
rp.register_arduino(ad)
```

The base `Arduino` skips Python-side pin validation, so it accepts any pin. You
don't lose safety — the firmware still range-checks every pin against the real
chip and rejects a bad one with a `RataError`. The only catch: the generic class
caps you at **8 devices** (a safe floor), even if the chip supports more.

**Optional — a named class** for nicer errors and the board's real device
ceiling. Only two things matter functionally: `NUM_DIGITAL_PINS` (early pin
validation + the `verify()` "wrong board?" check) and `MAX_DEVICES`. `MODEL` is
**only a label used in error messages** — it is *not* sent to the Arduino and has
nothing to do with the FQBN; name it whatever you like:

```python
from ratapy.boards import Arduino

class ProMini(Arduino):
    MODEL = "promini"                 # appears in error text only
    NUM_DIGITAL_PINS = 22
    NUM_ANALOG_INPUTS = 8             # A0..A7
    PWM_PINS = frozenset({3, 5, 6, 9, 10, 11})
    MAX_DEVICES = 12                  # verify() still caps this to the firmware's value

ad = ProMini("A")
```

`verify()` (run at `register_arduino`) only ever *lowers* `MAX_DEVICES` to what
the firmware reports, so setting it too high is harmless. Off-AVR boards (ESP32,
RP2040, SAMD, STM32) are **not** supported — they need a firmware port.

---

## 11. Errors you might see

RATA fails loudly with readable messages instead of doing nothing.

| Message | Meaning | Fix |
|---------|---------|-----|
| `ValueError: mega has no pin 999 ...` | pin doesn't exist on that board | use a valid pin |
| `RataError: timeout waiting for response` | the board didn't reply | wrong port, unplugged, or firmware not flashed / still booting |
| `RataError: could not open ... Could not exclusively lock port` | another program already has the port | close the other script / control panel — only one program can drive a board over serial at a time |
| `RataError: NACK: unknown device id` | commanding a device the board doesn't have | did you `register` / re-create it after a reset? |
| `RataError: ... is full: mega supports at most 32 devices` | too many devices | you've hit the board's limit |
| `UserWarning: firmware reports 70 digital pins, but uno expects 20` | wrong model class or wrong firmware | match `Uno/Mega/...` to the board you flashed |
| `UserWarning: firmware speaks protocol vN ...` | firmware is out of date | re-flash `firmware/rata` |

`RataError` is the exception type for all communication problems, so you can
`try/except ratapy.RataError:` around risky calls.

---

## 12. Troubleshooting

**Which serial port?** List candidates:

```bash
./firmware/acli.sh board list
ls /dev/ttyUSB* /dev/ttyACM*
```

Clone boards (CH340 chip) usually appear as `/dev/ttyUSB0`; genuine boards often
as `/dev/ttyACM0`.

**Permission denied on the port?** Add yourself to the `dialout` group:

```bash
sudo usermod -aG dialout $USER    # then log out and back in
```

**First command times out right after flashing.** The Arduino reboots when the
port opens and again after an upload; a script that connects *immediately* after
flashing can beat the bootloader. Wait a second and re-run. (RATA already waits
~2 s on connect for the normal case.)

**LED never lights / motor doesn't move.** Check wiring first, then confirm the
firmware is actually on the board:

```bash
./firmware/acli.sh compile --clean --upload -p /dev/ttyUSB0 --fqbn arduino:avr:mega firmware/rata
```

Use `compile --clean --upload` (not a bare `upload`) especially after building
an I2C variant — a plain `upload` can flash a stale cached build, and an I2C
build is silent on serial.

**A stepper buzzes but doesn't turn.** Wrong coil order — swap the middle two
pins (see [StepperWithDriver](#stepperwithdriver)).

---

## 13. API cheat sheet

```python
from ratapy import Raspberry, RataError
from ratapy.boards import Mega, Uno, Nano, Leonardo, Micro
from ratapy.devices import LED
from ratapy.devices import StepperWithDriver
from ratapy.executor import ParallelExecutor

# --- connection & board ---
rp = Raspberry(port="/dev/ttyUSB0", baud=115200)  # or use as: with Raspberry(...) as rp:
board = Mega("A")                    # Uno / Nano / Leonardo / Micro / Arduino("A") for any other
board = Uno(0x08, link=I2CLink(bus=1))            # ...or on an I2C bus
rp.register_arduino(board)           # add verify=False to skip the firmware check
rp.active_board                      # the default board for new devices
rp.close()                           # run anything sleep() deferred, then close every link
rp.wait()                            # block until deferred commands have been sent

# --- transports (per board via link=) ---
from ratapy.link import SerialLink, I2CLink
SerialLink("/dev/ttyUSB1")           # one Arduino per cable
I2CLink(bus=1)                       # one bus shared by many boards (distinct addresses)

board.ping()                         # -> BoardInfo(version, device_count, max_devices, num_digital_pins)
board.reset()                        # drop all devices on this board

# --- LED ---
led = LED(pin=2, board=board)        # board= optional -> active board
led.on()
led.off()
led.toggle()
led.is_on
led.blink(times=1, on=0.5, off=0.5)  # non-blocking (0 = forever); led.wait()

# --- switching a load ---
Relay(pin=7, active_low=False)       # mechanical, any digital pin; .on()/.off()/.toggle()
Mosfet(pin=9)                        # solid-state, PWM pin; .on()/.off()/.toggle()
Mosfet(pin=9).level(40)              # 40 % power; also .fade_to(%, secs), .percent

# --- PWM / servo (outputs) ---
PWM(pin=9).set(128)                  # 0..255; also .fraction(0..1), .off()
PWM(pin=9).fade(255, duration=1)     # non-blocking ramp; also .pulse(), .blink()
Servo(pin=9).angle(90)               # snap; .move(0, duration=1) sweeps smoothly

# every device has .wait() / .is_busy() -- block until a background action ends
# every device has .sleep(s) -- delay ITS next command only; does not block the script
led.on()
led.sleep(3)                         # led alone waits 3 s; other devices carry on
led.off()

# --- inputs / sensors (read fresh each access) ---
DigitalInput(pin=4, pull_up=True).value      # -> bool (HIGH/LOW)
Button(pin=4).is_pressed                     # -> bool; also .wait_for_press()
btn = Button(pin=4)                          # pull-up on by default
btn.is_pressed                               # LEVEL: true every poll while held
btn.was_pressed                              # EDGE: true ONCE per press (use this in loops)
btn.was_released                             # EDGE: true once per release
btn.held_seconds                             # how long it is/was down; freezes on release
btn.pressed_for(2)                           # -> down NOW and held 2s? instant; poll it
btn.wait_pressed_for(2)                      # -> watches up to 2 s; True if never let go
btn.wait_for_press(); btn.wait_for_release() # blocking
LimitSwitch(pin=5).is_pressed                # a Button that is CLOSED at rest
AnalogInput(channel=0).value                 # -> 0..1023  (A0); also .fraction, .voltage()
Ultrasonic(trigger=7, echo=8).distance_mm    # -> int mm or None; also .distance_cm
DHT(pin=4, kind=22).read()                   # -> DHTReading(temperature, humidity)
RotaryEncoder(clk=2, dt=3).position          # signed count; also .detents, .reset()
RotarySwitch(pins=[2,3,4,5]).position        # selected index or None (from components)

# --- stepper ---
st = StepperWithDriver(pins=[8, 10, 9, 11], board=board)
st.step(steps, speed=200)            # relative, non-blocking
st.run(300)                          # spin forever (−ve = reverse); st.stop()
st.is_moving                         # True while turning
st.wait(timeout=None, poll=0.02)     # block until done

# --- background tasks (blocking calls, without blocking your loop) ---
from ratapy.tasks import BackgroundTasks
with BackgroundTasks(max_workers=None) as tasks:   # max_workers caps CONCURRENT tasks
    @tasks.run                       # decorator form: starts it on its own thread
    def arm():
        while not tasks.stopping:    # long tasks MUST check this
            stepper.step(500)
            stepper.wait()           # blocks this task only
            tasks.sleep(0.02)        # use instead of time.sleep, so stop is prompt
    tasks.run(gripper, btn, left, right)   # or pass the task its devices
    ...                              # your main loop, still live
# exit: tasks stopped + joined; a task's exception is re-raised here
tasks.running                        # how many are still alive
tasks.stop()                         # ask them to finish early

tasks = BackgroundTasks().start()    # no `with`: you must close() it yourself
tasks.run(arm, stepper)
try: ...
finally: tasks.close()               # stops, joins, re-raises task errors

# --- start together ---
with ParallelExecutor():             # everything inside starts at once on exit
    st.step(100)
    other.step(100)

pe = ParallelExecutor()              # or bind explicitly:
st.set_executor(pe)
st.step(100)                         # queued, not sent
pe.execute()                         # fires everything queued on pe
st.remove_executor()                 # back to immediate commands

# --- errors ---
RataError                            # communication problems (NACK, timeout, bad frame)
```

Command line (after [`install.sh`](install.sh)):

```bash
rata doctor                  # health check: toolchain, perms, serial ports, hardware
rata ui                      # the control panel TUI (same as `ratapyui`)
rata start-project myapp     # scaffold myapp/: venv + ratapy + a starter script
rata check                   # newer release available?  (exit 0 = no, 10 = yes)
rata update                  # update to the latest release + re-sync dependencies
rata check --pre-release     # ... track master (bleeding edge) instead
rata uninstall               # remove the RATA env + launchers
rata version
```
