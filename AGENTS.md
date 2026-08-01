# AGENTS.md — working on RATA

Guidance for AI agents and contributors working in this repo. Read this before
changing code. User-facing docs are [README.md](README.md) (how to use) and
[EXPLANATION.md](EXPLANATION.md) (how it works, in depth).

## What this project is

RATA ("Raspberry-pi Attached Things") lets a master (Raspberry Pi / PC) control
devices (LEDs, steppers, …) on one or more Arduinos, configured **dynamically at
runtime** over a byte protocol. Two programs, one contract:

- **`ratapy/`** — the Python master library (runs on the PC/Pi).
- **`firmware/rata/`** — the Arduino C++ firmware (one image, any devices).
- Transport is **USB serial** or **I2C**, chosen per board; the same framing runs
  over both (`Link`/`Transport`). Both are hardware-tested — see the Transports
  section for what I2C still has unverified.

## Repo layout

```
ratapy/                 Python master library (strict-typed, mypy-clean)
  protocol.py           wire constants + framing (checksum, build_frame, Frame, Address)
  link.py               Link (ABC): framed transport. SerialLink + I2CLink (smbus2)
  raspberry.py          Raspberry -- registry, active board, default link; routes per board
  boards.py             Arduino base + Uno/Nano/Mega models; holds its own link + address
  devices/              subpackage; import all devices from `ratapy.devices`
    __init__.py         re-exports all groups (the single import surface)
    abstract_devices.py PURE abstract contracts (no logic): AbstractLED/Servo/Button/... Each Arduino device AND its Pi twin inherit the matching one, so the two are GUARANTEED the same methods. Abstract base goes LAST in the bases tuple (so a concrete/inherited impl wins over the abstractmethod in the MRO -> __abstractmethods__ resolves empty). Exported from `ratapy.devices`; type against them for transport-agnostic code. NO abstract for the analog family (no Pi ADC) or not-yet-ported devices.
    complex_devices.py  devices needing FIRMWARE support (a matching Device subclass in the sketch): DigitalOutput, PWM, Servo, DigitalInput, AnalogInput, StepperWithDriver, Ultrasonic, DHT, DS18B20 (+DS18S20/DS1822 aliases), RotaryEncoder, ADXL345 (I2C accelerometer, serial boards only)
    simple_devices.py   "simple" devices: pure-Python conveniences (inherit/compose the complex ones, NO new firmware): LED/Relay/Buzzer/Solenoid (DigitalOutput), DimmableLED/DCMotor/Mosfet (PWM, via the shared _PercentPWM base), ContinuousServo (Servo), Potentiometer/LightSensor/TMP36/SoilMoisture (AnalogInput), MQ2 (AnalogInput+DigitalInput gas/smoke composite), Button/MotionSensor (DigitalInput), RGBLED/Joystick/RotarySwitch (composites)
    local/              MASTER-attached devices: driven in Python on the Raspberry Pi itself. base.py = LocalDevice (now also has is_busy()/wait()/_mark_busy so Pi devices drive like an Arduino Device, incl. inside BackgroundTasks). Two sorts: (a) HEAVY devices that can't sit on an Arduino -- camera.py PiCamera/PiCam (Picamera2+OpenCV), neopixel.py PiNeoPixel (rpi_ws281x), adxl345.py PiADXL345 (smbus2; shares AccelReadout w/ Arduino ADXL345), radar.py PiRadar (RD-03D UART; decode UNVERIFIED), audio.py PiMicrophone/PiSpeaker (sounddevice); (b) GPIO TWINS of the Arduino devices, gpiozero-backed -- outputs.py (PiLED/PiRelay/PiBuzzer/PiSolenoid/PiDigitalOutput + PiPWM/PiDimmableLED/PiDCMotor/PiMosfet/PiRGBLED), inputs.py (PiDigitalInput/PiButton/PiLimitSwitch/PiMotionSensor/PiUltrasonic/PiRotaryEncoder), servos.py (PiServo/PiContinuousServo). GPIO twins inherit the same Abstract* as their Arduino counterpart -- SEPARATE code, shared contract only. Pins are BCM GPIO numbers; pins.py = PiPin (IntEnum GPIO2..GPIO27, value IS the BCM number so it drops in wherever an int pin is expected -- disambiguates BCM vs physical-header numbering; pure enum, exported eagerly from ratapy.devices, no gpiozero). Effects (blink/fade/pulse/move) run on GPIOZERO's own background threads (its blink/pulse + `source` for fades) -- RATA spawns NO threads for these (gpiozero is the Pi's "firmware"); is_busy()/wait() work off a computed completion time (_busy_until), no thread introspection. ALL master-attached devices carry a `Pi` prefix (PiADXL345 vs ADXL345); all top-level exported from `ratapy.devices`. board= is the Raspberry, NOT an Arduino. No firmware/Link/protocol. Backing libs imported at MODULE TOP; devices/__init__ loads local/ lazily (__getattr__) so RATA still imports off-Pi. gpiozero IS a base dep (pure-Python, imports anywhere); its pin backend lgpio is Pi-only (`rata pi`). picamera2/rpi_ws281x/sounddevice = optional `pi` group
  __init__.py           slim: exposes only Raspberry + RataError; everything else via submodules
  executor.py           ParallelExecutor (staged/batched writes; ContextVar-based)
firmware/rata/
  rata.ino              setup()/loop(), command dispatch, stage/commit buffer, I2C callbacks
  Config.h              transport choice: define RATA_I2C_ADDRESS -> I2C slave, else serial
  Protocol.h            wire constants (TWIN of protocol.py -- keep in sync!)
  Transport.h           Transport (ABC) + SerialTransport + WireTransport (I2C, buffered reply)
  FrameParser.h         byte-wise frame parser (state machine)
  Devices.h             Device base + DigitalOutput/DigitalInput/PWMOutput/ServoDevice/StepperDevice/AnalogInput + DeviceManager
  BoardConfig.h         per-board limits chosen at compile time (MAX_DEVICES, ...)
firmware/acli.sh           wrapper that finds a standalone arduino-cli
ratapyUI/               terminal control panel (curses TUI) + standalone ops
  app.py / pages.py     TUI shell (App, Page/DetailPage) + the concrete pages
  theme.py              glyphs/colours/ASCII wordmark + ANSI+text bars (no curses)
  tui/screen.py,widgets.py  reusable curses toolkit (Box/Menu/LogPane, palette, mouse)
  ops/                  the actual work, each DUAL-USE (TUI + `python -m ratapyUI.ops.<x>`)
    runner.py common.py updates.py devices.py storage.py flash.py usbgadget.py i2c.py pidevices.py
ratapyui                launcher script for the TUI (repo root)
example.py              minimal user example (kept working; it's a smoke test)

Transport lives on the Link, and each Arduino carries its own link (serial or
I2C), so one Raspberry can drive both at once. `Link.request()` is the shared
build+NACK-check; `_exchange()` is transport-specific (serial reads a byte
stream; I2C does a write transaction then a separate read transaction).
```

