"""SQLite sighting log + daily statistics / Hall of Fame queries."""
import logging
import sqlite3
import threading
import time
from datetime import datetime

from .config import DATA_DIR

log = logging.getLogger("stats")
STATS_PATH = DATA_DIR / "stats.db"
SESSION_GAP = 600  # seconds unseen before the same hex counts as a new sighting

SCHEMA = """
CREATE TABLE IF NOT EXISTS sightings(
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, hex TEXT, callsign TEXT, reg TEXT, type TEXT,
  type_name TEXT, airline TEXT, origin TEXT, dest TEXT, first_seen REAL, last_seen REAL,
  min_dist_km REAL, alt_at_closest INTEGER, min_alt_ft INTEGER, max_gs REAL,
  interest INTEGER DEFAULT 0, reasons TEXT DEFAULT '', military INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_sight_day ON sightings(day);
CREATE INDEX IF NOT EXISTS idx_sight_hex ON sightings(hex);
"""


def _day(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


class StatsLogger:
    def __init__(self):
        STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(STATS_PATH, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._sessions = {}   # hex -> dict (with '_id', '_dirty')
        self._last_flush = 0.0

    # ---- called every tick (memory only) ---------------------------------------
    def observe(self, aircraft, now=None):
        now = now or time.time()
        for hx, r in aircraft.items():
            s = self._sessions.get(hx)
            if s and now - s["last_seen"] > SESSION_GAP:
                self._sessions.pop(hx)
                s = None
            m = r["meta"]
            route = r.get("route") or {}
            if s is None:
                s = self._sessions[hx] = {
                    "_id": None, "day": _day(now), "hex": hx, "first_seen": now, "min_dist_km": 1e9,
                    "alt_at_closest": None, "min_alt_ft": None, "max_gs": 0.0, "interest": 0,
                    "reasons": set(), "military": 0,
                }
            s["last_seen"] = now
            s["callsign"] = r["callsign"] or s.get("callsign", "")
            s["reg"] = m["reg"] or s.get("reg", "")
            s["type"] = m["type"] or s.get("type", "")
            s["type_name"] = m["type_name"] or s.get("type_name", "")
            s["airline"] = (m["airline"] or {}).get("name") or s.get("airline", "")
            if route:
                s["origin"] = (route["origin"].get("iata") or route["origin"].get("icao") or "")
                s["dest"] = (route["dest"].get("iata") or route["dest"].get("icao") or "")
            if r["dist_km"] < s["min_dist_km"]:
                s["min_dist_km"], s["alt_at_closest"] = r["dist_km"], r["alt_ft"]
            if not r["on_ground"] and r["alt_ft"] is not None and r["alt_ft"] > 0:
                if s["min_alt_ft"] is None or r["alt_ft"] < s["min_alt_ft"]:
                    s["min_alt_ft"] = r["alt_ft"]
            if r["gs_kt"] and r["gs_kt"] > s["max_gs"]:
                s["max_gs"] = float(r["gs_kt"])
            sc = int(r["interest"]["score"])
            if sc > 0:
                s["interest"] = max(s["interest"], sc)
                s["reasons"].update(r["interest"]["reasons"])
            if m["military"]:
                s["military"] = 1
            s["_dirty"] = True

    # ---- persistence ------------------------------------------------------------
    def flush(self, force=False):
        now = time.time()
        if not force and now - self._last_flush < 10:
            return
        self._last_flush = now
        with self._lock, self.db:
            for hx, s in list(self._sessions.items()):
                if s.get("_dirty"):
                    vals = (s["day"], hx, s.get("callsign"), s.get("reg"), s.get("type"), s.get("type_name"),
                            s.get("airline"), s.get("origin"), s.get("dest"), s["first_seen"], s["last_seen"],
                            s["min_dist_km"], s["alt_at_closest"], s["min_alt_ft"], s["max_gs"],
                            s["interest"], "; ".join(sorted(s["reasons"])), s["military"])
                    if s["_id"] is None:
                        cur = self.db.execute(
                            "INSERT INTO sightings(day,hex,callsign,reg,type,type_name,airline,origin,dest,"
                            "first_seen,last_seen,min_dist_km,alt_at_closest,min_alt_ft,max_gs,interest,"
                            "reasons,military) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", vals)
                        s["_id"] = cur.lastrowid
                    else:
                        self.db.execute(
                            "UPDATE sightings SET day=?,hex=?,callsign=?,reg=?,type=?,type_name=?,airline=?,"
                            "origin=?,dest=?,first_seen=?,last_seen=?,min_dist_km=?,alt_at_closest=?,"
                            "min_alt_ft=?,max_gs=?,interest=?,reasons=?,military=? WHERE id=?",
                            vals + (s["_id"],))
                    s["_dirty"] = False
                if now - s["last_seen"] > SESSION_GAP:
                    self._sessions.pop(hx, None)

    # ---- queries ------------------------------------------------------------------
    def _records(self, where="", args=()):
        q = lambda order, extra: self.db.execute(
            f"SELECT * FROM sightings WHERE {extra} {where} ORDER BY {order} LIMIT 1", args).fetchone()
        rec = {}
        for name, order, extra in (
                ("lowest", "min_alt_ft ASC", "min_alt_ft > 0"),
                ("fastest", "max_gs DESC", "max_gs > 0"),
                ("closest", "min_dist_km ASC", "min_dist_km < 1e8")):
            row = q(order, extra)
            rec[name] = dict(row) if row else None
        return rec

    def summary(self):
        self.flush(force=True)
        today = _day(time.time())
        with self._lock:
            c = self.db
            total = c.execute("SELECT COUNT(*) FROM sightings WHERE day=?", (today,)).fetchone()[0]
            unique = c.execute("SELECT COUNT(DISTINCT hex) FROM sightings WHERE day=?", (today,)).fetchone()[0]
            hours = [0] * 24
            for r in c.execute("SELECT CAST(strftime('%H', first_seen,'unixepoch','localtime') AS INT) h, COUNT(*) n "
                               "FROM sightings WHERE day=? GROUP BY h", (today,)):
                hours[r["h"]] = r["n"]
            peak = max(range(24), key=lambda h: hours[h]) if total else None
            rare = [dict(r) for r in c.execute(
                "SELECT * FROM sightings WHERE day=? AND (interest>0 OR military=1) "
                "ORDER BY interest DESC, first_seen DESC LIMIT 7", (today,))]
            airlines = [dict(r) for r in c.execute(
                "SELECT airline name, COUNT(*) n FROM sightings WHERE day=? AND airline!='' "
                "GROUP BY airline ORDER BY n DESC LIMIT 3", (today,))]
            types = [dict(r) for r in c.execute(
                "SELECT COALESCE(NULLIF(type_name,''),type) name, COUNT(*) n FROM sightings "
                "WHERE day=? AND type!='' GROUP BY type ORDER BY n DESC LIMIT 3", (today,))]
            alltime_total = c.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
            return {
                "day": today, "total": total, "unique": unique, "hours": hours, "peak_hour": peak,
                "top_airlines": airlines, "top_types": types, "rare": rare,
                "records_today": self._records("AND day=?", (today,)),
                "records_all": self._records(),
                "alltime_total": alltime_total,
            }
