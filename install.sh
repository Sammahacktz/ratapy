#!/usr/bin/env bash
# RATA one-shot installer for Debian / Ubuntu / Raspberry Pi OS.
#
#   bash install.sh                     # RATA env + Arduino CLI + core/libs + serial perms
#   bash install.sh --pi                # + Raspberry Pi camera / NeoPixel support
#   bash install.sh --pi --usb-gadget   # + USB HID gamepad / storage (dwc2 + libcomposite)
#   bash install.sh --i2c               # + enable the Pi I2C bus (Arduinos over 2 wires)
#
#   bash install.sh --check             # is a newer released version available?
#   bash install.sh --update            # update to the latest release + re-sync deps
#   bash install.sh --pre-release       # add to install/--check/--update to track
#                                       #   master (bleeding edge) instead of a tag
#   bash install.sh --uninstall         # remove the RATA env + launchers
#   bash install.sh --uninstall --usb-gadget   # ...and revert the USB gadget boot config
#   bash install.sh --uninstall --i2c          # ...and turn the I2C bus back off
#   bash install.sh --help
#
# On a fresh machine, bootstrap straight from the default branch -- this URL is
# stable and never needs bumping for a new release (there is no "latest" ref on
# raw.githubusercontent.com; it only serves branches/tags/SHAs):
#
#   curl -fsSL https://raw.githubusercontent.com/Sammahacktz/ratapy/main/install.sh | bash
#   curl -fsSL .../main/install.sh | bash -s -- --pi        # pass flags like this
#
# It then installs the newest *published release* (not the branch it came from).
# Pin a specific version with RATA_REF=v1.2.3, or track the branch with
# --pre-release.
#
# Everything lands OUTSIDE your working directory: a private Python runtime and
# virtualenv under ~/.local/share/rata, launcher commands (`rata`, `ratapyui`) in
# ~/.local/bin. Nothing is pip-installed into a system Python. Finishes by running
# `rata doctor`.
set -euo pipefail

# --- pinned versions + locations (override via env) -------------------------
# Empty = install the latest published release, resolved from the repo's tags at
# run time (see latest_release). Set it to pin a specific tag/branch instead.
RATA_REF="${RATA_REF:-}"
RATA_REPO="${RATA_REPO:-https://github.com/Sammahacktz/ratapy.git}"   # remote git URL
# This script is served from the default branch, so the URL never needs bumping.
RAW_URL="https://raw.githubusercontent.com/Sammahacktz/ratapy/main/install.sh"
# The private env always gets 3.12, regardless of what the system ships. (RATA
# itself supports >=3.11 -- see requires-python -- so a user's own project can use
# Bookworm's system Python; this pin is only for the installer's own venv.)
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
ARDUINO_CLI_VERSION="${ARDUINO_CLI_VERSION:-1.5.1}"
AVR_CORE_VERSION="${AVR_CORE_VERSION:-1.8.6}"
ACCELSTEPPER_VERSION="${ACCELSTEPPER_VERSION:-1.64.0}"
DHTSTABLE_VERSION="${DHTSTABLE_VERSION:-1.1.0}"
# Servo is NOT part of the arduino:avr core (that only bundles EEPROM/Wire/SPI/
# SoftwareSerial/HID) -- the IDE ships it separately, arduino-cli does not.
SERVO_VERSION="${SERVO_VERSION:-1.3.0}"

RATA_HOME="${RATA_HOME:-$HOME/.local/share/rata}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
ACLI="$BIN_DIR/arduino-cli"

# The PATH the *caller's* shell has, captured before install_uv prepends BIN_DIR
# to ours -- otherwise the "not on your PATH" check below could never fire.
ORIG_PATH="$PATH"

# Path to this script, and the directory holding it. Both are empty when we are
# piped (curl ... | bash): there is no script file, so BASH_SOURCE is unset --
# and `set -u` would abort on a bare ${BASH_SOURCE[0]}.
SELF="${BASH_SOURCE[0]:-}"
SRC_DIR=""
[[ -n "$SELF" ]] && SRC_DIR="$(cd "$(dirname "$SELF")" && pwd)"

