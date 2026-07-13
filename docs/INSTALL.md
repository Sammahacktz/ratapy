# Installing RATA

RATA has two halves — the Python master library and the Arduino firmware — plus a
few tools and, for master-attached devices, some Raspberry-Pi-only libraries. On
Debian/Ubuntu/Raspberry Pi OS the **one-command installer** does everything; this
page also documents the pieces for a manual / developer setup.

- [1. One-command install](#1-one-command-install)
- [2. The dev/master machine (uv, from a checkout)](#2-the-devmaster-machine-uv-from-a-checkout)
- [3. Flashing firmware (arduino-cli)](#3-flashing-firmware-arduino-cli)
- [4. Master-attached devices (Raspberry Pi only)](#4-master-attached-devices-raspberry-pi-only)
- [5. USB gamepad / storage (Raspberry Pi gadget)](#5-usb-gamepad--storage-raspberry-pi-gadget)
- [6. Dependency reference table](#6-dependency-reference-table)

---

## 1. One-command install

On Debian, Ubuntu or Raspberry Pi OS, [`install.sh`](../install.sh) sets up
everything — a **private Python runtime + virtualenv** (via [uv](https://docs.astral.sh/uv/),
kept under `~/.local/share/rata`, not in your working directory), the latest RATA
release, Arduino CLI + the AVR core/libraries, serial permissions, and the `rata`
/ `ratapyui` launcher commands. It finishes by running `rata doctor`.

On a **fresh machine** you don't need the repo — pipe the installer straight in
(only `curl` is required; it apt-installs `git` and the rest itself):

```bash
curl -fsSL https://raw.githubusercontent.com/Sammahacktz/ratapy/main/install.sh | bash
```

Pass flags after `-s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/Sammahacktz/ratapy/main/install.sh | bash -s -- --pi
```

That URL is **stable** — it always serves the current installer, which then
installs the newest **published release** (not the branch it came from). There is
deliberately no `.../latest/install.sh`: `raw.githubusercontent.com` only serves
branches, tags and commit SHAs, so such a URL 404s.

From a checkout it's the same script:

```bash
bash install.sh                     # RATA env + Arduino CLI + core/libs + serial perms
bash install.sh --pi                # + Raspberry Pi camera / NeoPixel
bash install.sh --pi --usb-gadget   # + USB HID gamepad / storage (dwc2 + libcomposite)
```

Which version you get:

| You want | Do this |
|---|---|
| the newest release (default) | nothing — it resolves the highest `vX.Y.Z` tag |
| a specific version | `RATA_REF=v1.2.3 bash install.sh` |
| the bleeding edge (`main`) | `bash install.sh --pre-release` |

Lifecycle: once installed, use the `rata` command — no path to remember:

```bash
rata check                  # is a newer released version available?
rata update                 # update to the latest release + re-sync dependencies
rata check --pre-release    # ... against master (bleeding edge) instead
rata uninstall              # remove the RATA env + launchers
rata uninstall --usb-gadget # ... and revert the Pi's USB gadget boot config
```

`rata check` is scriptable: exit **0** = up to date, **10** = an update is
available, anything else = the check failed. The control panel does the same from
its **Find updates** page (`ratapyui`).

These are a thin front for the installer, which stays the single source of truth
and keeps managing the install at `~/.local/share/rata`. You can always call it
directly — the copy in the clone is the current one:

```bash
bash ~/.local/share/rata/install.sh --update      # same as `rata update`
bash ~/.local/share/rata/install.sh --uninstall   # same as `rata uninstall`
```

`rata uninstall` removes `~/.local/share/rata` and the `rata` / `ratapyui`
launchers — including the environment it is itself running from, which is fine
(it exits cleanly). It deliberately leaves arduino-cli, the apt packages and your
`dialout` membership alone; remove those by hand if you want them gone.

Add `--pre-release` to install, `--check`, or `--update` to track the `master`
branch instead of the latest release tag.

uv brings its own Python (`uv python install 3.12`), so the machine does **not**
need Python 3.12 preinstalled. After installing, check everything with:

```bash
rata doctor
```

Then start writing code — this scaffolds a directory with its own venv, `ratapy`
already installed and a starter script:

```bash
rata start-project myapp
```

The installer's own environment (`~/.local/share/rata`) is **not** where your code
belongs: `rata update` re-syncs it and would drop anything you added. Your project
gets its own venv — see
[Use RATA from your own project](../README.md#b-use-rata-from-your-own-project)
for the manual equivalent (plain `venv`, uv, or Poetry).

---

## 2. The dev/master machine (uv, from a checkout)

To work on RATA from a git checkout (instead of the packaged install), use
[uv](https://docs.astral.sh/uv/) directly:

```bash
uv sync                 # create .venv + install deps (incl. dev tools) from uv.lock
uv run python example.py
uv run mypy             # strict type-check (ratapy + ratapyUI)
uv run pytest           # the test-suite
```

- **Python ≥ 3.12** — uv fetches it for you (`uv python install 3.12`); never `pip
  install` into a system Python.
- `uv sync` pulls the runtime dependencies from the lockfile:
  - `pyserial` — USB-serial transport.
  - `smbus2` — I2C transport.
  - `opencv-python` + `numpy` — image handling for the `Camera` device. These
    install on any platform, so they live in the main dependency set.
  - plus the `dev` group (mypy, pytest); the installer uses `--no-dev` to skip it.
- **Serial port access**: add yourself to the `dialout` group so `/dev/ttyUSB*`
  is usable without root: `sudo usermod -aG dialout "$USER"` (then log out/in).
  (`install.sh` does this for you.)

---

## 3. Flashing firmware (arduino-cli)

RATA drives the Arduino toolchain through **arduino-cli** directly — it is no
longer tied to the VS Code Arduino extension.

Install the standalone binary once (no root needed; goes in `~/.local/bin`, which
should be on your `PATH`):

```bash
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh \
    | BINDIR="$HOME/.local/bin" sh
```

Then add the AVR core and the three libraries the firmware uses:

```bash
arduino-cli core update-index
arduino-cli core install arduino:avr          # Uno / Nano / Mega toolchain
arduino-cli lib install AccelStepper DHTStable Servo
```

`Servo` is on that list because the AVR core does **not** bundle it (it ships only
EEPROM, Wire, SPI, SoftwareSerial and HID). The Arduino IDE installs it alongside
the core, arduino-cli does not -- so skipping it gives you
`fatal error: Servo.h: No such file or directory` at compile time.

The repo scripts find arduino-cli automatically (`$ARDUINO_CLI`, then `PATH`,
then `~/.local/bin`) via [`firmware/acli.sh`](../firmware/acli.sh):

```bash
./firmware/acli.sh compile --fqbn arduino:avr:mega firmware/rata
./firmware/flash.sh --board mega              # clean compile + upload
./firmware/sizes.py                           # flash/SRAM footprint
```

To point at a different arduino-cli, export `ARDUINO_CLI=/path/to/arduino-cli`.

---

## 4. Master-attached devices (Raspberry Pi only)

Some devices are wired straight to the Pi and driven in Python there — see
[`ratapy/devices/local/`](../ratapy/devices/local/). Their backing libraries only
build/run on a Raspberry Pi, so they are **not** in the lockfile. Importing RATA
without them still works — only `Camera` / `NeoPixel` need them, and they are
loaded lazily. **`bash install.sh --pi` does all of the below**; the manual steps:

```bash
# system stack for the camera (libcamera has no working PyPI package):
sudo apt install -y python3-picamera2 python3-libcamera libcap-dev

# recreate the venv so it can see the apt-installed libcamera bindings:
uv venv --system-site-packages
uv sync --frozen

# NeoPixel driver, built on the Pi (no cross-platform wheel, so not in the lock):
uv pip install rpi_ws281x
```

Notes:

- **Camera** uses **Picamera2** (which needs **libcamera** from the system) plus
  **OpenCV** (already a main dependency). Enable the camera in
  `sudo raspi-config` → Interface Options if it is not already on. picamera2 comes
  from **apt** (`python3-picamera2`) rather than pip — the `--system-site-packages`
  venv is what lets the RATA environment see it.
- **NeoPixel** uses **rpi_ws281x**, which drives the strip over PWM/PCM/SPI DMA
  and therefore usually needs **root** — run those scripts with `sudo`, or use a
  method that grants GPIO/DMA access. Default data pin is GPIO18 (PWM0).

---

## 5. USB gamepad / storage (Raspberry Pi gadget)

RATA can make the **Raspberry Pi itself** appear to a host PC as a USB gamepad
(`Gamepad`) whose buttons/axes are fed from RATA input devices, and optionally as a
removable drive (`Storage`). See [`ratapy/devices/hid/`](../ratapy/devices/hid/).

This uses Linux **USB gadget mode** (`libcomposite` + ConfigFS), so it needs:

- A Pi with **USB-OTG**: a Pi Zero / Zero 2 W, or a Pi 4 / Pi 5 via its **USB-C**
  port. Connect *that* port to the host PC.
- A one-time boot-config change to enable the OTG driver + gadget framework, done
  by the setup script (then reboot):

  ```bash
  sudo ./scripts/setup-usb-gadget.sh     # edits config.txt/cmdline.txt, loads modules
  sudo reboot
  ```

  To go back to a normal Pi, revert it (removes exactly those two lines) and
  reboot — or use `bash install.sh --uninstall --usb-gadget`:

  ```bash
  sudo ./scripts/setup-usb-gadget.sh --undo
  sudo reboot
  ```

  Note you don't usually need to revert just to *stop* being a gamepad: the gadget
  only exists while a script holds it, so `rp.close()` (or the script ending) makes
  the Pi normal again immediately. Reverting is only for returning the OTG **port**
  itself to stock host behaviour.

- **root** to bring the gadget up (ConfigFS writes are privileged), so run gamepad
  scripts with `sudo`.
- **dosfstools** (`mkfs.vfat`) if you use `Storage` -- RATA formats the backing
  image with it: `sudo apt install -y dosfstools`.

Opt in when you create the master: `Raspberry(port=..., usb_device=True)`. Nothing
here is needed unless you use `Gamepad`/`Storage`.

**Runs anywhere, gracefully:** on a machine that can't be a gadget (your laptop, a
Pi without the setup, or without root) the HID devices fall back to a **logged
simulation** so scripts and the test-suite still run -- pass `usb_strict=True` to
turn that fallback into an error instead.

**Storage note:** the drive is a small FAT image RATA manages under `~/.rata/`, not
the Pi's live root filesystem -- a Linux mass-storage gadget always backs onto a
block image, so (unlike a CircuitPython board) the exposed drive is not your source
tree. `storage.hide()` removes it; `storage.show()` brings it back.

See [`example_gamepad_pi.py`](../example_gamepad_pi.py) for the full pattern.

---

## 6. Dependency reference table

Everything below is handled by `install.sh` (+ `--pi` / `--usb-gadget`); the
`Install` column shows the manual equivalent.

| Dependency | Kind | Needed for | Install |
|------------|------|-----------|---------|
| uv | tool | Python runtime + env manager | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python 3.12 | runtime | everything | `uv python install 3.12` (uv fetches it) |
| `pyserial` | pip (main) | serial transport | `uv sync` |
| `smbus2` | pip (main) | I2C transport | `uv sync` |
| `opencv-python`, `numpy` | pip (main) | `Camera` image handling | `uv sync` |
| arduino-cli | binary | compiling/flashing firmware | official install script → `~/.local/bin` |
| `arduino:avr` core | arduino-cli | Uno/Nano/Mega | `arduino-cli core install arduino:avr` |
| `AccelStepper` | arduino lib | `StepperWithDriver` | `arduino-cli lib install AccelStepper` |
| `DHTStable` | arduino lib | `DHT` sensor | `arduino-cli lib install DHTStable` |
| `Servo` | arduino lib | `Servo` device (not in the core!) | `arduino-cli lib install Servo` |
| `picamera2` (+ `python3-libcamera`) | apt (Pi) | `Camera` | `sudo apt install python3-picamera2 python3-libcamera` |
| `libcap-dev` | apt (Pi) | building the picamera2 stack | `sudo apt install libcap-dev` |
| `rpi_ws281x` | pip (Pi) | `NeoPixel` | `uv pip install rpi_ws281x` (on the Pi) |
| `dialout` group membership | OS | serial port access | `sudo usermod -aG dialout $USER` |
| `libcomposite` + dwc2 OTG | kernel (Pi) | `Gamepad` / `Storage` USB gadget | `sudo ./scripts/setup-usb-gadget.sh` + reboot |
| `dosfstools` (`mkfs.vfat`) | apt (Pi) | `Storage` drive image | `sudo apt install dosfstools` |
| root | OS | binding the USB gadget | run gamepad scripts with `sudo` |
