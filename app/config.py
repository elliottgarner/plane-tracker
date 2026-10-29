"""Persistent, validated runtime configuration (data/config.json)."""
import copy
import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger("config")

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path=BASE_DIR / ".env"):
    """Minimal .env reader (KEY=VALUE, # comments, optional quotes). Real environment wins."""
    try:
        for raw in path.read_text("utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            os.environ.setdefault(key.strip(), val)
    except OSError:
        pass


_load_dotenv()
DATA_DIR = Path(os.environ.get("PLANE_TRACKER_DATA", BASE_DIR / "data"))
CONFIG_PATH = DATA_DIR / "config.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"
LOGO_DIR = STATIC_DIR / "logos"

DEFAULTS = {
    # --- location -----------------------------------------------------------
    "home_lat": 53.50864828515752,
    "home_lon": -2.371656425587413,
    "home_elevation_m": 57,
    "range_km": 60,
    # --- presentation -------------------------------------------------------
    "units": "imperial",            # metric | imperial | nautical
    "tile_style": "dark",           # dark | positron | osm | satellite
    "tile_url": "",                 # optional keyed provider, e.g. https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png?api_key=...
    "screen_rotation": "0",         # 0 | 90 | 180 | 270 degrees clockwise, applied in the page (touch follows)
    "stats_page_seconds": 12,
    "stats_screensaver": {"enabled": True, "start_hour": 0, "end_hour": 5},
    # --- data ---------------------------------------------------------------
    "data_source": "hybrid",       # local | web | hybrid | auto | demo
    "local_url": "http://localhost:8080/data/aircraft.json",  # URL or file path
    # Tried in order; a provider that rate-limits (429/403) is rested and the next one is used.
    # adsb.lol's free API is capped at 4/s, 60/min and 500 per DAY, so it is last resort only.
    "web_api_urls": [
        "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{radius_nm}",
        "https://api.adsb.lol/v2/point/{lat}/{lon}/{radius_nm}",
    ],
    "web_poll_seconds": 5,
    # static per-callsign JSON on a CDN (no API limits)
    "route_url": "https://vrs-standing-data.adsb.lol/routes/{prefix}/{callsign}.json",
    "lazy_route_lookup": True,
    "auto_build_reference": True,   # download airline/aircraft/route tables in the background if missing
    "logo_sources": [
        "https://raw.githubusercontent.com/Jxck-S/airline-logos/main/flightaware_logos/{icao}.png"
    ],
    # --- tracking -----------------------------------------------------------
    "dwell_seconds": 45,
    "airport_filter": True,         # ignore (for auto-selection) traffic taking off / landing / taxiing at nearby airports
    "airport_zone_km": 5,           # radius around each passenger airport counted as "airport traffic"
    "airport_ceiling_ft": 2500,     # ...below this altitude
    "demote_helicopters": True,     # helicopters (esp. police / air ambulance) rank low and time out quickly
    "max_focus_seconds": 120,       # fixed-wing: after this long on screen, rotate away to something else
    "heli_focus_seconds": 30,       # helicopters / emergency services
    "proximity_km": 9,           # closeness half-scale: smaller = stronger preference for nearby planes
    "interest_override": True,
    "low_alt_ft": 3000,
    "low_alt_radius_km": 8,
    # --- hardware -----------------------------------------------------------
    "hardware_mode": "touch",       # encoder | toggle | touch
    "pir_enabled": True,
    "pir_gpio": 14,                 # physical pin 8: sits in one 3-pin block with 5V (pin 4) and GND (pin 6)
    "pir_timeout_min": 10,
    "display_method": "auto",       # auto | wlr-randr | wlopm | xset | vcgencmd | backlight | none
    "display_output": "",           # e.g. HDMI-A-1 (blank = all outputs)
    "panel_relay_gpio": 0,          # 0 = no relay. BCM pin driving a relay/transistor that powers the panel (e.g. 26)
    "panel_relay_active_low": True, # most relay modules switch on when the pin goes LOW
    "panel_relay_boot_seconds": 3,  # wait after powering the panel before unblanking it
    "encoder_pins": {"clk": 22, "dt": 23, "sw": 27},
    "encoder_rotate_action": "zoom",   # zoom | cycle | hybrid (rotate=zoom, click=next plane)
    "encoder_step_divider": 1,
    "long_press_seconds": 1.0,
    "toggle_pins": {"mode1": 24, "mode2": 25, "mode3": 8},
}

ENUMS = {
    "units": {"metric", "imperial", "nautical"},
    "tile_style": {"dark", "positron", "osm", "satellite"},
    "screen_rotation": {"0", "90", "180", "270"},
    "data_source": {"local", "web", "hybrid", "auto", "demo"},
    "hardware_mode": {"encoder", "toggle", "touch"},
    "display_method": {"auto", "wlr-randr", "wlopm", "xset", "vcgencmd", "backlight", "none"},
    "encoder_rotate_action": {"zoom", "cycle", "hybrid"},
}
RANGES = {
    "home_lat": (-90, 90), "home_lon": (-180, 180), "home_elevation_m": (-400, 9000),
    "range_km": (5, 400), "web_poll_seconds": (1, 60), "proximity_km": (3, 60),
    "airport_zone_km": (1, 30), "airport_ceiling_ft": (200, 10000),
    "max_focus_seconds": (20, 3600), "heli_focus_seconds": (10, 1800), "dwell_seconds": (10, 600),
    "low_alt_ft": (200, 20000), "low_alt_radius_km": (1, 100), "pir_timeout_min": (0.5, 1440),
    "pir_gpio": (0, 40), "panel_relay_gpio": (0, 27), "panel_relay_boot_seconds": (0, 30),
    "stats_page_seconds": (4, 120), "encoder_step_divider": (1, 8),
    "long_press_seconds": (0.4, 5), "start_hour": (0, 23), "end_hour": (0, 24),
    "clk": (0, 40), "dt": (0, 40), "sw": (0, 40), "mode1": (0, 40), "mode2": (0, 40), "mode3": (0, 40),
}


def _coerce(key, default, value):
    """Coerce `value` to the type of `default`; raise ValueError if impossible."""
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int):
        value = int(float(value))
    elif isinstance(default, float):
        value = float(value)
    elif isinstance(default, str):
        value = str(value).strip()
    elif isinstance(default, list):
        if not isinstance(value, list):
            raise ValueError(f"{key} must be a list")
        return [str(v) for v in value]
    if key in ENUMS and value not in ENUMS[key]:
        raise ValueError(f"{key} must be one of {sorted(ENUMS[key])}")
    if key in RANGES and not (RANGES[key][0] <= value <= RANGES[key][1]):
        raise ValueError(f"{key} out of range {RANGES[key]}")
    return value