## Environment & commands

- **arduino-cli** is a standalone binary (installed to `~/.local/bin`, no longer
  the VS Code extension). Use the wrapper `./firmware/acli.sh <args>` — it finds
  arduino-cli via `$ARDUINO_CLI`, then `PATH`, then `~/.local/bin`. Install it per
  [docs/INSTALL.md](docs/INSTALL.md).
- **Board**: an Arduino Mega 2560 clone (CH340) on **`/dev/ttyUSB0`**. User is in
  the `dialout` group. FQBN `arduino:avr:mega` (also `:uno`, `:nano`).
- **Python** uses **uv**: `uv add <pkg>`, `uv run python ...`, `uv run mypy`,
  `uv sync`. Never `pip install` — the user corrected this once. `uv.lock` is the
  source of truth; regenerate with `uv lock`. Managed Python only (a stray system
  beta breaks the hatchling build — `UV_PYTHON_PREFERENCE=only-managed` / pin the
  patch version). Main deps include `opencv-python`/`numpy` (for `Camera`). Pi-only
  libs (`picamera2` via apt, `rpi_ws281x` via `uv pip install`) are NOT in the lock
  — they don't build on this amd64 dev box (by design); `install.sh --pi` adds them
  on a real Pi.
- **End-user install** is `install.sh` (uv-based private env under
  `~/.local/share/rata`, `rata`/`ratapyui` launchers, `rata doctor`). Flags:
  `--pi`, `--usb-gadget`, `--check`, `--update`, `--pre-release`, `--uninstall`.
  `--check` exits **10** when an update is available (0 = up to date) so callers
  can branch on it. `rata check` / `rata update` and the TUI's *Find updates* page
  are thin fronts over it (`ratapyUI/ops/updates.py`) — keep the logic in the
  script, not duplicated in Python.
