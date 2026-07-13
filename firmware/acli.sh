#!/usr/bin/env bash
# Thin wrapper around a standalone arduino-cli (no VS Code extension required).
#
# Resolution order:
#   1. $ARDUINO_CLI            (explicit override)
#   2. arduino-cli on $PATH    (e.g. installed to ~/.local/bin -- see docs/INSTALL.md)
#   3. ~/.local/bin/arduino-cli
#
# Install it once with:
#   curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh \
#       | BINDIR="$HOME/.local/bin" sh
set -euo pipefail

if [[ -n "${ARDUINO_CLI:-}" ]]; then
    CLI="$ARDUINO_CLI"
elif command -v arduino-cli >/dev/null 2>&1; then
    CLI="$(command -v arduino-cli)"
elif [[ -x "$HOME/.local/bin/arduino-cli" ]]; then
    CLI="$HOME/.local/bin/arduino-cli"
else
    echo "acli.sh: arduino-cli not found. Install it (see docs/INSTALL.md):" >&2
    echo "  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=\"\$HOME/.local/bin\" sh" >&2
    exit 127
fi

exec "$CLI" "$@"
