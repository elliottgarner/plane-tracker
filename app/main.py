"""FastAPI application: collector loop, REST API, dashboard + settings pages."""
import asyncio
import logging
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .collector import Collector
from .config import LOGO_DIR, STATIC_DIR, cfg
from .display_power import DisplayPower
from .enricher import Enricher, route_progress
from .geo import compass
from .hardware_controls import HardwareControls
from . import refbuild
from .presence import PresenceManager
from .stats import StatsLogger
from .tracker import Tracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("main")

LOGO_EXTS = ("svg", "png", "webp", "jpg")
MANUAL_ZOOM_TIMEOUT = 45  # seconds before a manual zoom offset relaxes back to automatic


class UI:
    """Display state shared by touch, rotary encoder and toggle switch."""

    def __init__(self):
        self.view = "tracker"          # tracker | stats  (user-selected)
        self.zoom_offset = 0
        self.last_input = 0.0
        self.stats_page = 0
        self.stats_page_ts = time.time()
        self.rev = 0
        self.lock = threading.RLock()


ui = UI()
STATS_PAGES = 3


def dispatch(action, **kw):
    now = time.time()
    with ui.lock:
        ui.rev += 1
        in_stats = ui.view == "stats" or app_state.effective_view == "stats"
        if action in ("zoom_in", "zoom_out", "next", "prev") and in_stats:
            step = 1 if action in ("zoom_in", "next") else -1
            ui.stats_page = (ui.stats_page + step) % STATS_PAGES
            ui.stats_page_ts = now
        elif action == "zoom_in":
            ui.zoom_offset = min(3, ui.zoom_offset + 1)
            ui.last_input = now
        elif action == "zoom_out":
            ui.zoom_offset = max(-3, ui.zoom_offset - 1)
            ui.last_input = now
        elif action == "next":
            app_state.tracker.cycle(+1)
        elif action == "prev":
            app_state.tracker.cycle(-1)
        elif action == "select":
            if not in_stats:
                app_state.tracker.select_hex(str(kw.get("hex", "")).lower())
        elif action == "toggle_lock":
            if in_stats:
                ui.view = "tracker"
            else:
                app_state.tracker.toggle_lock()
        elif action == "toggle_view":
            ui.view = "tracker" if in_stats else "stats"
            ui.stats_page = 0
            ui.stats_page_ts = now
            app_state.schedule_override_until = now + 120 if ui.view == "tracker" else 0
        elif action == "set_view":
            ui.view = kw.get("view") if kw.get("view") in ("tracker", "stats") else "tracker"
            ui.stats_page_ts = now
            app_state.schedule_override_until = now + 120 if ui.view == "tracker" else 0
        elif action == "set_filter":
            app_state.tracker.set_filter(kw.get("filter", "all"))
        elif action == "position":
            n = int(kw.get("n", 1))
            if n == 3:
                ui.view = "stats"
            else:
                ui.view = "tracker"
                app_state.tracker.set_filter("all" if n == 1 else "interesting")
            ui.stats_page = 0
            ui.stats_page_ts = now
        else:
            raise ValueError(f"unknown action {action}")


class AppState:
    def __init__(self):
        self.collector = Collector()
        self.enricher = Enricher()
        self.tracker = Tracker(self.enricher)
        self.stats = StatsLogger()
        self.display = DisplayPower()
        self.presence = PresenceManager(self.display)
        self.controls = HardwareControls(dispatch, on_activity=self.presence.poke)
        self.effective_view = "tracker"
        self.schedule_override_until = 0.0
        self.tasks = []
        self.cached_stats = (0.0, None)


app_state: AppState