- Firmware libraries: **AccelStepper** (steppers), **DHTStable** (DHT),
  **Servo**, **OneWire** + **DallasTemperature** (DS18B20). None ship with the
  AVR core: `./firmware/acli.sh lib install AccelStepper DHTStable Servo OneWire
  DallasTemperature`. flash.sh pre-checks all five and names any that are missing.
- **Full dependency list / easy-setup commands live in
  [docs/INSTALL.md](docs/INSTALL.md)** — keep it current when deps change.

Typical loop:

```bash
# compile (check all three boards when touching firmware)
./firmware/acli.sh compile --fqbn arduino:avr:mega firmware/rata
./firmware/acli.sh compile --fqbn arduino:avr:uno  firmware/rata
./firmware/acli.sh compile --fqbn arduino:avr:nano firmware/rata

# flash with the helper (does a clean compile+upload; avoids the stale-cache trap)
./firmware/flash.sh --board mega                 # serial
./firmware/flash.sh --board uno --i2c 8          # I2C slave at address 8
./firmware/flash.sh --board uno --i2c 8 --compile-only   # build without a board

# type-check + run on hardware
uv run mypy
uv run python example.py

# firmware footprint (flash + SRAM per board, unicode bars)
./firmware/sizes.py            # add --i2c for the I2C build, --board uno for one
```

`firmware/flash.sh` wraps `firmware/acli.sh` (the raw arduino-cli). The `--i2c N`
address is a plain number; the script formats it into the `-DRATA_I2C_ADDRESS`
compile flag. Keep it in sync with the Python address (`Uno(N, link=...)`).

## Conventions (do not regress these)

1. **Strict typing.** `uv run mypy` (strict, config in `pyproject.toml`) must
   stay green. `ratapy/py.typed` marks the package typed. Use `TYPE_CHECKING`
   imports to break cycles; pyserial is untyped (`cast`/override handles it).
2. **No module-level globals for mutable state.** State lives on the class that
   owns it: the active board is `Raspberry.active_board` (+ `Raspberry.current()`),
   *not* a `board.py` global. Context-scoped state uses `contextvars.ContextVar`
   (see the ambient executor in `executor.py`) — never a plain global.
3. **Bind/unbind methods over per-call kwargs.** e.g. `device.set_executor(pe)` /
   `remove_executor()`, not an `executor=` argument threaded through every method.
4. **Beginner-friendly surface, complex internals OK.** Usage must read like
   `led.on()`. Boards are classes per model; the master is a class.
   **Imports come from submodules** (`from ratapy.boards import Mega`,
   `ratapy.devices` for ALL devices, `ratapy.link`, `ratapy.executor`);
   `__init__.py` stays slim -- only `Raspberry` and `RataError` at top level. Do
   not re-export the whole catalog from `__init__`. `devices` is a package split
   into `complex_devices` (need firmware) and `simple_devices` (helpers), but
   users import both from `ratapy.devices` -- keep new devices exported in
   `devices/__init__.py`.
   **`DigitalOutput` (DEV_DIGITAL_OUT, any pin) is NOT redundant with
   `DimmableLED`** (DEV_PWM, PWM pins only) -- keep both. `LED`/`Relay`/`Buzzer`
   are friendly components inheriting `DigitalOutput`. (`LED` was renamed to
   `DigitalOutput` as the primitive; `LED` now lives in components.)
5. **Keep the two protocol definitions in sync.** `ratapy/protocol.py` and
   `firmware/rata/Protocol.h` are hand-maintained twins. Change a byte code in
   one → change it in the other. Bump `PROTO_VERSION` (both files) on any
   incompatible change; `Arduino.verify()` warns on version mismatch.
   (A JSON-single-source generator was considered and explicitly declined — do
   not reintroduce it without asking.)
6. **Verify on real hardware.** This project controls physical pins; "it compiles"
   is not "it works". Flash and run against `/dev/ttyUSB0`, observe timing/output.
   Keep `example.py` runnable — it doubles as the smoke test.
