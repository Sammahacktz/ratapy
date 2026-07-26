#!/usr/bin/env bash
# Enable (or disable) USB gadget mode on a Raspberry Pi.
#
# RATA's `Gamepad` / `Storage` make the Pi present itself to a host PC as a USB
# HID gamepad (and optional drive). That needs the Pi's USB-OTG port in
# "peripheral" mode plus the libcomposite gadget framework -- a boot-config change
# (then a reboot).
#
#   sudo ./scripts/setup-usb-gadget.sh            # enable it
#   sudo ./scripts/setup-usb-gadget.sh --undo     # revert to a normal Pi
#   sudo reboot                                    # either way, reboot to apply
#
# Enabling is append-only and idempotent; --undo removes exactly the two lines
# this script adds (dtoverlay=dwc2 in config.txt, modules-load=dwc2,libcomposite
# in cmdline.txt) and tears down any live gadget. Nothing else is touched.
#
# Requirements: a Pi with USB-OTG on its USB port (Zero / Zero 2 W / Pi 4 / Pi 5
# via the USB-C port). Connect *that* port to the host PC.
set -euo pipefail

MODE="enable"
case "${1:-}" in
  "")                MODE="enable" ;;
  --undo|--disable)  MODE="disable" ;;
  -h|--help)         grep '^#' "$0" | sed 's/^# \{0,1\}//;s/^!.*//'; exit 0 ;;
  *)                 echo "error: unknown argument '$1' (try --help)" >&2; exit 1 ;;
esac

if [[ "${EUID}" -ne 0 ]]; then
  echo "error: run me as root (sudo $0 ${1:-})" >&2
  exit 1
fi

# Raspberry Pi OS Bookworm keeps the boot files under /boot/firmware; older
# images use /boot directly.
BOOT="/boot/firmware"
[[ -d "$BOOT" ]] || BOOT="/boot"
CONFIG="$BOOT/config.txt"
CMDLINE="$BOOT/cmdline.txt"

if [[ ! -f "$CONFIG" || ! -f "$CMDLINE" ]]; then
  echo "error: could not find $CONFIG / $CMDLINE -- is this a Raspberry Pi?" >&2
  exit 1
fi
echo ">> using boot files in $BOOT"

teardown_live_gadget() {
  # Best effort: unbind + remove a bound RATA gadget so the change takes effect
  # without waiting for the reboot (harmless if none is present).
  local g=/sys/kernel/config/usb_gadget/rata
  if [[ -d "$g" ]]; then
    echo "" > "$g/UDC" 2>/dev/null || true
    find "$g" -maxdepth 2 -name '*.usb0' -type l -exec rm -f {} + 2>/dev/null || true
  fi
}

enable_gadget() {
  # 1. Load the dwc2 USB-OTG driver via a device-tree overlay.
  if grep -q '^dtoverlay=dwc2$' "$CONFIG"; then
    echo "   config.txt already has dtoverlay=dwc2"
  else
    echo 'dtoverlay=dwc2' >> "$CONFIG"
    echo "   added dtoverlay=dwc2 to config.txt"
  fi

  # 2. Load dwc2 + libcomposite early at boot (cmdline.txt is a single line).
  if grep -q 'modules-load=dwc2' "$CMDLINE"; then
    echo "   cmdline.txt already loads dwc2"
  else
    sed -i '1 s/$/ modules-load=dwc2,libcomposite/' "$CMDLINE"
    echo "   added modules-load=dwc2,libcomposite to cmdline.txt"
  fi

  # 3. Make them available now too (best effort; the reboot is what really matters).
  modprobe libcomposite 2>/dev/null || true

  # 4. dosfstools provides mkfs.vfat, used to format the Storage backing image.
  if ! command -v mkfs.vfat >/dev/null 2>&1; then
    echo "   note: mkfs.vfat not found -- 'sudo apt install dosfstools' for USB storage"
  fi

  echo
  echo ">> enabled. Reboot to finish:  sudo reboot"
  echo "   then connect the Pi's USB-OTG port to the host and run your Gamepad script as root."
}

disable_gadget() {
  teardown_live_gadget

  # Remove exactly the two lines enable adds; leave everything else intact.
  if grep -q '^dtoverlay=dwc2$' "$CONFIG"; then
    sed -i '/^dtoverlay=dwc2$/d' "$CONFIG"
    echo "   removed dtoverlay=dwc2 from config.txt"
  else
    echo "   config.txt had no dtoverlay=dwc2"
  fi

  if grep -q 'modules-load=dwc2,libcomposite' "$CMDLINE"; then
    sed -i 's/ *modules-load=dwc2,libcomposite//' "$CMDLINE"
    echo "   removed modules-load=dwc2,libcomposite from cmdline.txt"
  else
    echo "   cmdline.txt had no modules-load=dwc2,libcomposite"
  fi

  echo
  echo ">> disabled. Reboot to return the USB port to normal:  sudo reboot"
}

if [[ "$MODE" == "enable" ]]; then
  enable_gadget
else
  disable_gadget
fi
