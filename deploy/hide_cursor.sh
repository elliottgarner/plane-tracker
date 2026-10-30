#!/usr/bin/env bash
# Hide the compositor's own mouse pointer (labwc). Run once, then reboot:
#   bash deploy/hide_cursor.sh [home-dir]
set -euo pipefail
APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${1:-$HOME}"

python3 "$APPDIR/deploy/make_blank_cursor.py" "$HOME_DIR/.local/share/icons/blank"

ENV_FILE="$HOME_DIR/.config/labwc/environment"
mkdir -p "$(dirname "$ENV_FILE")"
touch "$ENV_FILE"
sed -i '/^XCURSOR_THEME=/d' "$ENV_FILE"
echo "XCURSOR_THEME=blank" >> "$ENV_FILE"
echo "Set XCURSOR_THEME=blank in $ENV_FILE - reboot for it to take effect."
