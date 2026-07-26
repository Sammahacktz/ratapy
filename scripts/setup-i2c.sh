#!/usr/bin/env bash
# Enable (or disable) the I2C bus on a Raspberry Pi.
#
# RATA drives Arduinos over I2C with `I2CLink(bus=1)`, which needs /dev/i2c-1 --
# the Pi's ARM I2C controller, which ships disabled. Turning it on is a boot-config
# change (then a reboot), plus the i2c-dev module and group membership so the bus is
# usable without root.
#
#   sudo ./scripts/setup-i2c.sh            # enable it
#   sudo ./scripts/setup-i2c.sh --undo     # turn it back off
#   sudo reboot                            # either way, reboot to apply
#
# Enabling is idempotent; --undo removes exactly what this script adds
# (dtparam=i2c_arm=on in config.txt, i2c-dev in /etc/modules). It deliberately
# leaves your i2c group membership and the i2c-tools package alone.
#
# Wiring: Pi SDA = GPIO2 (pin 3), SCL = GPIO3 (pin 5), plus a COMMON GROUND.
# The Pi's GPIO is 3.3V and NOT 5V-tolerant: use a bi-directional level shifter
# for a 5V Arduino (Uno/Nano/Mega), or a 3.3V board. After a reboot, check the
# board answers with:  i2cdetect -y 1
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
MODULES="/etc/modules"

if [[ ! -f "$CONFIG" ]]; then
  echo "error: could not find $CONFIG -- is this a Raspberry Pi?" >&2
  exit 1
fi
echo ">> using boot config $CONFIG"

enable_i2c() {
  # 1. Turn on the ARM I2C controller (this is what creates /dev/i2c-1).
  if grep -qE '^dtparam=i2c_arm=on$' "$CONFIG"; then
    echo "   config.txt already has dtparam=i2c_arm=on"
  elif grep -qE '^#?dtparam=i2c_arm=' "$CONFIG"; then
    # Replace a commented-out or =off line rather than appending a duplicate.
    sed -i 's/^#\?dtparam=i2c_arm=.*$/dtparam=i2c_arm=on/' "$CONFIG"
    echo "   set dtparam=i2c_arm=on in config.txt"
  else
    echo 'dtparam=i2c_arm=on' >> "$CONFIG"
    echo "   added dtparam=i2c_arm=on to config.txt"
  fi

  # 2. Load i2c-dev at boot -- the module that exposes the bus as /dev/i2c-*.
  if grep -qE '^i2c-dev$' "$MODULES" 2>/dev/null; then
    echo "   /etc/modules already loads i2c-dev"
  else
    echo 'i2c-dev' >> "$MODULES"
    echo "   added i2c-dev to /etc/modules"
  fi
  modprobe i2c-dev 2>/dev/null && echo "   loaded i2c-dev now" || true

  # 3. i2cdetect etc. -- the first thing to reach for when a board stays silent.
  if command -v i2cdetect >/dev/null; then
    echo "   i2c-tools already installed"
  else
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq i2c-tools >/dev/null 2>&1 \
      && echo "   installed i2c-tools" \
      || echo "   ! could not install i2c-tools (apt-get install -y i2c-tools)"
  fi

  # 4. Let the invoking user open /dev/i2c-* without sudo (mirrors dialout).
  local who="${SUDO_USER:-${USER:-}}"
  if [[ -z "$who" || "$who" == "root" ]]; then
    echo "   (no non-root user to add to the i2c group -- skipping)"
  elif ! getent group i2c >/dev/null; then
    echo "   (no i2c group on this system -- skipping)"
  elif id -nG "$who" | tr ' ' '\n' | grep -qx i2c; then
    echo "   $who is already in the i2c group"
  else
    usermod -aG i2c "$who"
    echo "   added $who to the i2c group (log out/in for it to take effect)"
  fi

  echo
  echo ">> enabled. Reboot to bring up the bus:  sudo reboot"
  echo "   then:  i2cdetect -y 1     # your board should show at its --i2c address"
}

disable_i2c() {
  # Remove exactly what enable adds; group membership and i2c-tools stay.
  if grep -qE '^dtparam=i2c_arm=on$' "$CONFIG"; then
    sed -i '/^dtparam=i2c_arm=on$/d' "$CONFIG"
    echo "   removed dtparam=i2c_arm=on from config.txt"
  else
    echo "   config.txt had no dtparam=i2c_arm=on"
  fi

  if grep -qE '^i2c-dev$' "$MODULES" 2>/dev/null; then
    sed -i '/^i2c-dev$/d' "$MODULES"
    echo "   removed i2c-dev from /etc/modules"
  else
    echo "   /etc/modules had no i2c-dev"
  fi

  echo
  echo ">> disabled. Reboot to release the bus:  sudo reboot"
  echo "   (i2c-tools and your i2c group membership were left alone)"
}

if [[ "$MODE" == "enable" ]]; then
  enable_i2c
else
  disable_i2c
fi
