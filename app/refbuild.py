"""Populate data/reference.db from open datasets (CLI: tools/build_reference_db.py).

Sources (each optional - a failure is reported and the others still load):
  aircraft  wiedehopf/tar1090-db  (Mictronics-derived hex -> reg/type/flags/owner)
  airlines  OpenFlights airlines.dat
  airports  OurAirports airports.csv + countries.csv
  routes    Virtual Radar Server standing-data via the adsb.lol mirror (bulk callsign -> origin-dest)

Re-runnable: rows are upserted, lazily-learned routes are kept.
"""
import csv
import gzip
import io
import logging
import time
import urllib.request

from . import refdb

log = logging.getLogger("refbuild")
UA = {"User-Agent": "plane-tracker-builder/1.0"}
URLS = {
    "aircraft": "https://github.com/wiedehopf/tar1090-db/raw/csv/aircraft.csv.gz",
    "airlines": "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat",
    "airports": "https://davidmegginson.github.io/ourairports-data/airports.csv",
    "countries": "https://davidmegginson.github.io/ourairports-data/countries.csv",
    "routes": "https://vrs-standing-data.adsb.lol/routes.csv.gz",
    "airlines_vrs": "https://raw.githubusercontent.com/vradarserver/standing-data/main/airlines/schema-01/airlines.csv",
}
DB_VERSION = 2   # bump to force existing installs to rebuild (v2: VRS airline list)
state = {"running": False, "step": "", "last": {}}


def get(url, timeout=120):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if url.endswith(".gz"):
        data = gzip.decompress(data)
    return data.decode("utf-8-sig", "replace")   # some files carry a BOM that would corrupt the first header


def load_aircraft(con):
    """tar1090-db csv: semicolon separated  hex;reg;type;flags;description;year;owner"""
    rows, mil = [], 0
    for line in csv.reader(io.StringIO(get(URLS["aircraft"])), delimiter=";"):
        if len(line) < 5 or not line[0]:
            continue
        flags = int(line[3]) if line[3].isdigit() else 0
        mil += flags & 1
        rows.append((line[0].lower(), line[1], line[2], flags, line[4], line[6] if len(line) > 6 else ""))
    # Sanity guard: if the flags column is not the encoding we assumed, don't flag everything military.
    if rows and mil / len(rows) > 0.15:
        log.warning("%s/%s aircraft look military - flags encoding differs; ignoring flags", mil, len(rows))
        rows = [(a, b, c, 0, d, e) for a, b, c, _, d, e in rows]
        mil = 0
    with con:
        con.executemany("INSERT OR REPLACE INTO aircraft VALUES (?,?,?,?,?,?)", rows)
    return f"{len(rows):,} airframes ({mil:,} flagged military)"


def load_airlines(con):
    rows = {}
    for r in csv.reader(io.StringIO(get(URLS["airlines"]))):
        if len(r) < 8:
            continue
        _, name, _, iata, icao, callsign, country, active = r[:8]
        if len(icao) != 3 or not icao.isalpha():
            continue
        if icao in rows and active != "Y":
            continue
        rows[icao] = (icao, "" if iata in ("-", "\\N", "N/A") else iata, name, country,
                      "" if callsign == "\\N" else callsign)
    with con:
        con.executemany("INSERT OR REPLACE INTO airlines VALUES (?,?,?,?,?)", rows.values())
    n = len(rows)
    # OpenFlights is years out of date (no Ryanair UK / RUK, etc.); the VRS list is maintained and wins.
    vrs = 0
    try:
        for r in csv.DictReader(io.StringIO(get(URLS["airlines_vrs"]))):
            icao = (r.get("ICAO") or "").strip().upper()
            if len(icao) != 3 or not r.get("Name"):
                continue
            con.execute(
                "INSERT INTO airlines(icao,iata,name,country,callsign) VALUES (?,?,?,?,?) "
                "ON CONFLICT(icao) DO UPDATE SET name=excluded.name, "
                "iata=CASE WHEN excluded.iata!='' THEN excluded.iata ELSE iata END",
                (icao, (r.get("IATA") or "").strip(), r["Name"].strip(), "", ""))
            vrs += 1
        con.commit()
    except Exception as e:
        log.warning("VRS airline list unavailable: %s", e)
    return f"{n:,} airlines (+{vrs:,} from VRS)"


def load_airports(con):
    countries = {r["code"]: r["name"] for r in csv.DictReader(io.StringIO(get(URLS["countries"])))}
    rows = []
    for r in csv.DictReader(io.StringIO(get(URLS["airports"]))):
        if r["type"] in ("closed", "heliport", "seaplane_base", "balloonport"):
            continue
        icao = r["gps_code"] or r["ident"]
        if len(icao) != 4:
            continue
        rows.append((icao, r["iata_code"], r["name"], r["municipality"],
                     countries.get(r["iso_country"], r["iso_country"]),
                     float(r["latitude_deg"]), float(r["longitude_deg"])))
    with con:
        con.executemany("INSERT OR REPLACE INTO airports VALUES (?,?,?,?,?,?,?)", rows)
    return f"{len(rows):,} airports"


def load_routes(con):
    rows = []
    for r in csv.DictReader(io.StringIO(get(URLS["routes"]))):
        parts = [p for p in (r.get("AirportCodes") or "").split("-") if p]
        if r.get("Callsign") and len(parts) >= 2:
            rows.append((r["Callsign"].strip().upper(), parts[0], parts[-1], "vrs", int(time.time())))
    with con:
        con.executemany("INSERT OR REPLACE INTO routes VALUES (?,?,?,?,?)", rows)
    return f"{len(rows):,} routes"


STEPS = {"aircraft": load_aircraft, "airlines": load_airlines, "airports": load_airports, "routes": load_routes}
DEFAULT_ORDER = ["airlines", "airports", "aircraft", "routes"]


def build(steps=None, say=print):
    """Run the build; returns {step: message}. Safe to call from a worker thread."""
    state["running"] = True
    con = refdb.connect()
    out = {}
    try:
        for name in steps or DEFAULT_ORDER:
            t = time.time()
            state["step"] = name
            say(f"[{name}] ...")
            try:
                out[name] = f"{STEPS[name](con)} in {time.time() - t:.0f}s"
            except Exception as e:
                out[name] = f"FAILED: {e}"
            say(f"[{name}] {out[name]}")
        if steps is None and not any(v.startswith("FAILED") for v in out.values()):
            con.execute(f"PRAGMA user_version={DB_VERSION}")
    finally:
        con.close()
        state.update(running=False, step="", last=out)
    return out


def needs_build():
    con = refdb.connect()
    try:
        return (con.execute("SELECT COUNT(*) FROM aircraft").fetchone()[0] < 1000
                or con.execute("PRAGMA user_version").fetchone()[0] < DB_VERSION)
    finally:
        con.close()
