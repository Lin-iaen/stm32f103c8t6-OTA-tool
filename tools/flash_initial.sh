#!/usr/bin/env bash
# One-time wired flash of bootloader + app (Linux / macOS).
# Requires: python3 and STM32CubeProgrammer (STM32_Programmer_CLI on PATH).
# Usage: ./tools/flash_initial.sh [--port /dev/ttyUSB0]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/flash_initial.py" "$@"
