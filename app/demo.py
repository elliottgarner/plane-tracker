"""Synthetic traffic so the UI can be developed and demoed without an SDR."""
import math
import random
import time

from .config import cfg
from . import geo

# callsign, hex, type, reg, gs(kt), alt(ft), vs, category
CAST = [
    ("BAW117", "406b8d", "A359", "G-XWBA", 440, 5200, -900, "A5"),
    ("EZY41KD", "400f1c", "A320", "G-EZBR", 330, 3400, -1400, "A3"),
    ("DLH4TN", "3c6444", "A321", "D-AIDA", 380, 11000, 1500, "A3"),
    ("RYR7XM", "4ca7b4", "B738", "EI-DCL", 350, 7800, 0, "A3"),
    ("VIR9", "406a0e", "B789", "G-VZIG", 470, 14000, 2200, "A5"),
    ("AFR1281", "3944ee", "A319", "F-GRXA", 320, 4100, -1100, "A3"),
    ("KLM1002", "484c31", "E190", "PH-EZA", 300, 6000, 800, "A3"),
    ("UAE7", "896183", "A388", "A6-EUA", 460, 9000, 1800, "A5"),
    ("N172SP", "a0d9b4", "C172", "N172SP", 105, 2100, 0, "A1"),
    ("G-BYKE", "406f01", "PA28", "G-BYKE", 95, 1500, 0, "A1"),
    ("RCH492", "ae1e3f", "C17", "05-5140", 330, 6500, 0, "A5"),
    ("ASCOT31", "43c6a1", "A332", "ZZ330", 420, 12500, 0, "A5"),
    ("EXPLORER", "43efa5", "SPIT", "G-AIST", 150, 1800, 0, "A1"),
    ("PLCE91", "407f10", "EC35", "G-POLC", 120, 1200, 0, "A7"),
    ("SHT6F", "4009a2", "AT76", "G-LMAS", 240, 3600, -500, "A3"),
    ("BGA1KQ", "4b8b4c", "A3ST", "F-GSTA", 350, 8000, 0, "A5"),
    ("TUI44A", "406d7e", "B38M", "G-TUMA", 300, 2800, -800, "A3"),
    ("NSZ2", "4789a1", "B738", "LN-NHA", 360, 9000, 0, "A3"),
]
DEMO_ROUTES = {
    "BAW117": ("EGLL", "KJFK"), "EZY41KD": ("EGKK", "LFMN"), "DLH4TN": ("EDDF", "EGLL"),
    "RYR7XM": ("EGSS", "LEMD"), "VIR9": ("EGLL", "KATL"), "AFR1281": ("LFPG", "EGLL"),
    "KLM1002": ("EHAM", "EGLC"), "UAE7": ("OMDB", "EGLL"), "SHT6F": ("EGPH", "EGLL"),
    "BGA1KQ": ("LFBO", "EGNM"), "TUI44A": ("EGLL", "GCRR"), "NSZ2": ("ENGM", "EGLL"),
}

_planes = []
_last = 0.0
_emergency_cycle = 0.0


def _spawn(i):
    cs, hx, typ, reg, gs, alt, vs, cat = CAST[i % len(CAST)]
    # fly a straight chord that misses home by a random offset
    off = random.uniform(-0.8, 0.8) * cfg["range_km"] * 0.35
    entry_brg = random.uniform(0, 360)
    r = cfg["range_km"] * 0.98
    track = (entry_brg + 180 + random.uniform(-6, 6)) % 360
    perp = (track + 90) % 360
    cx, cy = geo.offset_point(cfg["home_lat"], cfg["home_lon"], perp, off)
    lat, lon = geo.offset_point(cx, cy, entry_brg, r)
    return dict(cs=cs, hex=hx, type=typ, reg=reg, gs=gs, alt=alt, vs=vs, cat=cat,
                lat=lat, lon=lon, track=track, squawk=f"{random.randint(1000, 6777)}"[:4])


def tick(now):
    global _last, _planes
    dt = min(now - _last, 5.0) if _last else 1.0
    _last = now
    if not _planes:
        _planes = [_spawn(i) for i in range(10)]
        # start part-way along so the screen is not empty
        for p in _planes:
            d = random.uniform(0, cfg["range_km"] * 1.2)
            p["lat"], p["lon"] = geo.offset_point(p["lat"], p["lon"], p["track"], d)
    out = []
    for i, p in enumerate(_planes):
        dkm = p["gs"] * 1.852 * dt / 3600.0
        p["lat"], p["lon"] = geo.offset_point(p["lat"], p["lon"], p["track"], dkm)
        p["alt"] = max(0, p["alt"] + p["vs"] * dt / 60.0)
        if geo.haversine_km(p["lat"], p["lon"], cfg["home_lat"], cfg["home_lon"]) > cfg["range_km"] * 1.05:
            _planes[i] = p = _spawn(random.randrange(len(CAST)))
        sq = p["squawk"]
        if p["cs"] == "SHT6F" and int(now // 90) % 4 == 0:
            sq = "7700"  # periodic demo emergency
        out.append({
            "hex": p["hex"], "callsign": p["cs"], "lat": p["lat"], "lon": p["lon"],
            "alt_ft": int(p["alt"]), "on_ground": False, "gs_kt": p["gs"], "track": p["track"],
            "vs_fpm": p["vs"], "squawk": sq, "type": p["type"], "reg": p["reg"],
            "category": p["cat"], "emergency": {"7700": "EMERGENCY"}.get(sq),
            "db_flags": 1 if p["cs"] in ("RCH492", "ASCOT31") else 0, "desc": "", "ownop": "",
            "pos_ts": now, "src": "demo",
        })
    return out
