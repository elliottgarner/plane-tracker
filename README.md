# ✈ Plane Tracker — Pi wall display

Live ADS-B radar (left, 58%) + airport-board telemetry card (right, 42%) for a 1024×600 panel on a
Raspberry Pi 4, fed by a local RTL-SDR (`readsb`) with optional adsb.lol fallback. PIR-controlled screen sleep,
rotary-encoder / 3-way-switch / touch controls, SQLite daily stats & Hall of Fame, LAN settings page.

## Try it on any PC (no hardware)
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\...
python run.py --demo           # synthetic traffic -> http://localhost:5000  (settings: /settings)
```
Keys for testing: ↑/↓ zoom, ←/→ cycle planes, Enter lock, `m` stats view, `c` show cursor.

## Install on the Pi (Bookworm 64-bit)
```bash
git clone <this repo> plane-tracker && cd plane-tracker
bash deploy/install.sh        # venv, Leaflet, reference DB, systemd service, kiosk autostart
```
Then follow **[deploy/SDR_AND_FR24.md](deploy/SDR_AND_FR24.md)** to install `readsb` + `fr24feed` sharing one dongle,
open `http://<pi-ip>:5000/settings`, set home lat/lon, **Local SDR URL** (`/run/readsb/aircraft.json`) and reboot.

## Layout
| Path | Role |
|---|---|
| `app/collector.py` | SDR JSON reader (URL or file), adsb.lol reader, local/web/hybrid/auto/demo modes |
| `app/enricher.py`, `refdb.py`, `seed.py`, `classify.py` | hex/callsign → airline, model, route, military/rare flags; SQLite + lazy online route fallback (selected plane only, cached, negative-cached) |
| `app/tracker.py` | interest scoring, closest-first selection, dwell/hysteresis, lock, cycle, filter |
| `app/stats.py` | `data/stats.db` sightings log, daily stats, Hall of Fame |
| `app/hardware_controls.py` | encoder / toggle / touch abstraction → fixed action vocabulary |
| `app/presence.py`, `display_power.py` | PIR → display off/on (`wlr-randr`, `wlopm`, `xset`, `vcgencmd`, backlight) |
| `app/main.py` | FastAPI: `/api/state` (1 Hz), `/api/stats`, `/api/config`, `/api/control`, `/api/logo/{icao}`, pages |
| `app/static/` | vanilla JS + Leaflet UI (dead-reckoned 30 fps markers, dynamic zoom), stats view, settings |
| `tools/build_reference_db.py` | loads tar1090-db/Mictronics, OpenFlights, OurAirports, VRS routes |
| `deploy/` | installer, systemd unit, kiosk launcher, SDR/FR24 guide |

## Wiring (BCM numbers; all inputs use internal pull-ups, switches go to GND)
| Part | Pins |
|---|---|
| PIR (SR505 / HC-SR501 / AM312) | One 3-pin block on the outer column: pin 4 = 5 V, pin 6 = GND, pin 8 = OUT (GPIO14, default; change in Settings). AM312 wants 3.3 V instead (pin 1) |
| Encoder KY-040 | CLK → GPIO22, DT → GPIO23, SW → GPIO27, `+` → **3.3 V**, GND |
| Panel power relay (optional) | Module IN → GPIO26 (pin 37), VCC → 5 V, GND → GND; wire the panel's 5 V feed through the relay's **NO** contact. In Settings set *Panel power relay GPIO* to 26 and tick *active-low* for typical opto-isolated modules. While asleep the screen is blanked, then its power is cut; on wake power returns, the app waits *Panel boot wait*, then unblanks. Set *Screen power method* to *None* to rely on the relay alone |
| 3-way switch | Mode 1 → GPIO24, Mode 2 → GPIO25, Mode 3 → GPIO8, common → GND. A centre-off ON-OFF-ON switch only needs positions 1 and 3; "no contact" is treated as position 2 |

Behaviour: **Encoder** rotate = zoom (or cycle planes — setting), click = lock/unlock, long-press = Tracker ⇄ Stats.
**Toggle** 1 = all traffic (closest first), 2 = interesting/military only, 3 = Stats / Hall of Fame.
Any control input or touch also wakes a sleeping display. Pins are editable in `data/config.json`.