# ---------------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app):
    global app_state
    app_state = AppState()
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    s = app_state

    async def on_update(items):
        with ui.lock:
            s.tracker.update(items)
        s.stats.observe(s.tracker.aircraft)

    async def housekeeping():
        while True:
            await asyncio.sleep(10)
            try:
                await asyncio.to_thread(s.stats.flush)
            except Exception:
                log.exception("stats flush")

    def on_cfg_change(changed):
        hw = {"hardware_mode", "encoder_pins", "toggle_pins", "long_press_seconds",
              "encoder_rotate_action", "encoder_step_divider"}
        if changed & hw:
            s.controls.reload()
        if changed & {"pir_enabled", "pir_gpio", "pir_timeout_min"}:
            s.presence.reload()

    async def build_reference():
        """First run: fetch airline/aircraft/airport/route tables in the background."""
        try:
            if cfg["auto_build_reference"] and refbuild.needs_build():
                log.info("Reference database is empty - downloading it in the background...")
                await asyncio.to_thread(refbuild.build, None, log.info)
                s.enricher.reload()
                log.info("Reference database ready: %s", s.enricher.counts())
        except Exception:
            log.exception("reference build failed")

    cfg.on_change(on_cfg_change)
    s.tasks.append(asyncio.create_task(build_reference()))
    s.presence.start()
    s.controls.start()
    s.tasks += [asyncio.create_task(s.collector.run(on_update)), asyncio.create_task(housekeeping())]
    log.info("Plane tracker up: source=%s home=(%.4f, %.4f) range=%skm hw=%s",
             cfg["data_source"], cfg["home_lat"], cfg["home_lon"], cfg["range_km"], cfg["hardware_mode"])
    try:
        yield
    finally:
        for t in s.tasks:
            t.cancel()
        s.controls.stop()
        s.presence.stop()
        await asyncio.to_thread(s.stats.flush, True)
        await s.collector.close()
        await s.enricher.close()


app = FastAPI(title="Plane Tracker", lifespan=lifespan)


# ---------------------------------------------------------------------------------
# helpers
def _airport_out(a):
    if not a:
        return None
    return {k: a.get(k) for k in ("icao", "iata", "name", "city", "country", "lat", "lon")}


def _brief(r):
    m = r["meta"]
    return {
        "hex": r["hex"], "cs": r["callsign"] or r["hex"].upper(), "lat": round(r["lat"], 5),
        "lon": round(r["lon"], 5), "trk": r["track"], "gs": r["gs_kt"], "alt": r["alt_ft"],
        "age": round(max(0.0, time.time() - r["pos_ts"]), 1), "dist": round(r["dist_km"], 2),
        "cls": m["silhouette"], "mil": m["military"], "int": r["interest"]["score"] > 0,
        "em": bool(r["interest"]["emergency"]), "apt": bool(r.get("airport")),
    }


def _detail(r, locked):
    m = r["meta"]
    route = r["route"]            # validated against the plane's actual position/heading
    prog = route_progress(route, r["lat"], r["lon"]) if route else None
    return {
        **_brief(r),
        "callsign": r["callsign"], "flight_no": m["flight_no"], "airline": m["airline"],
        "reg": m["reg"], "type": m["type"], "type_name": m["type_name"], "ownop": m["ownop"],
        "vs": r["vs_fpm"], "squawk": r["squawk"], "bearing": round(r["bearing"]),
        "compass": compass(r["bearing"]), "elevation": round(r["elevation"], 1),
        "on_ground": r["on_ground"], "reasons": r["interest"]["reasons"],
        "military": m["military"], "vip": m["vip"], "rare": m["rare"],
        "route": ({"origin": _airport_out(route["origin"]), "dest": _airport_out(route["dest"]),
                   "progress": round(prog[0], 3) if prog else None,
                   "remaining_km": round(prog[1], 1) if prog else None,
                   "total_km": round(prog[2], 1) if prog else None} if route else None),
        "locked": locked, "route_rejected": r.get("route_rejected", False),
    }


def _schedule_active(now):
    sc = cfg["stats_screensaver"]
    if not sc["enabled"]:
        return False
    h = datetime.fromtimestamp(now).hour
    a, b = sc["start_hour"], sc["end_hour"]
    return (a <= h < b) if a <= b else (h >= a or h < b)


def build_state():
    s, now = app_state, time.time()
    with ui.lock:
        if ui.zoom_offset and now - ui.last_input > MANUAL_ZOOM_TIMEOUT:
            ui.zoom_offset = 0
        t = s.tracker
        view = ui.view
        if (view == "tracker" and _schedule_active(now) and now > s.schedule_override_until
                and not t.selected and now - t.last_plane_ts > 30):
            view = "stats"
        s.effective_view = view
        if view == "stats" and now - ui.stats_page_ts > cfg["stats_page_seconds"]:
            ui.stats_page = (ui.stats_page + 1) % STATS_PAGES
            ui.stats_page_ts = now
        sel = t.selected_rec()
        aircraft = sorted(t.aircraft.values(), key=lambda r: r["dist_km"])[:80]
        em = t.emergencies()
        return {
            "ts": now, "rev": ui.rev, "cfg_rev": cfg.rev, "view": view, "stats_page": ui.stats_page,
            "zoom_offset": ui.zoom_offset, "filter": t.filter, "locked": t.locked,
            "reason": t.reason, "selected": t.selected,
            "detail": _detail(sel, t.locked) if sel else None,
            "aircraft": [_brief(r) for r in aircraft],
            "count": len(t.aircraft),
            "airport_count": sum(1 for r in t.aircraft.values() if r.get("airport")),
            "emergency": ({"cs": em[0]["callsign"] or em[0]["hex"].upper(),
                           "label": em[0]["interest"]["emergency"], "squawk": em[0]["squawk"],
                           "hex": em[0]["hex"], "dist": round(em[0]["dist_km"], 1)} if em else None),
            "last_spotted": t.last_spotted,
            "source": {"label": s.collector.source_label, "ok": s.collector.healthy,
                       "error": s.collector.last_error},
            "display_on": s.display.is_on,
            "hardware": {"mode": s.controls.active_mode, "error": s.controls.error},
        }


