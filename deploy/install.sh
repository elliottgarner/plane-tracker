#!/usr/bin/env bash
# Plane Tracker installer for Raspberry Pi OS Bookworm (64-bit).
#   cd plane-tracker && bash deploy/install.sh
# Does NOT install readsb / fr24feed - see deploy/SDR_AND_FR24.md for those.
set -euo pipefail

APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
USER_ID="$(id -u "$USER_NAME")"
HOME_DIR="$(getent passwd "$USER_NAME" | cut -d: -f6)"
LEAFLET_VER="1.9.4"

echo "==> Installing system packages"
sudo apt-get update
sudo apt-get install -y python3-venv python3-gpiozero python3-lgpio wlr-randr wlopm x11-xserver-utils \
  unclutter curl chromium-browser 2>/dev/null || sudo apt-get install -y python3-venv python3-gpiozero \
  python3-lgpio wlr-randr x11-xserver-utils curl chromium

echo "==> Python virtualenv (with system site-packages for gpiozero/lgpio)"
python3 -m venv --system-site-packages "$APPDIR/.venv"
"$APPDIR/.venv/bin/pip" install --upgrade pip
"$APPDIR/.venv/bin/pip" install -r "$APPDIR/requirements.txt"

echo "==> Vendoring Leaflet $LEAFLET_VER (offline-safe UI)"
V="$APPDIR/app/static/vendor/leaflet"
mkdir -p "$V/images"
for f in leaflet.js leaflet.css images/layers.png images/layers-2x.png images/marker-icon.png \
         images/marker-icon-2x.png images/marker-shadow.png; do
  curl -fsSL "https://unpkg.com/leaflet@$LEAFLET_VER/dist/$f" -o "$V/$f" || echo "   (skipped $f)"
done

echo "==> Building reference database (airlines, airports, aircraft, routes) - a few minutes"
mkdir -p "$APPDIR/data"
"$APPDIR/.venv/bin/python" "$APPDIR/tools/build_reference_db.py" || echo "   Reference build had errors; the built-in seed still works."

echo "==> GPIO / display permissions"
sudo usermod -aG gpio,video,render "$USER_NAME"

echo "==> systemd service"
sed -e "s|@USER@|$USER_NAME|g" -e "s|@APPDIR@|$APPDIR|g" -e "s|@UID@|$USER_ID|g" \
  "$APPDIR/deploy/plane-tracker.service" | sudo tee /etc/systemd/system/plane-tracker.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now plane-tracker.service

echo "==> Kiosk autostart"
chmod +x "$APPDIR/deploy/kiosk.sh"
# Disable the desktop's own screen blanking (PIR logic owns it)
sudo raspi-config nonint do_blanking 1 || true
if [ -d "$HOME_DIR/.config/labwc" ] || command -v labwc >/dev/null; then
  mkdir -p "$HOME_DIR/.config/labwc"
  grep -q "plane-tracker kiosk" "$HOME_DIR/.config/labwc/autostart" 2>/dev/null || \
    echo "$APPDIR/deploy/kiosk.sh &   # plane-tracker kiosk" >> "$HOME_DIR/.config/labwc/autostart"
  echo "   labwc autostart updated"
elif [ -f "$HOME_DIR/.config/wayfire.ini" ] || command -v wayfire >/dev/null; then
  if ! grep -q "plane-tracker" "$HOME_DIR/.config/wayfire.ini" 2>/dev/null; then
    printf '\n[autostart]\nplane_tracker = %s/deploy/kiosk.sh\nscreensaver = false\ndpms = false\n' "$APPDIR" >> "$HOME_DIR/.config/wayfire.ini"
  fi
  echo "   wayfire.ini updated"
else
  mkdir -p "$HOME_DIR/.config/lxsession/LXDE-pi"
  echo "@$APPDIR/deploy/kiosk.sh" >> "$HOME_DIR/.config/lxsession/LXDE-pi/autostart"
  echo "   X11/LXDE autostart updated"
fi
chown -R "$USER_NAME": "$HOME_DIR/.config" 2>/dev/null || true

IP="$(hostname -I | awk '{print $1}')"
cat <<EOF

Done.
  Dashboard : http://$IP:5000/
  Settings  : http://$IP:5000/settings   (set your home lat/lon first!)
  Logs      : journalctl -u plane-tracker -f
Reboot to start the kiosk:  sudo reboot
EOF
