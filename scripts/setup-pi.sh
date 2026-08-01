#!/usr/bin/env bash
# Install the Raspberry-Pi-only device libraries into an existing RATA install --
# the camera (Picamera2 + libcamera), NeoPixel (rpi_ws281x) and audio
# (sounddevice + PortAudio) support. Run it any time AFTER the base install to add
# Pi hardware support, without re-running the whole installer.
#
#   rata pi                       # via the CLI (recommended)
#   bash scripts/setup-pi.sh      # directly
#
# What it installs:
#   apt  : python3-picamera2 python3-libcamera libcap-dev libportaudio2
#   venv : rpi_ws281x  sounddevice  lgpio   (into RATA's own .venv, via uv pip)
#
# lgpio is gpiozero's pin backend on Pi OS Bookworm -- gpiozero itself is a base
# RATA dependency (so the Pi GPIO devices import anywhere), but it needs a backend
# to actually drive real pins. Without lgpio the Pi GPIO devices raise
# gpiozero's BadPinFactory only when you construct one.
#
# apt needs root, so this uses sudo for that part; the venv installs run as you.
# Everything is idempotent -- re-running is safe. It does NOT enable the camera
# (do that in raspi-config) or write any I2S audio overlay (that boot-config edit
# is board-specific and manual -- see docs/INSTALL.md).
set -euo pipefail

case "${1:-}" in
  -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//;s/^!.*//'; exit 0 ;;
  "")        ;;
  *)         echo "error: unknown argument '$1' (try --help)" >&2; exit 1 ;;
esac

RATA_HOME="${RATA_HOME:-$HOME/.local/share/rata}"
if [[ ! -d "$RATA_HOME/.venv" ]]; then
  echo "error: no RATA install at $RATA_HOME (expected $RATA_HOME/.venv)." >&2
  echo "       run the base installer first, then this." >&2
  exit 1
fi

# Find uv (the base installer puts it in ~/.local/bin).
if command -v uv >/dev/null 2>&1; then UV="$(command -v uv)"
elif [[ -x "$HOME/.local/bin/uv" ]]; then UV="$HOME/.local/bin/uv"
else echo "error: uv not found (expected on PATH or ~/.local/bin)." >&2; exit 1; fi

# How to become root for the apt step. Prefer no-op (already root), then
# passwordless sudo, then an interactive sudo IF we have a terminal to prompt on.
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  SUDO=""
elif sudo -n true 2>/dev/null; then
  SUDO="sudo"
elif [[ -t 0 ]]; then
  SUDO="sudo"                       # a terminal is attached: sudo can prompt
else
  echo "error: the apt step needs root, but sudo would prompt and there is no" >&2
  echo "       terminal here. Run it yourself in a shell:  rata pi" >&2
  echo "       (or set up passwordless sudo)." >&2
  exit 1
fi

echo ">> installing Pi device libraries into $RATA_HOME"

echo ">> apt: picamera2, libcamera, libcap-dev, libportaudio2 (needs root)"
$SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3-picamera2 python3-libcamera libcap-dev libportaudio2

echo ">> venv: rpi_ws281x (NeoPixel), sounddevice (audio), lgpio (GPIO backend)"
cd "$RATA_HOME"
"$UV" pip install rpi_ws281x sounddevice lgpio

echo
echo ">> done. Added camera / NeoPixel / audio / GPIO (gpiozero) support."
if command -v libcamera-hello >/dev/null 2>&1 || command -v rpicam-hello >/dev/null 2>&1; then
  echo "   camera stack present (enable it in raspi-config if a camera doesn't work)"
else
  echo "   ! no libcamera tools found -- enable the camera in raspi-config"
fi
echo "   I2S mic/amp also need a device-tree overlay -- that part is manual,"
echo "   see docs/INSTALL.md. A USB mic/speaker needs nothing more."