# uv must never pick a system beta/unstable Python for the build; managed only.
export UV_PYTHON_PREFERENCE=only-managed

# Boot-config changes (I2C, USB gadget) only take effect after a reboot. Record
# WHICH ones asked for it, so the closing message names them instead of guessing.
NEEDS_REBOOT=0
REBOOT_WHY=""
note_reboot() { NEEDS_REBOOT=1; REBOOT_WHY="${REBOOT_WHY:+$REBOOT_WHY + }$1"; }

# No terminal to type into (e.g. run from the TUI)? Fail fast instead of hanging
# on git's username/password prompt for a private HTTPS clone -- use SSH there.
[[ -t 0 ]] || export GIT_TERMINAL_PROMPT=0

# --- pretty logging ---------------------------------------------------------
if [[ -t 1 ]]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; D=$'\033[90m'; X=$'\033[0m'
else B=""; G=""; Y=""; R=""; D=""; X=""; fi
step() { echo; echo "${B}▶ $*${X}"; }
info() { echo "  $*"; }
ok()   { echo "  ${G}✓${X} $*"; }
warn() { echo "  ${Y}!${X} $*" >&2; }
die()  { echo "${R}✗ $*${X}" >&2; exit 1; }

SUDO=""
need_sudo() { if [[ $EUID -ne 0 ]]; then command -v sudo >/dev/null || die "need root or sudo"; SUDO="sudo"; fi; }

# --- steps ------------------------------------------------------------------

detect_os() {
    step "Detecting system"
    [[ -r /etc/os-release ]] || die "no /etc/os-release -- unsupported system"
    # shellcheck disable=SC1091
    . /etc/os-release
    local arch; arch="$(uname -m)"
    info "OS:   ${PRETTY_NAME:-$ID} ($ID)"
    info "Arch: $arch"
    case "$ID ${ID_LIKE:-}" in
        *debian*|*ubuntu*|*raspbian*) ok "Debian-family system supported" ;;
        *) warn "not Debian/Ubuntu/Raspberry Pi OS -- apt steps may not apply, continuing" ;;
    esac
    # if/else, not `[[ ]] && IS_PI=1`: as the last command that would return 1 on a
    # non-Pi, making detect_os return 1 and trip `set -e` at the call site.
    if [[ "$ID" == "raspbian" || -e /proc/device-tree/model ]]; then IS_PI=1; else IS_PI=0; fi
}

apt_install() {
    step "Installing system packages (apt)"
    need_sudo
    $SUDO apt-get update -qq
    $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        git curl ca-certificates build-essential
    ok "base packages present (git, curl, build-essential)"
}

install_uv() {
    step "Installing uv (Python runtime manager)"
    if command -v uv >/dev/null 2>&1; then
        ok "uv already present ($(uv --version))"
    else
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # the installer drops uv into ~/.local/bin
        export PATH="$HOME/.local/bin:$PATH"
        command -v uv >/dev/null || die "uv install failed"
        ok "installed $(uv --version)"
    fi
}

fetch_rata() {
    step "Fetching RATA into $RATA_HOME"
    if [[ -d "$RATA_HOME/.git" ]]; then
        ok "already cloned -- use --update to change version"
        return
    fi
    mkdir -p "$(dirname "$RATA_HOME")"
    local origin
    if [[ -n "$RATA_REPO" ]]; then
        origin="$RATA_REPO"
    elif [[ -d "$SRC_DIR/.git" ]]; then
        origin="$SRC_DIR"                    # install from this local checkout
        warn "no RATA_REPO set -- cloning from the local checkout ($SRC_DIR)"
    else
        die "no git repo to install from -- set RATA_REPO=<url>"
    fi
    git clone --quiet "$origin" "$RATA_HOME" \
        || die "clone failed -- private repo? clone over SSH (see 'bash install.sh --help')"
    if [[ "$WITH_PRE" == 1 ]]; then
        # Pre-release: stay on the freshly-cloned default branch (bleeding edge).
        ok "on $(git -C "$RATA_HOME" rev-parse --abbrev-ref HEAD) (pre-release)"
        return
    fi
    # RATA_REF pins a version; unset means "whatever the newest release is", so a
    # new release needs no change here (same rule --check/--update follow).
    local ref="${RATA_REF:-$(latest_release)}"
    if [[ -z "$ref" ]]; then
        warn "no release tags published yet -- staying on the default branch"
        return
    fi
    git -C "$RATA_HOME" checkout --quiet "$ref" 2>/dev/null \
        || warn "ref '$ref' not found -- staying on the default branch"
    ok "cloned $(git -C "$RATA_HOME" describe --tags --always 2>/dev/null || echo "$ref")"
}