def _merge(base, patch, path=""):
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if k not in base:
            continue  # unknown keys ignored
        if isinstance(base[k], dict):
            if isinstance(v, dict):
                out[k] = _merge(base[k], v, f"{path}{k}.")
        else:
            try:
                out[k] = _coerce(k, base[k], v)
            except (TypeError, ValueError) as e:
                raise ValueError(f"{path}{k}: {e}")
    return out


class Config:
    def __init__(self):
        self._lock = threading.RLock()
        self._data = copy.deepcopy(DEFAULTS)
        self._listeners = []
        self.rev = 1
        self.load()

    def load(self):
        try:
            if CONFIG_PATH.exists():
                stored = json.loads(CONFIG_PATH.read_text("utf-8"))
                self._data = _merge(DEFAULTS, stored)
        except Exception as e:  # corrupt file must never brick the display
            log.error("Could not read %s (%s); using defaults", CONFIG_PATH, e)

    def save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), "utf-8")
        tmp.replace(CONFIG_PATH)

    def __getitem__(self, key):
        with self._lock:
            return self._data[key]

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._data)

    def update(self, patch: dict):
        with self._lock:
            new = _merge(self._data, patch)
            changed = {k for k in new if new[k] != self._data[k]}
            self._data = new
            self.rev += 1
            self.save()
        for cb in list(self._listeners):
            try:
                cb(changed)
            except Exception:
                log.exception("config listener failed")
        return changed

    def on_change(self, cb):
        self._listeners.append(cb)


cfg = Config()