# ---------------------------------------------------------------------------------
# API
@app.get("/api/state")
async def api_state():
    return JSONResponse(build_state(), headers={"Cache-Control": "no-store"})


@app.get("/api/stats")
async def api_stats():
    s = app_state
    ts, cached = s.cached_stats
    if cached is None or time.time() - ts > 5:
        cached = await asyncio.to_thread(s.stats.summary)
        s.cached_stats = (time.time(), cached)
    return JSONResponse(cached, headers={"Cache-Control": "no-store"})


@app.get("/api/config")
async def api_get_config():
    return cfg.snapshot()


@app.post("/api/config")
async def api_set_config(patch: dict = Body(...)):
    try:
        changed = cfg.update(patch)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "changed": sorted(changed), "config": cfg.snapshot()}


@app.post("/api/control")
async def api_control(body: dict = Body(...)):
    action = str(body.get("action", ""))
    kw = {k: v for k, v in body.items() if k != "action"}
    app_state.presence.poke("touch/control")
    try:
        dispatch(action, **kw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return build_state()


@app.post("/api/display/{state}")
async def api_display(state: str):
    if state not in ("on", "off"):
        raise HTTPException(400, "state must be on|off")
    ok = await asyncio.to_thread(app_state.display.set, state == "on")
    if state == "on":
        app_state.presence.last_motion = time.time()
    return {"ok": ok, "display_on": app_state.display.is_on}


@app.get("/api/health")
async def api_health():
    s = app_state
    return {"ok": True, "source": s.collector.source_label, "feed_ok": s.collector.healthy,
            "error": s.collector.last_error, "aircraft": len(s.tracker.aircraft),
            "presence": s.presence.status(), "hardware": s.controls.active_mode,
            "hardware_error": s.controls.error, "lazy_routes": s.enricher.stats,
            "reference_db": {**s.enricher.counts(), "building": refbuild.state["running"],
                             "step": refbuild.state["step"], "last_build": refbuild.state["last"]}}


_logo_miss = {}
_logo_busy = set()


async def _download_logo(icao):
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as c:
            for tpl in cfg["logo_sources"]:
                url = tpl.format(icao=icao, icao_lower=icao.lower())
                r = await c.get(url)
                ctype = r.headers.get("content-type", "")
                if r.status_code == 200 and ctype.startswith("image/"):
                    ext = "svg" if "svg" in ctype else ("png" if "png" in ctype else
                          "webp" if "webp" in ctype else "jpg")
                    (LOGO_DIR / f"{icao}.{ext}").write_bytes(r.content)
                    return
    except Exception as e:
        log.info("logo %s: %s", icao, e)
    finally:
        _logo_busy.discard(icao)


@app.get("/api/logo/{icao}")
async def api_logo(icao: str):
    icao = icao.upper()
    if not re.fullmatch(r"[A-Z0-9]{2,4}", icao):
        raise HTTPException(404)
    for ext in LOGO_EXTS:
        p = LOGO_DIR / f"{icao}.{ext}"
        if p.exists():
            return FileResponse(p, headers={"Cache-Control": "public, max-age=604800"})
    # lazy cache: try the configured source once per day per airline, in the background
    if icao not in _logo_busy and time.time() - _logo_miss.get(icao, 0) > 86400 and cfg["logo_sources"]:
        _logo_miss[icao] = time.time()
        _logo_busy.add(icao)
        asyncio.create_task(_download_logo(icao))
    raise HTTPException(404)


# ---------------------------------------------------------------------------------
# pages
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/settings")
async def settings_page():
    return FileResponse(STATIC_DIR / "settings.html", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico")
async def favicon():
    return RedirectResponse("/static/favicon.svg")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
