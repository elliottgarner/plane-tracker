"""Aircraft data collector: local readsb/dump1090 JSON, adsb.lol-style web API, or both."""
import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .config import cfg
from . import demo

log = logging.getLogger("collector")

EMERGENCY_SQUAWKS = {"7500": "HIJACK", "7600": "RADIO FAILURE", "7700": "EMERGENCY"}


def normalize(a: dict, now: float, src: str):
    """readsb/dump1090/adsb.lol aircraft object -> our flat record (None if no position)."""
    lat, lon = a.get("lat"), a.get("lon")
    if lat is None or lon is None:
        return None
    alt = a.get("alt_baro")
    on_ground = alt == "ground"
    if on_ground:
        alt_ft = 0
    elif isinstance(alt, (int, float)):
        alt_ft = int(alt)
    else:
        g = a.get("alt_geom")
        alt_ft = int(g) if isinstance(g, (int, float)) else None
    vs = a.get("baro_rate", a.get("geom_rate"))
    track = a.get("track", a.get("calc_track", a.get("true_heading", a.get("mag_heading"))))
    seen_pos = a.get("seen_pos", a.get("seen", 0)) or 0
    squawk = a.get("squawk")
    emerg = a.get("emergency")
    if emerg in (None, "none"):
        emerg = EMERGENCY_SQUAWKS.get(squawk)
    else:
        emerg = str(emerg).upper()
    return {
        "hex": str(a.get("hex", "")).lower().lstrip("~"),
        "callsign": (a.get("flight") or "").strip().upper(),
        "lat": float(lat), "lon": float(lon),
        "alt_ft": alt_ft, "on_ground": on_ground,
        "gs_kt": a.get("gs"), "track": track,
        "vs_fpm": int(vs) if isinstance(vs, (int, float)) else None,
        "squawk": squawk, "type": "" if a.get("t") == "GND" else (a.get("t") or ""),
        "reg": "" if a.get("r") == "GND" else (a.get("r") or ""),
        "category": a.get("category") or "", "emergency": emerg,
        "db_flags": a.get("dbFlags") or 0,
        "desc": a.get("desc") or "", "ownop": a.get("ownOp") or "",
        "pos_ts": now - float(seen_pos), "src": src,
    }


class Collector:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=2.0),
                                        headers={"User-Agent": "plane-tracker/1.0"})
        self._web_cache = []
        self._web_ts = 0.0
        self._cool = {}          # provider url template -> resting until (epoch)
        self.web_host = "web"
        self._local_fail = 0
        self.source_label = "—"
        self.healthy = False
        self.last_error = ""

    async def close(self):
        await self.client.aclose()

    # ---- sources -----------------------------------------------------------
    async def _read_local(self, now):
        target = cfg["local_url"]
        if target.startswith(("http://", "https://")):
            r = await self.client.get(target)
            r.raise_for_status()
            data = r.json()
        else:
            path = Path(target.replace("file://", ""))
            data = json.loads(await asyncio.to_thread(path.read_text, "utf-8"))
        file_now = data.get("now")
        # If the decoder stalls, its file stops advancing: treat as down.
        if file_now and abs(now - file_now) > 15:
            raise RuntimeError("local feed is stale (%.0fs old)" % (now - file_now))
        out = [normalize(a, file_now or now, "sdr") for a in data.get("aircraft", [])]
        return [x for x in out if x]

    async def _read_web(self, now):
        """Community readsb-style APIs with failover: a provider that rate-limits is rested."""
        if now - self._web_ts < cfg["web_poll_seconds"] and self._web_cache:
            return self._web_cache
        radius_nm = min(250, max(5, round(cfg["range_km"] / 1.852)))
        errors = []
        for tpl in cfg["web_api_urls"]:
            if self._cool.get(tpl, 0) > now:
                errors.append(f"{urlparse(tpl).hostname}: resting")
                continue
            host = (urlparse(tpl).hostname or "web").replace("opendata.", "").replace("api.", "")
            try:
                r = await self.client.get(tpl.format(lat=cfg["home_lat"], lon=cfg["home_lon"], radius_nm=radius_nm))
                if r.status_code in (429, 403, 502, 503):
                    ra = r.headers.get("retry-after", "")
                    wait = float(ra) if ra.replace(".", "", 1).isdigit() else (60 if r.status_code == 429 else 300)
                    self._cool[tpl] = now + wait
                    errors.append(f"{host}: HTTP {r.status_code} (rest {wait:.0f}s)")
                    log.warning("%s returned %s - resting it for %.0fs", host, r.status_code, wait)
                    continue
                r.raise_for_status()
                data = r.json()
                self._web_cache = [x for x in (normalize(a, now, "web")
                                               for a in (data.get("ac") or data.get("aircraft") or [])) if x]
                self._web_ts = now
                self.web_host = host
                return self._web_cache
            except Exception as e:
                self._cool[tpl] = now + 15
                errors.append(f"{host}: {e.__class__.__name__}")
        if self._web_cache and now - self._web_ts < 30:   # ride out brief outages on dead-reckoning
            return self._web_cache
        raise RuntimeError("all web providers failed: " + "; ".join(errors))

    # ---- main entry --------------------------------------------------------
    async def poll(self):
        """Returns list of normalized aircraft for this tick."""
        now = time.time()
        mode = cfg["data_source"]
        try:
            if mode == "demo":
                self.source_label, self.healthy, self.last_error = "DEMO", True, ""
                return demo.tick(now)

            if mode == "web":
                items = await self._read_web(now)
                self.source_label, self.healthy, self.last_error = "WEB · " + self.web_host, True, ""
                return items

            # local / hybrid / auto
            local, local_err = None, None
            try:
                local = await self._read_local(now)
                self._local_fail = 0
            except Exception as e:
                local_err = e
                self._local_fail += 1

            if mode == "local":
                if local is None:
                    raise local_err
                self.source_label, self.healthy, self.last_error = "SDR", True, ""
                return local

            if mode == "auto":
                if local is not None:
                    self.source_label, self.healthy, self.last_error = "SDR", True, ""
                    return local
                items = await self._read_web(now)
                self.source_label, self.healthy = "WEB (no SDR)", True
                self.last_error = f"local: {local_err}"
                return items

            # hybrid: SDR is authoritative, web fills in what the antenna can't hear
            try:
                web = await self._read_web(now)
            except Exception as e:
                web = []
                self.last_error = f"web: {e}"
            if local is None and not web:
                raise local_err or RuntimeError("no data")
            merged = {a["hex"]: a for a in web}
            for a in local or []:
                merged[a["hex"]] = a
            self.source_label = "SDR+WEB" if local is not None else "WEB (no SDR)"
            self.healthy = True
            return list(merged.values())
        except Exception as e:
            self.healthy = False
            self.last_error = str(e) or e.__class__.__name__
            log.warning("poll failed: %s", self.last_error)
            return None  # None = keep previous picture (brief outage), [] = genuinely empty

    async def run(self, on_update):
        while True:
            t0 = time.monotonic()
            items = await self.poll()
            if items is not None:
                try:
                    await on_update(items)
                except Exception:
                    log.exception("update handler failed")
            await asyncio.sleep(max(0.2, 1.0 - (time.monotonic() - t0)))
