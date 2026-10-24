#!/usr/bin/env bash
# Launch Chromium in kiosk mode on the plane-tracker dashboard.
# Works on Raspberry Pi OS Bookworm under labwc / Wayfire (Wayland) or X11.
URL="${PLANE_TRACKER_URL:-http://localhost:5000/}"

# Wait for the backend (up to ~2 minutes) so we never show an error page.
for _ in $(seq 1 60); do
  curl -fs -o /dev/null "${URL}api/health" && break
  sleep 2
done

# Never let the desktop blank the screen itself; the PIR logic owns sleep.
if [ -n "$DISPLAY" ] && command -v xset >/dev/null; then
  xset s off; xset -dpms; xset s noblank
fi
# Hide the mouse cursor on X11 (the page also hides it via CSS).
command -v unclutter >/dev/null && [ -z "$WAYLAND_DISPLAY" ] && unclutter -idle 0.5 -root &

# Avoid the "Chromium didn't shut down correctly" bubble after power loss.
PREFS="$HOME/.config/chromium/Default/Preferences"
[ -f "$PREFS" ] && sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"Crashed"/"exit_type":"Normal"/' "$PREFS"

OZONE="--ozone-platform=x11"
[ -n "$WAYLAND_DISPLAY" ] && OZONE="--ozone-platform=wayland"

exec chromium-browser \
  --kiosk "$URL" \
  $OZONE \
  --noerrdialogs --disable-infobars --disable-session-crashed-bubble --no-first-run \
  --disable-features=Translate,TranslateUI --disable-pinch --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000 --password-store=basic \
  --ignore-gpu-blocklist --enable-gpu-rasterization --enable-zero-copy \
  --autoplay-policy=no-user-gesture-required