setup_python_env() {
    local venv_args=()
    if [[ "$WITH_PI" == 1 ]]; then
        # --pi must build on the SYSTEM python3. apt installs picamera2 into
        # /usr/lib/python3/dist-packages, which belongs to that interpreter; uv's
        # managed Python is a standalone build whose site-packages has nothing from
        # apt, so --system-site-packages there exposes nothing. RATA supports
        # >=3.11 (see requires-python), which is what Bookworm ships.
        # /usr/bin/python3 by absolute path, NOT `command -v python3`: dist-packages
        # belongs to the DISTRO interpreter, and a python3 earlier on PATH
        # (/usr/local/bin, pyenv, conda) owns none of it. Pre-releases are rejected
        # too -- their bundled packaging raises InvalidVersion('0.dev0'), which
        # breaks every pip install made inside the venv.
        local sys_py=/usr/bin/python3
        [[ -x "$sys_py" ]] || die "--pi needs $sys_py (sudo apt install python3)"
        "$sys_py" -c 'import sys; v = sys.version_info
raise SystemExit(0 if v >= (3, 11) and v.releaselevel == "final" else 1)' \
            || die "--pi needs a final $sys_py >= 3.11 (found $("$sys_py" --version 2>&1))"
        step "Building the private Python environment (system $("$sys_py" --version 2>&1 | cut -d" " -f2))"
        venv_args=(--python "$sys_py" --system-site-packages)
    else
        step "Building the private Python environment ($PYTHON_VERSION)"
        uv python install "$PYTHON_VERSION"
        venv_args=(--python "$PYTHON_VERSION")
    fi
    cd "$RATA_HOME"
    uv venv "${venv_args[@]}"
    uv sync --frozen --no-dev
    ok "environment ready at $RATA_HOME/.venv"
}

install_arduino_cli() {
    step "Installing Arduino CLI (pinned $ARDUINO_CLI_VERSION)"
    if [[ -x "$ACLI" ]] && "$ACLI" version 2>/dev/null | grep -q "$ARDUINO_CLI_VERSION"; then
        ok "arduino-cli $ARDUINO_CLI_VERSION already installed"
    else
        curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh \
            | BINDIR="$BIN_DIR" sh -s "$ARDUINO_CLI_VERSION"
        ok "installed arduino-cli into $BIN_DIR"
    fi
}

install_arduino_deps() {
    step "Installing AVR core + Arduino libraries (pinned)"
    "$ACLI" core update-index >/dev/null
    "$ACLI" core install "arduino:avr@$AVR_CORE_VERSION"
    "$ACLI" lib install "AccelStepper@$ACCELSTEPPER_VERSION" "DHTStable@$DHTSTABLE_VERSION" \
                        "Servo@$SERVO_VERSION"
    ok "arduino:avr@$AVR_CORE_VERSION, AccelStepper, DHTStable, Servo"
}

add_dialout() {
    step "Serial port permissions"
    if id -nG "$USER" | tr ' ' '\n' | grep -qx dialout; then
        ok "$USER already in the dialout group"
    else
        need_sudo
        $SUDO usermod -aG dialout "$USER"
        ok "added $USER to dialout (log out/in for it to take effect)"
    fi
}

