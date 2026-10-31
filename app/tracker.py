"""Interest scoring and the 'which aircraft is on screen' state machine."""
import math
import time

from . import geo
from .config import cfg
from .enricher import route_plausible

EMERGENCY_LABELS = {"7700": "GENERAL EMERGENCY", "7600": "RADIO FAILURE", "7500": "HIJACK"}
SWITCH_MARGIN = 10.0   # a challenger must beat the current plane by this much after dwell
EARLY_SWITCH = 45.0    # ...or by this much to cut the dwell short (e.g. a plane arrives overhead)


def evaluate(rec, meta):
    """Return {'score': float, 'reasons': [...], 'emergency': str|None}."""
    reasons, score, emergency = [], 0.0, None
    sq = rec.get("squawk")
    if sq in EMERGENCY_LABELS or rec.get("emergency"):
        emergency = EMERGENCY_LABELS.get(sq) or str(rec["emergency"]).replace("_", " ").upper()
        score += 500
        reasons.append(f"{emergency} ({sq})" if sq in EMERGENCY_LABELS else emergency)
    # Modest bonuses: they break ties between similarly-distant planes and let a rare plane win
    # at moderate range, but a plane overhead still beats an interesting one far away.
    if meta["military"]:
        score += 20
        reasons.append("Military")
    if meta["vip"]:
        score += 20
        reasons.append("VIP / Government")
    if meta["rare"]:
        score += 25
        reasons.append("Rare: " + meta["rare"])
    elif meta["notable"]:
        score += 10
        reasons.append("Notable airframe")
    alt = rec.get("alt_ft")
    if (alt is not None and not rec["on_ground"] and alt < cfg["low_alt_ft"] and meta["silhouette"] != "heli"
            and rec["dist_km"] < cfg["low_alt_radius_km"]):
        score += 30
        reasons.append(f"Low pass ({alt:,} ft)")
    return {"score": score, "reasons": reasons, "emergency": emergency}


