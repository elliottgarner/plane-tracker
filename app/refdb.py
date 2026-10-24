"""Reference database schema, shared by the runtime enricher and tools/build_reference_db.py."""
import sqlite3

from .config import DATA_DIR

REF_PATH = DATA_DIR / "reference.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS aircraft(hex TEXT PRIMARY KEY, reg TEXT, type TEXT, flags INTEGER DEFAULT 0,
                                    descr TEXT, ownop TEXT);
CREATE TABLE IF NOT EXISTS airlines(icao TEXT PRIMARY KEY, iata TEXT, name TEXT, country TEXT, callsign TEXT);
CREATE TABLE IF NOT EXISTS airports(icao TEXT PRIMARY KEY, iata TEXT, name TEXT, city TEXT, country TEXT,
                                    lat REAL, lon REAL);
CREATE INDEX IF NOT EXISTS idx_airports_iata ON airports(iata);
CREATE TABLE IF NOT EXISTS routes(callsign TEXT PRIMARY KEY, origin TEXT, dest TEXT, source TEXT, updated INTEGER);
CREATE TABLE IF NOT EXISTS route_miss(callsign TEXT PRIMARY KEY, ts INTEGER);
"""


def connect(path=REF_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")   # readers keep working while the builder writes
    con.executescript(SCHEMA)
    return con
