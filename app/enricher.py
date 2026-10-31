"""Metadata enrichment: hex/callsign -> airline, aircraft model, route, flags (local SQLite first)."""
import asyncio
import logging
import math
import re
import threading
import time

import httpx

from . import classify, demo, refdb, seed
from .config import cfg
from .geo import bearing_deg, haversine_km

log = logging.getLogger("enricher")

MISS_TTL = 6 * 3600


def _title(s):
    return " ".join(w.capitalize() if len(w) > 3 else w for w in (s or "").split())


class Enricher:
    def __init__(self):
        self._lock = threading.Lock()
        self.db = refdb.connect()
        self._seed()
        self._cache = {}
        self._airport_cache = {}
        self._field_cache = {}
        self.rev = 0
        self._pending = set()
        self._miss = {}
        self._sem = asyncio.Semaphore(4)
        self.client = httpx.AsyncClient(timeout=8.0, headers={"User-Agent": "plane-tracker/1.0"})
        self.stats = {"lazy_hits": 0, "lazy_misses": 0, "fallback_hits": 0}

    def reload(self):
        """Drop in-memory caches (after the reference DB has been rebuilt)."""
        self._cache.clear()
        self._airport_cache.clear()
        self._field_cache.clear()
        self.rev += 1

    def airports_near(self, lat, lon, radius_km):
        """Airports with an IATA code (i.e. real passenger airports) within radius_km of a point."""
        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * max(0.2, math.cos(math.radians(lat))))
        with self._lock:
            rows = self.db.execute(
                "SELECT icao, lat, lon FROM airports WHERE iata != '' AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                (lat - dlat, lat + dlat, lon - dlon, lon + dlon)).fetchall()
        return [r for r in rows if haversine_km(lat, lon, r[1], r[2]) <= radius_km]

    def nearest_airfield(self, lat, lon, max_km):
        """(airport dict, distance km) of the closest airfield of any size (strips and microlight sites
        included) within max_km, or None. Used to infer where a plane with no flight plan took off / is landing."""
        key = (round(lat, 2), round(lon, 2), max_km)
        rows = self._field_cache.get(key)
        if rows is None:
            pad = max_km + 1.5                                  # the key rounds the position by up to ~0.8 km
            dlat = pad / 111.0
            dlon = pad / (111.0 * max(0.2, math.cos(math.radians(lat))))
            with self._lock:
                rows = self.db.execute("SELECT icao, lat, lon FROM airports WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                                       (lat - dlat, lat + dlat, lon - dlon, lon + dlon)).fetchall()
            if len(self._field_cache) > 500:
                self._field_cache.clear()
            self._field_cache[key] = rows
        best = min(((haversine_km(lat, lon, r[1], r[2]), r[0]) for r in rows), default=None)
        if not best or best[0] > max_km:
            return None
        ap = self.airport(best[1])
        return (ap, best[0]) if ap else None

    def counts(self):
        return {t: self._q(f"SELECT COUNT(*) FROM {t}")[0] for t in ("aircraft", "airlines", "airports", "routes")}

    def _seed(self):
        with self._lock, self.db:
            self.db.executemany("INSERT OR IGNORE INTO airlines VALUES (?,?,?,?,?)", seed.AIRLINES)
            self.db.executemany("INSERT OR IGNORE INTO airports VALUES (?,?,?,?,?,?,?)", seed.AIRPORTS)

    async def close(self):
        await self.client.aclose()

    # ---- lookups -----------------------------------------------------------
    def _q(self, sql, args=()):
        with self._lock:
            return self.db.execute(sql, args).fetchone()

    def airport(self, code):
        if not code:
            return None
        code = code.upper()
        if code in self._airport_cache:
            return self._airport_cache[code]
        col = "icao" if len(code) == 4 else "iata"
        row = self._q(f"SELECT icao,iata,name,city,country,lat,lon FROM airports WHERE {col}=?", (code,))
        if not row and len(code) == 3:
            row = None
        out = None
        if row:
            out = dict(zip(("icao", "iata", "name", "city", "country", "lat", "lon"), row))
        self._airport_cache[code] = out
        return out

    def _route(self, callsign):
        row = self._q("SELECT origin,dest FROM routes WHERE callsign=?", (callsign,))
        if not row and cfg["data_source"] == "demo":
            row = demo.DEMO_ROUTES.get(callsign)
        if not row:
            return None
        o, d = self.airport(row[0]), self.airport(row[1])
        if not o and not d:
            return None
        return {"origin": o or {"icao": row[0], "iata": row[0]}, "dest": d or {"icao": row[1], "iata": row[1]}}

    def _build(self, ac):
        hex_, cs = ac["hex"], ac["callsign"]
        row = self._q("SELECT reg,type,flags,descr,ownop FROM aircraft WHERE hex=?", (hex_,))
        db_reg, db_type, db_flags, db_desc, db_own = row if row else ("", "", 0, "", "")
        typ = (ac["type"] or db_type or "").upper()
        reg = ac["reg"] or db_reg or ""
        own = ac.get("ownop") or db_own or ""
        flags = int(ac.get("db_flags") or 0) | int(db_flags or 0)
        prefix, number = classify.split_callsign(cs)
        military = bool(flags & 1) or classify.is_military_hex(hex_) or bool(
            classify.MIL_CALLSIGN.match(cs or "")) or bool(classify.MIL_OWNER.search(own))
        vip = bool(classify.VIP_CALLSIGN.match(cs or "")) or bool(classify.VIP_OWNER.search(own))

        airline = None
        if prefix and not military:
            r = self._q("SELECT icao,iata,name,country FROM airlines WHERE icao=?", (prefix,))
            if r:
                airline = dict(zip(("icao", "iata", "name", "country"), r))
        flight_no = f"{airline['iata']}{number}" if airline and airline.get("iata") and number else cs

        service = bool(classify.SERVICE_OWNER.search(own)) or bool(classify.SERVICE_CALLSIGN.match(cs or ""))
        if service:
            military = False if not (flags & 1) else military   # police helis are not "military visitors"
        type_name = seed.TYPE_NAMES.get(typ) or _title(ac.get("desc") or db_desc) or typ
        rare = classify.RARE.get(typ)
        route = self._route(cs) if cs else None
        return {
            "reg": reg, "type": typ, "type_name": type_name, "ownop": own,
            "military": military, "vip": vip, "rare": rare, "notable": bool(flags & 2), "service": service,
            "airline": airline, "flight_no": flight_no,
            "route": route,
            "silhouette": classify.silhouette(typ, ac.get("category", ""), military),
            # any airline-style callsign (ABC123) may have a scheduled route, known airline or not
            "route_lookup_ok": bool(prefix) and not military,
        }

    def enrich(self, ac):
        key = (ac["hex"], ac["callsign"])
        m = self._cache.get(key)
        if m is None:
            if len(self._cache) > 6000:
                self._cache.clear()
            m = self._cache[key] = self._build(ac)
        return m

    # ---- lazy route fallback (only ever for the aircraft on screen) ------------
    def want_route(self, ac, meta):
        cs = ac["callsign"]
        if (meta["route"] or not meta["route_lookup_ok"] or not cfg["lazy_route_lookup"]
                or cfg["data_source"] == "demo" or cs in self._pending):
            return
        t = self._miss.get(cs)
        if t and time.time() - t < MISS_TTL:
            return
        row = self._q("SELECT ts FROM route_miss WHERE callsign=?", (cs,))
        if row and time.time() - row[0] < MISS_TTL:
            self._miss[cs] = row[0]
            return
        self._pending.add(cs)
        asyncio.create_task(self._fetch_route(cs, ac["lat"], ac["lon"]))

    async def _fetch_fallback(self, cs):
        """Second opinion for callsigns the VRS list lacks (hexdb.io: "EGLL-KJFK", or "Varies" when unknown).
        Both ends must be airports we know; the plausibility check still vets it against the flight path."""
        url = cfg["route_fallback_url"]
        if not url:
            return False
        try:
            async with self._sem:
                r = await self.client.get(url.format(callsign=cs))
            if r.status_code != 200:
                return False
            codes = str((r.json() or {}).get("route", "")).upper().split("-")
            if len(codes) < 2 or not all(re.fullmatch(r"[A-Z0-9]{3,4}", c) for c in codes):
                return False
            if not (self.airport(codes[0]) and self.airport(codes[-1])):
                return False
            with self._lock, self.db:
                self.db.execute("INSERT OR REPLACE INTO routes VALUES (?,?,?,?,?)",
                                (cs, codes[0], codes[-1], "fallback", int(time.time())))
            for k in [k for k in self._cache if k[1] == cs]:
                del self._cache[k]
            self.stats["fallback_hits"] += 1
            log.info("Fallback route %s: %s -> %s", cs, codes[0], codes[-1])
            return True
        except Exception as e:
            log.info("Fallback route lookup for %s failed: %s", cs, e)
            return False

    async def _fetch_route(self, cs, lat, lon):
        """Static per-callsign JSON from the VRS standing-data mirror (CDN, no rate limit)."""
        try:
            async with self._sem:
                r = await self.client.get(cfg["route_url"].format(prefix=cs[:2], callsign=cs))
            if r.status_code == 404:
                if not await self._fetch_fallback(cs):
                    self._record_miss(cs)
                return
            r.raise_for_status()
            item = r.json()
            codes = (item or {}).get("airport_codes", "")
            parts = [p for p in str(codes).split("-") if p and p.lower() != "unknown"]
            if len(parts) >= 2:
                for ap in item.get("_airports") or []:
                    self._store_airport(ap)
                with self._lock, self.db:
                    self.db.execute("INSERT OR REPLACE INTO routes VALUES (?,?,?,?,?)",
                                    (cs, parts[0], parts[-1], "lazy", int(time.time())))
                self._airport_cache.clear()
                for k in [k for k in self._cache if k[1] == cs]:
                    del self._cache[k]
                self.stats["lazy_hits"] += 1
                log.info("Lazy route %s: %s -> %s", cs, parts[0], parts[-1])
            elif not await self._fetch_fallback(cs):
                self._record_miss(cs)
        except Exception as e:
            log.info("Route lookup for %s failed: %s", cs, e)
            self._miss[cs] = time.time() - MISS_TTL + 300  # retry in 5 min on network errors
        finally:
            self._pending.discard(cs)

    def _record_miss(self, cs):
        self.stats["lazy_misses"] += 1
        self._miss[cs] = time.time()
        with self._lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO route_miss VALUES (?,?)", (cs, int(time.time())))

    def _store_airport(self, ap):
        try:
            icao = ap.get("icao")
            lat, lon = ap.get("lat"), ap.get("lon")
            if lat is None and isinstance(ap.get("location"), dict):
                lat, lon = ap["location"].get("lat"), ap["location"].get("lon")
            if not icao or lat is None:
                return
            city = ap.get("location") if isinstance(ap.get("location"), str) else ap.get("city", "")
            with self._lock, self.db:
                self.db.execute("INSERT OR IGNORE INTO airports VALUES (?,?,?,?,?,?,?)",
                                (icao, ap.get("iata", ""), ap.get("name", ""), city,
                                 seed.COUNTRIES.get(ap.get("countryiso2"), ap.get("countryiso2", "")), lat, lon))
        except Exception:
            log.debug("bad airport payload %r", ap)


def route_plausible(route, lat, lon, track=None, gs=None):
    """Callsign->route tables are only a schedule: callsigns get reused on other legs/days.
    Accept a route only if the aircraft is actually flying along it."""
    try:
        o, d = route["origin"], route["dest"]
        if o.get("lat") is None or d.get("lat") is None:
            return True                      # can't test, nothing better to offer
        a = haversine_km(o["lat"], o["lon"], lat, lon)
        b = haversine_km(lat, lon, d["lat"], d["lon"])
        total = haversine_km(o["lat"], o["lon"], d["lat"], d["lon"])
        if a + b - total > max(40.0, 0.15 * total):     # well off the great-circle corridor
            return False
        if track is not None and (gs or 0) > 80 and b > 20 and a > 25:
            diff = abs((bearing_deg(lat, lon, d["lat"], d["lon"]) - track + 180) % 360 - 180)
            if diff > 100:                   # flying away from the destination: wrong leg
                return False
        return True
    except (KeyError, TypeError):
        return True


def route_progress(route, lat, lon):
    """Return (fraction 0..1, remaining_km, total_km) or None."""
    try:
        o, d = route["origin"], route["dest"]
        if o.get("lat") is None or d.get("lat") is None:
            return None
        a = haversine_km(o["lat"], o["lon"], lat, lon)
        b = haversine_km(lat, lon, d["lat"], d["lon"])
        total = haversine_km(o["lat"], o["lon"], d["lat"], d["lon"])
        if a + b <= 0:
            return None
        return a / (a + b), b, max(total, a + b)
    except (KeyError, TypeError):
        return None