class Tracker:
    def __init__(self, enricher):
        self.enricher = enricher
        self.aircraft = {}
        self.selected = None
        self.sel_since = 0.0
        self.hold_until = 0.0
        self.locked = False
        self.filter = "all"          # all | interesting
        self.reason = ""
        self.last_spotted = None     # summary of the last aircraft that was on screen
        self.last_plane_ts = 0.0
        self.focus = {}              # hex -> seconds spent on screen (decays while off screen)
        self.cooldown = set()        # hogs temporarily excluded from auto-selection
        self._last_tick = 0.0
        self._zones, self._zone_key = [], None
        self._seen = {}              # hex -> last update time; a gap means the plane (re)entered range
        self.departed = {}           # hex -> airport it was first seen climbing out of

    # ---- inferred origin / destination (planes with no flight plan: microlights, GA, ...) ------
    def _note_arrival(self, a, now):
        hx = a["hex"]
        gap = now - self._seen.get(hx, 0)
        self._seen[hx] = now
        if gap < 600:
            return
        self.departed.pop(hx, None)
        alt, vs = a["alt_ft"], a["vs_fpm"]
        if a["on_ground"] or alt is None or alt > 2000 or vs is None or vs < 150:
            return                                   # only a plane first seen climbing low is clearly "just departed"
        hit = self.enricher.nearest_airfield(a["lat"], a["lon"], 4)
        if hit:
            self.departed[hx] = hit[0]

    def infer(self, r):
        """{'kind': 'to'|'from', 'airport': dict} for a plane with no known route, else None. A guess from
        what we can see: low and descending towards an airfield = landing there; first seen climbing out
        of one = departed from there."""
        if r["route"]:
            return None
        alt, vs = r["alt_ft"], r["vs_fpm"]
        if not r["on_ground"] and alt is not None and alt < 1500 and vs is not None and vs < -100:
            hit = self.enricher.nearest_airfield(r["lat"], r["lon"], 5)
            if hit:
                ap, dist = hit
                ahead = dist < 1.0 or r["track"] is None or r["gs_kt"] is None or abs(
                    (geo.bearing_deg(r["lat"], r["lon"], ap["lat"], ap["lon"]) - r["track"] + 180) % 360 - 180) < 60
                if ahead:
                    return {"kind": "to", "airport": ap}
        ap = self.departed.get(r["hex"])
        return {"kind": "from", "airport": ap} if ap else None

    # ---- ingest --------------------------------------------------------------
    def update(self, items, now=None):
        now = now or time.time()
        lat0, lon0, elev = cfg["home_lat"], cfg["home_lon"], cfg["home_elevation_m"]
        rng = cfg["range_km"]
        new = {}
        for a in items:
            if not a["hex"] or now - a["pos_ts"] > 60:
                continue
            d = geo.haversine_km(lat0, lon0, a["lat"], a["lon"])
            if d > rng:
                continue
            a["dist_km"] = d
            a["bearing"] = geo.bearing_deg(lat0, lon0, a["lat"], a["lon"])
            alt_m = (a["alt_ft"] or 0) * 0.3048
            a["elevation"] = geo.elevation_deg(alt_m, d, elev)
            a["meta"] = self.enricher.enrich(a)
            r = a["meta"]["route"]
            fits = lambda rt: route_plausible(rt, a["lat"], a["lon"], a["track"], a["gs_kt"], a["alt_ft"], a["vs_fpm"])
            a["route"] = r if r and fits(r) else None
            if r and not a["route"]:                 # listed leg doesn't fit: the callsign was reused, try a second source
                a["route"] = next((alt for alt in self.enricher.alt_routes(a["callsign"]) if fits(alt)), None)
            a["route_rejected"] = bool(r) and a["route"] is None
            a["interest"] = evaluate(a, a["meta"])
            a["airport"] = self._airport_of(a)
            self._note_arrival(a, now)
            new[a["hex"]] = a
        if len(self._seen) > 4000:
            self._seen = {h: t for h, t in self._seen.items() if now - t < 3600}
            self.departed = {h: v for h, v in self.departed.items() if h in self._seen}
        self.aircraft = new
        self._track_focus(now)
        self._select(now)
        sel = self.selected_rec()
        # warm the route cache for the selected plane and its nearest neighbours
        for r in ([sel] if sel else []) + sorted(new.values(), key=lambda r: r["dist_km"])[:5]:
            self.enricher.want_route(r, r["meta"])
            if r["route_rejected"]:
                self.enricher.want_alt_route(r["callsign"])
        if sel:
            self.last_plane_ts = now
        elif new:
            self.last_plane_ts = now

    # ---- airport traffic / focus fatigue --------------------------------------------
    def _airport_of(self, r):
        """ICAO of the nearby passenger airport this plane is operating at (taking off, landing, taxiing)."""
        if not cfg["airport_filter"]:
            return None
        key = (cfg["home_lat"], cfg["home_lon"], cfg["range_km"], self.enricher.rev)
        if key != self._zone_key:
            self._zone_key = key
            self._zones = self.enricher.airports_near(cfg["home_lat"], cfg["home_lon"], cfg["range_km"] + 10)
        if not (r["on_ground"] or (r["alt_ft"] is not None and r["alt_ft"] < cfg["airport_ceiling_ft"])):
            return None
        for icao, lat, lon in self._zones:
            if geo.haversine_km(lat, lon, r["lat"], r["lon"]) <= cfg["airport_zone_km"]:
                return icao
        return None

    def _is_heli(self, r):
        return cfg["demote_helicopters"] and (r["meta"]["silhouette"] == "heli" or r["meta"]["service"])

    def _focus_limit(self, r):
        return cfg["heli_focus_seconds"] if self._is_heli(r) else cfg["max_focus_seconds"]

    def _track_focus(self, now):
        """Accumulate on-screen time; planes that hog the display get demoted, then rested."""
        dt = min(now - self._last_tick, 5.0) if self._last_tick else 0.0
        self._last_tick = now
        for hx in list(self.focus):
            if hx not in self.aircraft:
                del self.focus[hx]
                self.cooldown.discard(hx)
        for hx, r in self.aircraft.items():
            f = self.focus.get(hx, 0.0)
            f = f + dt if hx == self.selected else max(0.0, f - dt * 0.25)   # rests 4x slower than it tires
            self.focus[hx] = f
            lim = self._focus_limit(r)
            if f > lim * 2:
                self.cooldown.add(hx)
            elif f < lim:
                self.cooldown.discard(hx)

    # ---- selection -----------------------------------------------------------
    def _rank(self, r):
        # exponential closeness: 5 km ~ 66, 12 km ~ 37, 30 km ~ 8 (proximity_km = decay length)
        prox = 100.0 * math.exp(-r["dist_km"] / cfg["proximity_km"])
        em = bool(r["interest"]["emergency"])
        bonus = r["interest"]["score"] if (cfg["interest_override"] or self.filter == "interesting") else 0
        pen = 0.0
        if not em:
            if self._is_heli(r):
                pen += 70.0 if r["meta"]["service"] else 40.0
            pen += max(0.0, self.focus.get(r["hex"], 0.0) - self._focus_limit(r)) * 2.0   # fatigue
        return prox + bonus - pen

    def _candidates(self):
        recs = [r for r in self.aircraft.values() if not r["on_ground"]]
        if cfg["airport_filter"]:
            recs = [r for r in recs if not r["airport"]]
        recs = [r for r in recs if r["hex"] not in self.cooldown or r["interest"]["emergency"]]
        if self.filter == "interesting":
            recs = [r for r in recs if r["interest"]["score"] > 0]
        return recs

    def _switch(self, rec, now, hold=None):
        if rec is None:
            self.selected = None
            return
        if rec["hex"] != self.selected:
            self.selected = rec["hex"]
            self.sel_since = now
        self.hold_until = now + (hold if hold is not None else cfg["dwell_seconds"])

    def _select(self, now):
        cur = self.aircraft.get(self.selected) if self.selected else None
        if self.selected and cur is None:      # left the boundary / lost
            self.locked = False
        if self.locked and cur:
            self._set_reason(cur)
            return
        cands = self._candidates()
        if not cands:
            self.selected = None
            self.reason = ""
            return
        best = max(cands, key=self._rank)
        cur_ok = cur is not None and any(c["hex"] == cur["hex"] for c in cands)
        if not cur_ok:
            self._switch(best, now)
        elif best["hex"] != cur["hex"]:
            emergency_preempt = best["interest"]["emergency"] and not cur["interest"]["emergency"]
            gap = self._rank(best) - self._rank(cur)
            if emergency_preempt or gap > EARLY_SWITCH or (now >= self.hold_until and gap > SWITCH_MARGIN):
                self._switch(best, now)
        sel = self.aircraft.get(self.selected)
        if sel:
            self._set_reason(sel)

    def _set_reason(self, rec):
        if self.locked:
            self.reason = "Locked"
        elif rec["interest"]["reasons"] and rec["interest"]["score"] > 0:
            self.reason = rec["interest"]["reasons"][0]
        elif self.filter == "interesting":
            self.reason = "Interesting traffic"
        else:
            self.reason = "Closest aircraft"
        m = rec["meta"]
        self.last_spotted = {
            "callsign": rec["callsign"] or rec["hex"].upper(), "type": m["type_name"] or m["type"],
            "airline": (m["airline"] or {}).get("name"), "ts": time.time(), "dist_km": rec["dist_km"],
        }

    # ---- controls ------------------------------------------------------------
    def selected_rec(self):
        return self.aircraft.get(self.selected) if self.selected else None

    def toggle_lock(self):
        if self.selected_rec():
            self.locked = not self.locked
        else:
            self.locked = False
        return self.locked

    def select_hex(self, hex_):
        """User picked a plane (click/tap on the map): show it and keep it until unlocked."""
        if self.locked and self.selected == hex_:
            self.locked = False            # tapping the tracked plane again releases it
            self.hold_until = 0
            return
        rec = self.aircraft.get(hex_)
        if rec is None:
            return
        self._switch(rec, time.time())
        self.locked = True
        self._set_reason(rec)

    def cycle(self, delta=1):
        cands = sorted(self._candidates(), key=lambda r: r["dist_km"])
        if not cands:
            return
        idx = next((i for i, r in enumerate(cands) if r["hex"] == self.selected), -1)
        pick = cands[(idx + delta) % len(cands)]
        self._switch(pick, time.time(), hold=max(60, cfg["dwell_seconds"]))
        self._set_reason(pick)

    def set_filter(self, mode):
        if mode in ("all", "interesting") and mode != self.filter:
            self.filter = mode
            self.locked = False
            self.hold_until = 0
            self._select(time.time())

    def emergencies(self):
        out = [r for r in self.aircraft.values() if r["interest"]["emergency"]]
        return sorted(out, key=lambda r: r["dist_km"])