install_launchers() {
    step "Installing launcher commands in $BIN_DIR"
    mkdir -p "$BIN_DIR"
    # "<command>:<module>" -- run with `python -m` rather than a console script, so
    # the package ships none (see pyproject.toml): a `rata` script inside a user's
    # own project venv would shadow these and break.
    local entry name module
    for entry in "rata:ratapy.cli" "ratapyui:ratapyUI"; do
        name="${entry%%:*}"; module="${entry#*:}"
        cat > "$BIN_DIR/$name" <<EOF
#!/usr/bin/env bash
# RATA launcher (generated by install.sh) -> the private venv's interpreter.
exec "$RATA_HOME/.venv/bin/python" -m $module "\$@"
EOF
        chmod +x "$BIN_DIR/$name"
    done
    ok "commands: rata, ratapyui"
    # Whether they actually resolve is a PATH question -- reported once, at the end.
}

configure_pi() {
    step "Configuring Raspberry Pi devices (camera, NeoPixel)"
    need_sudo
    $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        python3-picamera2 python3-libcamera libcap-dev
    cd "$RATA_HOME"
    uv pip install rpi_ws281x          # built here; only compiles on the Pi
    ok "picamera2 + libcamera (apt) and rpi_ws281x (venv) installed"
    if command -v libcamera-hello >/dev/null 2>&1 || command -v rpicam-hello >/dev/null 2>&1; then
        ok "camera stack present -- enable it in raspi-config if not already"
    else
        warn "no libcamera tools found -- enable the camera in raspi-config"
    fi
}

configure_usb_gadget() {
    step "Configuring USB gadget mode (HID gamepad / storage)"
    need_sudo
    $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y -qq dosfstools
    $SUDO "$RATA_HOME/scripts/setup-usb-gadget.sh"
    note_reboot "USB gadget mode"
    ok "USB gadget boot config applied (dwc2 + libcomposite)"
}

configure_i2c() {
    step "Configuring the I2C bus (Arduinos over two wires)"
    need_sudo
    # The script does the lot: dtparam, i2c-dev, i2c-tools, the i2c group.
    $SUDO "$RATA_HOME/scripts/setup-i2c.sh"
    note_reboot "the I2C bus"
    ok "I2C boot config applied (dtparam=i2c_arm=on + i2c-dev)"
}

run_doctor() {
    step "Diagnostics (rata doctor)"
    "$RATA_HOME/.venv/bin/python" -m ratapy.cli doctor || true
}

# --- lifecycle: uninstall / check / update ----------------------------------

# The newest stable release tag known to the checkout (run `git fetch` first).
# Tags are version-sorted (v1.10.0 > v1.9.0); the first without a '-' is the
# highest published vX.Y.Z (pre-releases like v1.1.0-rc1 are skipped). Empty if
# there are no release tags.
latest_release() {
    local t
    while IFS= read -r t; do
        [[ "$t" == *-* ]] && continue
        echo "$t"; return
    done < <(git -C "$RATA_HOME" tag --list 'v[0-9]*' --sort=-v:refname)
}

# The release the checkout currently sits on (nearest tag reachable from HEAD),
# or empty for an untagged build.
current_release() {
    git -C "$RATA_HOME" describe --tags --abbrev=0 --match 'v[0-9]*' 2>/dev/null || true
}

# The remote's default branch -- the pre-release ("bleeding edge") track. Prefers
# what origin points HEAD at, else master, else main.
remote_default_branch() {
    local b
    b="$(git -C "$RATA_HOME" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
    [[ -n "$b" ]] && { echo "$b"; return; }
    for cand in master main; do
        git -C "$RATA_HOME" rev-parse --verify --quiet "origin/$cand" >/dev/null && { echo "$cand"; return; }
    done
}

