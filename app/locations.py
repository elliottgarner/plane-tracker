"""Saved locations (data/locations.json): named home positions you can switch between.

Switching just writes the chosen position into the live config (home_lat / home_lon / elevation / range),
so the map, data polling and distance maths all follow without a restart.
"""
import json
import logging
import threading

from .config import DATA_DIR, cfg

log = logging.getLogger("locations")
PATH = DATA_DIR / "locations.json"
_lock = threading.RLock()
_KEYS = ("home_lat", "home_lon", "home_elevation_m", "range_km")


def _read():
    try:
        data = json.loads(PATH.read_text("utf-8"))
        return [d for d in data if isinstance(d, dict) and d.get("name")]
    except (OSError, ValueError):
        return []


def _write(items):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2), "utf-8")
    tmp.replace(PATH)


def _clean(name, lat, lon, elev, range_km):
    name = str(name).strip()[:40]
    if not name:
        raise ValueError("give the location a name")
    lat, lon, elev, range_km = float(lat), float(lon), float(elev), float(range_km)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("latitude / longitude out of range")
    if not (5 <= range_km <= 400):
        raise ValueError("range must be 5-400 km")
    return {"name": name, "home_lat": lat, "home_lon": lon, "home_elevation_m": int(round(elev)),
            "range_km": int(round(range_km))}


def list_all():
    with _lock:
        return _read()


def current_name():
    """Name of the saved location matching the live config (None if home has been edited by hand)."""
    for d in list_all():
        if abs(d["home_lat"] - cfg["home_lat"]) < 1e-6 and abs(d["home_lon"] - cfg["home_lon"]) < 1e-6:
            return d["name"]
    return None


def save(name, lat, lon, elev, range_km):
    """Add or replace (by name, case-insensitive)."""
    item = _clean(name, lat, lon, elev, range_km)
    with _lock:
        items = [d for d in _read() if d["name"].lower() != item["name"].lower()]
        items.append(item)
        _write(items)
    return item


def save_current(name):
    return save(name, cfg["home_lat"], cfg["home_lon"], cfg["home_elevation_m"], cfg["range_km"])


def delete(name):
    with _lock:
        items = _read()
        keep = [d for d in items if d["name"].lower() != str(name).lower()]
        if len(keep) == len(items):
            raise ValueError("unknown location")
        _write(keep)


def use(name):
    with _lock:
        item = next((d for d in _read() if d["name"].lower() == str(name).lower()), None)
    if not item:
        raise ValueError("unknown location")
    cfg.update({k: item[k] for k in _KEYS})
    log.info("Switched to location %r (%.4f, %.4f)", item["name"], item["home_lat"], item["home_lon"])
    return item


def cycle():
    """Switch to the next saved location (wraps). Returns it, or None if there is nothing to switch to."""
    items = list_all()
    if len(items) < 1:
        return None
    cur = current_name()
    names = [d["name"] for d in items]
    nxt = items[(names.index(cur) + 1) % len(items)] if cur in names else items[0]
    if cur == nxt["name"]:
        return None
    return use(nxt["name"])