## How selection works
Rank = proximity (0–100) + interest bonus: emergency squawk +500 (also red banner), military +45, VIP/gov +45,
rare type +50, notable flag +25, low pass (<3 000 ft within 8 km) +30. A selected plane is held for the dwell time
(default 45 s); afterwards a challenger must win by 15 points. Emergencies pre-empt the dwell. Locked planes stay
until they leave range. Zoom follows the plane: home+plane are fitted between zoom 9 and 13 (quiet sky: 9–10);
manual zoom offsets relax after 45 s. Between 00:00–05:00 (configurable) a quiet sky shows the stats screensaver.

## Things to know / verify on your hardware
* **Map tiles:** CARTO's free CDN now returns "API KEY REQUIRED" watermarks, so *Dark Matter / Positron* are
  OpenStreetMap tiles with a CSS colour treatment. That's fine for a single home display (follow OSM's tile
  policy); for a keyed provider paste its URL in *Custom tile URL*.
* **Web data & rate limits:** adsb.lol's free API is limited to 4/s, 60/min and **500 requests per day**, which a
  live display exhausts in minutes. The default web providers are now `adsb.fi` first (≈1 req/s allowed) with
  adsb.lol only as a last resort; a provider returning 429/403 is rested (honouring `Retry-After`) and the next one
  is used. Polling is every 2 s; markers are dead-reckoned in between. airplanes.live / adsb.one currently
  require you to email them for access — add their URLs under *Web API URLs* if you get it.
* **Operators & routes:** operator names come from the local reference DB (airlines, 620k airframes), which is
  downloaded automatically in the background on first start (watch `/api/health` → `reference_db`). Routes come
  from the local table plus a per-callsign static JSON on the VRS CDN (no API limit), cached.
* **Airport traffic & helicopters:** planes below 2 500 ft within 5 km of a passenger airport (and anything on the
  ground) are never auto-selected — if that's all there is, the map rests on home with a clock. Helicopters
  (police / air ambulance most of all) rank low, are shown for ≤30 s then rested; any aircraft rotates away after
  120 s on screen. All tunable in Settings → Tracking. Emergency squawks and manual taps override everything.
* **Selection:** closeness dominates (exponential, 12 km decay — tunable in Settings); interest bonuses are
  small tie-breakers except emergencies. Tap/click any plane on the map to track it (tap again to release).
* The `tar1090-db` CSV flags column is assumed to be a decimal bitfield (a sanity guard drops the flags if
  they look wrong; 4.7% flagged military in the current file looks right). Logos come from `Jxck-S/airline-logos`;
  missing ones fall back to a coloured crest.
* **Display power on Bookworm:** `vcgencmd display_power` does nothing under KMS; the service uses `wlr-randr`
  (labwc/Wayfire) or `xset dpms` (X11). Some panels ignore HDMI blanking — test with *Settings → Screen off*.
  If the compositor socket differs, set `XDG_RUNTIME_DIR`/`WAYLAND_DISPLAY` in the service file.
  A touchscreen can't wake an HDMI-off panel; the PIR/encoder do.
* **Encoder steps:** if one click jumps several zoom levels, raise `encoder_step_divider` (e.g. 2 or 4).
* **Settings password:** copy `.env.example` to `.env` (git-ignored; the installer does this) and set
  `SETTINGS_PASSWORD`, then restart the service. `/settings`, config saves, updates, reload and the screen
  test need it; the dashboard itself stays open. Without a password the settings page is open and Wi-Fi
  management is disabled. The site is plain HTTP, so the password isn't encrypted on your LAN.
* **Wi-Fi from the settings page** (Pi OS / NetworkManager): scan, join, forget. A failed join (no internet
  within ~25 s) is rolled back to the previous network automatically. Needs the service user in the `netdev`
  group (installer does this; re-run it or `sudo usermod -aG netdev $USER` + restart).
* Hardware paths (GPIO, PIR, encoder, wlr-randr) could not be exercised off-Pi; the app runs without them
  (warning logged) and the UI/API/demo mode were tested on a PC.