do_uninstall() {
    step "Uninstalling RATA"
    # With --usb-gadget / --i2c, also revert those boot configs (before we remove
    # the scripts they live in).
    if [[ "$WITH_USB" == 1 && -x "$RATA_HOME/scripts/setup-usb-gadget.sh" ]]; then
        need_sudo
        $SUDO "$RATA_HOME/scripts/setup-usb-gadget.sh" --undo && note_reboot "USB gadget mode"
    fi
    if [[ "$WITH_I2C" == 1 && -x "$RATA_HOME/scripts/setup-i2c.sh" ]]; then
        need_sudo
        $SUDO "$RATA_HOME/scripts/setup-i2c.sh" --undo && note_reboot "the I2C bus"
    fi
    rm -rf "$RATA_HOME" && ok "removed $RATA_HOME"
    for name in rata ratapyui; do rm -f "$BIN_DIR/$name" && ok "removed $BIN_DIR/$name"; done
    info "Left in place (remove by hand if you want): arduino-cli, apt packages, dialout."
    [[ "$WITH_USB" != 1 ]] && info "USB-gadget boot config kept -- pass --usb-gadget to revert it too."
    [[ "$WITH_I2C" != 1 ]] && info "I2C boot config kept -- pass --i2c to revert it too."
    [[ "$NEEDS_REBOOT" == 1 ]] && warn "reboot to finish reverting $REBOOT_WHY:  sudo reboot"
    exit 0
}

# Refresh refs + tags from origin.
#
# --force matters: a release tag can be re-pointed upstream, and without it git
# refuses ("[rejected] v1.0.0 -> v1.0.0 (would clobber existing tag)") and fails
# the WHOLE fetch -- so a moved tag would break --check/--update for everyone
# holding the old one.
fetch_origin() {
    git -C "$RATA_HOME" fetch --quiet --tags --force origin \
        || die "could not fetch from $(git -C "$RATA_HOME" remote get-url origin 2>/dev/null || echo origin) -- network down, or no access to the remote?"
}

# The commit --check/--update targets: the latest release tag, or (--pre-release)
# the tip of the remote's default branch. Echoes "<ref>\t<commit>"; ref is empty
# if the track has nothing to offer (no release tags).
update_target() {
    if [[ "$WITH_PRE" == 1 ]]; then
        local branch; branch="$(remote_default_branch)"
        [[ -n "$branch" ]] || die "no default branch on origin to track"
        printf '%s\t%s\n' "$branch" "$(git -C "$RATA_HOME" rev-parse "origin/$branch")"
    else
        local tag; tag="$(latest_release)"
        [[ -n "$tag" ]] && printf '%s\t%s\n' "$tag" "$(git -C "$RATA_HOME" rev-parse "$tag")"
    fi
}

do_check() {
    step "Checking for updates$PRE_NOTE"
    [[ -d "$RATA_HOME/.git" ]] || die "RATA is not installed at $RATA_HOME"
    fetch_origin
    local ref target
    IFS=$'\t' read -r ref target < <(update_target)
    [[ -n "$ref" ]] || { warn "no releases published yet -- try --pre-release for master"; exit 0; }
    if [[ "$(git -C "$RATA_HOME" rev-parse HEAD)" == "$target" ]]; then
        ok "up to date (on $ref)"
        exit 0
    fi
    warn "an update is available: $ref -- run: bash install.sh --update$PRE_FLAG"
    exit 10                                        # 10 = update available (scriptable)
}