7. **`ratapyUI` keeps ops dual-use.** Anything the control panel does lives in
   `ratapyUI/ops/<x>.py` with a `main(argv)` CLI *and* functions the TUI drives
   through a `CommandRunner` (whose sink is the log). Pages (`pages.py`) are thin
   glue over ops — no logic there. `ratapyUI` is in the strict-mypy gate too
   (`files = ["ratapy", "ratapyUI"]`); curses windows type as `curses.window`
   under `TYPE_CHECKING`. Can't run curses headless here — smoke-test it in a pty
   (a `pyte` screen render is the quickest visual check).

## Firmware architecture rules

- **`write()` must never block.** Long-running actions store a goal in `write()`
  and do the work in `update()`, which `loop()` calls every pass via
  `DeviceManager::updateAll()`. That's what makes devices non-blocking/concurrent.
  Report progress via `read()` (1=busy/moving, 0=idle) so `wait()`/`is_busy()`
  work. **This applies to time-structured convenience methods too** — `blink`
  (DigitalOutput), `fade`/`pulse`/`blink` (PWM), `beep` (Buzzer) are firmware
  patterns run in `update()`, NOT Python `time.sleep` loops. That's what lets
  `led1.blink(); led2.blink()` overlap and lets `blink` compose inside a
  `ParallelExecutor` (one staged "start" write per device). Never reintroduce
  Python-side timing loops for device actions. (Async was rejected: it can't
  stage into a COMMIT and would force `await` through the beginner API.)
- **Adding a device type touches exactly two sides, minimally:**
  - Firmware: new `Device` subclass in `Devices.h` (set `type()`, `begin()`,
    `write()`, optionally `read()`/`update()`; for a **multi-value sensor**
    override `readInto(out)->count` instead of `read()`), one `case` in
    `DeviceManager::create()`, and a `DEV_*` code in `Protocol.h`.
  - Python: matching `DEV_*` in `protocol.py`, a `Device` subclass in
    `devices/complex_devices.py` (set `DEVICE_TYPE`, `_params()`, `_pins()`,
    friendly methods), then export it in `devices/__init__.py`. A pure-Python
    convenience (no firmware) instead goes in `devices/simple_devices.py`.
    Nothing in the transport/parser/framing changes.
- **A device that runs on the Pi itself** (heavy: camera, LED strip, OLED) is a
  different animal: subclass `LocalDevice` in `devices/local/`, take `board:
  Raspberry`, drive the hardware with a Python library imported at MODULE TOP
  (no try/except), open the hardware lazily (first use, not `__init__`), override
  `_release()` for teardown. Add the name to `_LOCAL_EXPORTS` + `__all__` in
  `devices/__init__.py` AND to `_LAZY`/`__all__` in `devices/local/__init__.py`
  (resolved via `__getattr__` so the package still imports off-Pi). Put a
  pip-installable Pi lib in the optional `pi` group, and add any un-stubbed/absent
  lib to the `ignore_missing_imports` mypy override in `pyproject.toml`. No
  firmware, `DEV_*`, `Link` or protocol frame.
- **Backporting an Arduino device to the Pi's GPIO** (the `Pi*` twins in
  `local/outputs.py`|`inputs.py`|`servos.py`): (1) add/keep an `Abstract*` contract
  in `abstract_devices.py` and make BOTH the Arduino class and the `Pi*` class
  inherit it (abstract base LAST); (2) implement the `Pi*` as a `LocalDevice` over
  gpiozero -- SEPARATE code, no logic shared with the Arduino side (that's the
  point of the contract). Let gpiozero own any background work (blink/pulse/`source`)
  and track completion via `_mark_busy()` for is_busy()/wait(); don't hand-roll
  threads (and BackgroundTasks is the USER's tool, never a device's internal). A
  parity test in `tests/test_abstract_parity.py` enforces both sides match --
  extend the `PAIRS` list. Analog devices have NO Pi twin (no ADC on the Pi).
- **Per-board limits** live in `BoardConfig.h`, selected by MCU macro at compile
  time (`__AVR_ATmega2560__` vs `__AVR_ATmega328P__`). Pin counts come from the
  core's `NUM_DIGITAL_PINS`. No runtime board detection.

## Gotchas learned the hard way

- **Bootloader race after flashing.** Uploading resets the Mega; a script that
  opens the port immediately can beat the bootloader and get
  `timeout waiting for response` on the first ping. Wait ~1–2 s and retry.
