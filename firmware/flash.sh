#!/usr/bin/env bash
# Flash the RATA firmware to an Arduino -- the easy way.
#
# Serial (default transport):
#   ./firmware/flash.sh --board mega
#   ./firmware/flash.sh --board nano --port /dev/ttyUSB1
#
# I2C slave (give it a plain address number; the script bakes it in for you):
#   ./firmware/flash.sh --board uno --i2c 8
#   ./firmware/flash.sh --board uno --i2c 0x08      # hex works too
#
# The --i2c number is a normal integer -- no bytes, no hex required. It must
# match the address you use in Python:
#   Uno(8, link=I2CLink(bus=1))
#
# The RATA firmware auto-tunes to any AVR chip (see BoardConfig.h), so any board
# in the arduino:avr core works. The names below are shortcuts for the common
# ones; for anything else (Pro Mini, Mega ADK, a clone, ...) pass its full FQBN:
#   ./firmware/flash.sh --fqbn arduino:avr:pro:cpu=8MHzatmega328 --port /dev/ttyUSB0
#
# Options:
#   --board mega|uno|nano|leonardo|micro   which Arduino (or use --fqbn)
#   --fqbn FQBN             flash any AVR board by its arduino-cli FQBN (overrides --board)
#   --port PATH             serial port (default /dev/ttyUSB0)
#   --i2c N                 make it an I2C slave at address N (0x08..0x77); omit for serial
#   --compile-only          build but do not upload (no board needed)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACLI="$HERE/acli.sh"
SKETCH="$HERE/rata"

board=""
port="/dev/ttyUSB0"
i2c=""
compile_only=0
fqbn=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --board) board="$2"; shift 2;;
    --fqbn)  fqbn="$2";  shift 2;;
    --port)  port="$2";  shift 2;;
    --i2c)   i2c="$2";   shift 2;;
    --compile-only) compile_only=1; shift;;
    -h|--help) grep '^#' "$0" | sed 's/^# \?//;s/^!.*//'; exit 0;;
    *) echo "error: unknown argument '$1' (try --help)" >&2; exit 1;;
  esac
done

# An explicit --fqbn wins (any AVR board, no code change); otherwise map a name.
if [[ -z "$fqbn" ]]; then
  case "$board" in
    mega)     fqbn="arduino:avr:mega";;
    uno)      fqbn="arduino:avr:uno";;
    nano)     fqbn="arduino:avr:nano";;
    leonardo) fqbn="arduino:avr:leonardo";;
    micro)    fqbn="arduino:avr:micro";;
    "")   echo "error: --board is required (mega|uno|nano|leonardo|micro), or pass --fqbn <fqbn>" >&2; exit 1;;
    *)    echo "error: unknown board '$board'; use mega|uno|nano|leonardo|micro, or --fqbn <fqbn>" >&2; exit 1;;
  esac
fi
board="${board:-$fqbn}"                  # a label for the messages below

# The sketch's external libraries (see Devices.h). None of these come with the
# arduino:avr core -- install.sh adds them, but a hand-rolled arduino-cli setup
# easily misses one, and the only symptom is a C++ "No such file or directory"
# 200 lines into the build. Name the real problem instead.
missing=()
for lib in AccelStepper DHTStable Servo; do
  "$ACLI" lib list "$lib" 2>/dev/null | grep -q "^$lib " || missing+=("$lib")
done
if (( ${#missing[@]} )); then
  echo "error: the firmware needs Arduino libraries you don't have: ${missing[*]}" >&2
  echo "  install them:  arduino-cli lib install ${missing[*]}" >&2
  exit 1
fi

# Always a clean build so we never flash a stale cached artifact (e.g. an I2C
# build left over from a previous run, which would be silent on serial).
args=(compile --clean)
if [[ "$compile_only" -eq 0 ]]; then
  args+=(--upload -p "$port")
fi
args+=(--fqbn "$fqbn")

if [[ -n "$i2c" ]]; then
  # Accept a plain number: decimal (8) or hex (0x08). Convert + range-check here
  # so the user never touches the -D compile flag or byte formatting.
  if [[ ! "$i2c" =~ ^(0[xX][0-9a-fA-F]+|[0-9]+)$ ]]; then
    echo "error: --i2c must be a number like 8 or 0x08 (got '$i2c')" >&2; exit 1
  fi
  addr=$(( i2c ))
  if (( addr < 8 || addr > 119 )); then
    echo "error: I2C address $addr out of range 8..119 (0x08..0x77)" >&2; exit 1
  fi
  hex=$(printf '0x%02X' "$addr")
  echo ">> $board as I2C slave at address $addr ($hex)  [$fqbn]"
  # The copy-paste Python hint only makes sense for boards that have a class.
  case "$board" in
    mega|uno|nano|leonardo|micro) echo "   Python:  ${board^}($addr, link=I2CLink(bus=1))";;
  esac
  # compiler.cpp.extra_flags, NOT build.extra_flags: the latter carries
  # {build.usb_flags} on the USB boards (leonardo/micro), so overriding it drops
  # USB_VID/USB_PID and the core fails to build. compiler.cpp.extra_flags is
  # empty by default and sits in the same recipe -- it's meant for exactly this.
  args+=(--build-property "compiler.cpp.extra_flags=-DRATA_I2C_ADDRESS=$hex")
else
  echo ">> $board on serial ($port)  [$fqbn]"
fi

args+=("$SKETCH")
exec "$ACLI" "${args[@]}"