do_update() {
    [[ -d "$RATA_HOME/.git" ]] || die "RATA is not installed at $RATA_HOME"
    fetch_origin
    local ref target
    IFS=$'\t' read -r ref target < <(update_target)
    [[ -n "$ref" ]] || die "no releases published yet -- try --update --pre-release for master"
    # Only on the first pass: the hand-off below re-enters this function from the
    # new script, and announcing the same update twice reads like it ran twice.
    [[ -z "${RATA_UPDATE_HANDOFF:-}" ]] && step "Updating RATA to $ref$PRE_NOTE"
    git -C "$RATA_HOME" checkout --quiet "$ref"
    # On the branch track, fast-forward to the fetched tip; tags are immutable.
    [[ "$WITH_PRE" == 1 ]] && git -C "$RATA_HOME" merge --quiet --ff-only "$target"

    # Everything so far ran from the OLD install.sh -- the very file that checkout
    # just replaced. Hand the rest over to the NEW one: otherwise a change to the
    # steps below only takes effect on the update *after* the one that ships it
    # (Servo was added this way), and bash keeps reading a script that changed on
    # disk underneath it. The guard stops the new copy from handing off again.
    if [[ -z "${RATA_UPDATE_HANDOFF:-}" ]]; then
        export RATA_UPDATE_HANDOFF=1
        exec bash "$RATA_HOME/install.sh" --update${PRE_FLAG}
    fi

    cd "$RATA_HOME"
    uv sync --frozen --no-dev
    # The new revision may pin a different core or need a library the old one
    # didn't (Servo was added this way). Both are idempotent and offline-cheap
    # when nothing changed, so an update refreshes them just like the Python deps
    # -- otherwise the firmware silently fails to compile until a reinstall.
    install_arduino_deps
    ok "updated to $(git -C "$RATA_HOME" describe --tags --always)"
    run_doctor
    exit 0
}

# Prints the comment header above. Needs the script on disk, which a piped run
# (curl | bash) does not have -- point those at the downloadable copy instead.
usage() {
    if [[ -n "$SELF" ]]; then
        awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$SELF"
    else
        echo "RATA installer. --help needs the script on disk; download it first:"
        echo "  curl -fsSLO $RAW_URL"
        echo "  bash install.sh --help"
    fi
    exit 0
}

# --- argument parsing + main ------------------------------------------------
WITH_PI=0; WITH_USB=0; WITH_I2C=0; WITH_PRE=0; ACTION="install"
for arg in "$@"; do
    case "$arg" in
        --pi)          WITH_PI=1 ;;
        --usb-gadget)  WITH_USB=1 ;;
        --i2c)         WITH_I2C=1 ;;
        --pre-release) WITH_PRE=1 ;;
        --uninstall)   ACTION="uninstall" ;;
        --check)       ACTION="check" ;;
        --update)      ACTION="update" ;;
        -h|--help)     usage ;;
        *)             die "unknown option '$arg' (try --help)" ;;
    esac
done

# Label + flag echoed back in messages ("" unless --pre-release; note WITH_PRE=0
# is a non-empty string, so ${WITH_PRE:+...} would always expand -- hence these).
PRE_NOTE=""; PRE_FLAG=""
if [[ "$WITH_PRE" == 1 ]]; then PRE_NOTE=" (pre-release)"; PRE_FLAG=" --pre-release"; fi

case "$ACTION" in
    uninstall) do_uninstall ;;
    check)     do_check ;;
    update)    do_update ;;
esac

# fresh / normal install
detect_os
apt_install
install_uv
fetch_rata
setup_python_env
install_arduino_cli
install_arduino_deps
add_dialout
install_launchers
[[ "$WITH_PI"  == 1 ]] && configure_pi
[[ "$WITH_USB" == 1 ]] && configure_usb_gadget
[[ "$WITH_I2C" == 1 ]] && configure_i2c
run_doctor

step "Done"
ok "RATA installed under $RATA_HOME"
# The launchers only resolve if BIN_DIR is on the caller's PATH. Check the PATH
# they started with, not ours (install_uv prepended BIN_DIR to ours). Reported
# here, at the end, because that is the part people read and act on.
case ":$ORIG_PATH:" in
    *":$BIN_DIR:"*) : ;;
    *)  warn "$BIN_DIR is not on your PATH yet, so these won't resolve."
        info "Open a new login shell (it picks it up permanently), or run:"
        info "    export PATH=\"$BIN_DIR:\$PATH\""
        ;;
esac
info "Try:  rata doctor   ·   rata ui   ·   ratapyui"
[[ "$NEEDS_REBOOT" == 1 ]] && warn "$REBOOT_WHY needs a reboot to activate:  sudo reboot"
exit 0