- **Stale build cache on `upload`.** A bare `acli upload` flashes the last
  *compiled* artifact, which may be a different build than you think — e.g. an
  I2C variant compiled with `--build-property`, or another board. Symptom: board
  goes silent on serial after "successful" upload (an I2C build never calls
  `Serial.begin`). Fix: always `compile --clean --upload` when build properties
  or FQBNs have changed, so the thing compiled is the thing flashed.
- **AccelStepper speed ordering.** For constant-speed moves the call order must be
  `setMaxSpeed()` → `move()` → `setSpeed()`. `move()` recomputes the speed for its
  acceleration profile and silently overrides an earlier `setSpeed()`, making the
  motor crawl. This bit us; it's commented in `StepperDevice::write()`.
- **Docstrings/docs drift.** When you change the API, update `README.md`,
  `EXPLANATION.md`, and the `ratapy/__init__.py` module docstring too.

## Wire protocol quick reference

Frame: `START(0xAA) | CMD | LEN | PAYLOAD[LEN] | XOR-checksum(of CMD,LEN,payload)`.
`PROTO_VERSION = 5`. (Bump it on new WRITE sub-encodings too — old firmware
misreads them; `verify()` warns. v4→v5 added servo sweep + stepper stop/run.)

- Commands: `PING 0x01`, `RESET 0x02`, `ADD_DEVICE 0x10`, `WRITE 0x20`,
  `READ 0x21`, `STAGE 0x22` (buffer a write), `COMMIT 0x23` (apply all staged),
  `DEVICE_INFO 0x24 [index]` (introspect a registered device -> `RSP_DEVICE`),
  `SAVE 0x25` (persist the registry to EEPROM; the board reloads it on boot).
- Responses: `ACK 0x01`, `NACK 0x02 [err]`, `PONG 0x03 [ver, count, maxDevices,
  numDigitalPins]`, `VALUE 0x04 [id, hi, lo]`, `DEVICE 0x05 [index, id, type,
  nparams, params...]` (the base `Device` remembers its params for this).
- **Persistence:** `Arduino.save_devices()` -> `CMD_SAVE` writes `['R','A',fmt,
  count,{id,type,nparams,params}...]` to EEPROM (EEPROM.update, wear-friendly);
  `setup()` calls `DeviceManager::load()` to re-create them. Restores wiring/
  config, not runtime state. Clear it by `reset()` then `save_devices()`.
- Device types: `DEV_DIGITAL_OUT 0x01` (LED), `DEV_STEPPER 0x05`.
- Staging (`STAGE`/`COMMIT`) is how `ParallelExecutor` starts several devices in
  one firmware pass — microseconds apart instead of milliseconds.

## Transports (serial + I2C)

- Serial: request = write frame, read reply from the byte stream. One board per
  cable; `address` is a label.
- I2C: `I2CLink` (smbus2) shares one bus; `address` is the 7-bit slave addr. A
  request is a write transaction (command) then, after a small settle, a read
  transaction (reply). Firmware side: `WireTransport` buffers the reply in
  `sendFrame()` and writes it in the `onRequest` ISR; `onReceive` just buffers
  incoming bytes, and `loop()` parses/handles them so device access stays
  single-threaded with `updateAll()`. I2C frames must fit the AVR 32-byte Wire
  buffer — keep payloads small.
- **I2C is hardware-tested** as of 2026-07-15: a Pi driving one Mega (flashed
  `--i2c 8`, powered separately, through a bi-directional level shifter) ran
  `LED.blink()` end to end. The `I2CLink` settle delay needed no tuning. Still
  unverified: two boards at different addresses, and mixed serial+I2C on one
  Raspberry.
- **DS18B20 is hardware-tested** as of 2026-07-18: a Mega read a real sensor on
  pin 34 (with the required 4.7k data->VCC pull-up) -- 23.75 C, updating live.
  Confirmed the background-conversion design: the first ~750 ms conversion
  raises "no reading yet", then reads return instantly and stay current. RATA
  drives only the FIRST sensor on the pin; multi-drop on one bus is unbuilt.
  Diagnostic: `firmware/ds18b20_probe/` scans every pin with the raw
  DallasTemperature lib -- 0 devices there means wiring (usually the pull-up),
  not RATA.
