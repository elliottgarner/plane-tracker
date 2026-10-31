(function () {
'use strict';
const $ = (s) => document.querySelector(s);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

let CFG = null, STATE = null, cfgRev = -1;
let map, tileLayer, ringLayer, homeMarker, trailLine;
const planes = new Map();          // hex -> {marker, el, rotEl, lat, lon, fix, trail, cls, rot}
let selectedHex = null;
let lastViewSet = 0, viewInit = false;
let statsData = null, statsAt = 0, statsFetching = false;

/* ------------------------------------------------------------------ units */
const UNITS = {
  imperial: { alt: (ft) => [ft, 'ft'], spd: (kt) => [kt * 1.15078, 'mph'], vs: (f) => [f, 'fpm'], dist: (km) => [km * 0.621371, 'mi'], rings: [[3, 'mi', 1.609344], [10, 'mi', 1.609344], [30, 'mi', 1.609344]] },
  nautical: { alt: (ft) => [ft, 'ft'], spd: (kt) => [kt, 'kts'], vs: (f) => [f, 'fpm'], dist: (km) => [km / 1.852, 'nm'], rings: [[3, 'nm', 1.852], [8, 'nm', 1.852], [25, 'nm', 1.852]] },
  metric: { alt: (ft) => [ft * 0.3048, 'm'], spd: (kt) => [kt * 1.852, 'km/h'], vs: (f) => [f * 0.00508, 'm/s'], dist: (km) => [km, 'km'], rings: [[5, 'km', 1], [15, 'km', 1], [50, 'km', 1]] },
};
const U = () => UNITS[(CFG && CFG.units) || 'imperial'];
const fmt = (n, d = 0) => (n == null || isNaN(n)) ? '—' : Number(n).toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d });
function fmtDist(km) { const [v, u] = U().dist(km); return [fmt(v, v < 10 ? 1 : 0), u]; }

/* ------------------------------------------------------------------ DOM helpers */
const cache = {};
function setText(id, val) { if (cache[id] !== val) { cache[id] = val; $('#' + id).textContent = val; } }
function setHtml(id, val) { if (cache['h' + id] !== val) { cache['h' + id] = val; $('#' + id).innerHTML = val; } }
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(path + ' ' + r.status);
  return r.json();
}
function control(action, extra) {
  return api('/api/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.assign({ action }, extra)) })
    .then(applyState).catch(() => {});
}

/* ------------------------------------------------------------------ map */
/* CARTO's public basemap CDN now demands an API key, so Dark Matter / Positron are rendered from
   OpenStreetMap tiles with a CSS colour treatment (one GPU-composited layer, no extra requests).
   Put a keyed style (Stadia, MapTiler, CARTO...) into the "Custom tile URL" setting to override. */
const TILES = {
  dark: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png', '© OpenStreetMap contributors', { className: 'tiles-dark' }],
  positron: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png', '© OpenStreetMap contributors', { className: 'tiles-positron' }],
  osm: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png', '© OpenStreetMap contributors', {}],
  satellite: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 'Tiles © Esri', { maxNativeZoom: 17 }],
};

function applyRotation() {
  const r = String(CFG.screen_rotation || '0'), cl = document.documentElement.classList;
  ['rot-90', 'rot-180', 'rot-270'].forEach((c) => cl.remove(c));
  if (r !== '0') cl.add('rot-' + r);
  if (map) setTimeout(() => { map.invalidateSize(false); viewInit = false; }, 50);
}

function initMap() {
  map = L.map('map', {
    zoomControl: false, attributionControl: false, zoomSnap: 0.25, zoomDelta: 0.5, fadeAnimation: false,
    inertia: false, keyboard: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false,
    touchZoom: false, boxZoom: false, tap: false, preferCanvas: true, minZoom: 6, maxZoom: 15,
  });
  L.control.attribution({ prefix: false, position: 'bottomright' }).addTo(map);
  map.setView([CFG.home_lat, CFG.home_lon], 9.5, { animate: false });
}

function applyMapConfig() {
  const c = [CFG.home_lat, CFG.home_lon];
  const def = CFG.tile_url ? [CFG.tile_url, 'Map tiles: custom provider', { subdomains: 'abcd' }] : (TILES[CFG.tile_style] || TILES.dark);
  if (tileLayer) map.removeLayer(tileLayer);
  tileLayer = L.tileLayer(def[0], Object.assign({ attribution: def[1], maxZoom: 15, keepBuffer: 3, updateWhenZooming: false, crossOrigin: true }, def[2])).addTo(map);
  if (ringLayer) map.removeLayer(ringLayer);
  ringLayer = L.layerGroup().addTo(map);
  U().rings.forEach(([n, unit, k]) => {
    const km = n * k;
    if (km > CFG.range_km * 1.05) return;
    L.circle(c, { radius: km * 1000, color: '#4fd1ff', weight: 1.2, opacity: 0.55, fill: false, dashArray: '4 6', interactive: false }).addTo(ringLayer);
    const top = [c[0] + km / 111.32, c[1]];
    L.marker(top, { interactive: false, icon: L.divIcon({ className: '', html: '<div class="ring-lbl">' + n + ' ' + unit + '</div>', iconSize: [0, 0] }) }).addTo(ringLayer);
  });
  L.circle(c, { radius: CFG.range_km * 1000, color: '#ffb000', weight: 1, opacity: 0.35, fill: false, interactive: false }).addTo(ringLayer);
  if (homeMarker) map.removeLayer(homeMarker);
  homeMarker = L.marker(c, { interactive: false, zIndexOffset: -500, icon: L.divIcon({ className: '', html: '<div class="home-dot"></div>', iconSize: [0, 0] }) }).addTo(map);
  viewInit = false;
}

function makeMarker(a) {
  const html = '<div class="ac"><div class="rot">' + planeSvg(a.cls) + '</div><span class="lbl"></span></div>';
  const m = L.marker([a.lat, a.lon], { interactive: true, bubblingMouseEvents: false, keyboard: false, icon: L.divIcon({ className: 'ac-wrap', html, iconSize: [0, 0] }) }).addTo(map);
  m.on('click', () => control('select', { hex: a.hex }));   // tap a plane: track it + show it in the side panel
  const el = m.getElement().firstChild;
  return { marker: m, el, rotEl: el.firstChild, lblEl: el.lastChild, lat: a.lat, lon: a.lon, rot: a.trk || 0, cls: a.cls, trail: [] };
}

function syncPlanes(list, st) {
  const nowS = Date.now() / 1000, seen = new Set();
  for (const a of list) {
    seen.add(a.hex);
    let p = planes.get(a.hex);
    if (!p) { p = makeMarker(a); planes.set(a.hex, p); p.rotEl.style.transition = 'none'; }
    if (p.cls !== a.cls) { p.cls = a.cls; p.rotEl.innerHTML = planeSvg(a.cls); }
    p.fix = { lat: a.lat, lon: a.lon, t: nowS - a.age, gs: a.gs || 0, trk: a.trk };
    p.cs = a.cs;
    const cls = 'ac' + (a.em ? ' em' : a.mil ? ' mil' : a.int ? ' int' : '') + (a.hex === st.selected ? ' sel' : '') + (a.apt && a.hex !== st.selected ? ' apt' : '');
    if (p.el.className !== cls) p.el.className = cls;
    if (p.lblEl.textContent !== a.cs) p.lblEl.textContent = a.cs;
    if (a.trk != null) {          // unwrap so the nose never spins the long way round
      let d = ((a.trk - p.rot) % 360 + 540) % 360 - 180;
      p.rot += d;
      p.rotEl.style.transform = 'rotate(' + p.rot.toFixed(1) + 'deg)';
    }
    if (!p.lastTrailT || nowS - p.lastTrailT > 2) {
      p.lastTrailT = nowS; p.trail.push([a.lat, a.lon]); if (p.trail.length > 90) p.trail.shift();
    }
    p.marker.setZIndexOffset(a.hex === st.selected ? 1000 : a.em ? 900 : 0);
  }
  for (const [hex, p] of planes) {
    if (!seen.has(hex)) { map.removeLayer(p.marker); planes.delete(hex); }
  }
  const z = map.getZoom();
  document.body.classList.toggle('show-labels', z >= 11);
  // trail for the selected aircraft
  const sp = st.selected && planes.get(st.selected);
  if (sp && sp.trail.length > 1) {
    if (!trailLine) trailLine = L.polyline([], { color: '#ffb000', weight: 2, opacity: 0.6, interactive: false, smoothFactor: 1.5 }).addTo(map);
    trailLine.setLatLngs(sp.trail);
  } else if (trailLine) { map.removeLayer(trailLine); trailLine = null; }
}

/* dead-reckoning + easing at ~30fps: smooth between 1 s data ticks */
let lastFrame = 0;
function frame(ts) {
  requestAnimationFrame(frame);
  if (ts - lastFrame < 33) return;
  const dt = (ts - lastFrame) / 1000; lastFrame = ts;
  if (!STATE || STATE.display_on === false || document.hidden || !map || map._animatingZoom) return;
  const now = Date.now() / 1000, k = 1 - Math.exp(-dt * 7);
  for (const p of planes.values()) {
    const f = p.fix; if (!f) continue;
    let tl = f.lat, tn = f.lon;
    if (f.gs > 0 && f.trk != null) {
      const el = Math.min(now - f.t, 20), d = f.gs * 0.514444 * el, b = f.trk * Math.PI / 180;
      tl += (d * Math.cos(b)) / 111320;
      tn += (d * Math.sin(b)) / (111320 * Math.cos(f.lat * Math.PI / 180));
    }
    p.lat += (tl - p.lat) * k; p.lon += (tn - p.lon) * k;
    p.marker.setLatLng([p.lat, p.lon]);
  }
}

function updateView(st) {
  if (!map) return;
  const home = L.latLng(CFG.home_lat, CFG.home_lon), d = st.detail;
  let center = home, zoom;
  if (d) {
    const plane = L.latLng(d.lat, d.lon);
    const z = map.getBoundsZoom(L.latLngBounds([home, plane]), false, L.point(110, 90));
    zoom = clamp(Math.floor(z * 2) / 2, 9, 13);
    if (d.dist > 3) center = L.latLng((home.lat + plane.lat) / 2, (home.lng + plane.lng) / 2);
  } else {
    zoom = st.count > 0 ? 10 : 9;
  }
  zoom = clamp(zoom + (st.zoom_offset || 0), 7, 15);
  const now = Date.now();
  const offPx = map.latLngToContainerPoint(center).distanceTo(map.getSize().divideBy(2));
  const needs = !viewInit || Math.abs(map.getZoom() - zoom) >= 0.5 || offPx > 40;
  if (needs && (!viewInit || now - lastViewSet > 1800 || st.rev !== STATE_REV_LAST)) {
    map.setView(center, zoom, { animate: viewInit, duration: 1.4, easeLinearity: 0.3 });
    lastViewSet = now; viewInit = true;
  }
  STATE_REV_LAST = st.rev;
}
let STATE_REV_LAST = -1;

/* ------------------------------------------------------------------ card */
function hue(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }

function setLogo(icao) {
  if (cache.logoIcao === icao) return;
  cache.logoIcao = icao;
  const box = $('#logo'), img = $('#logo-img'), crest = $('#logo-crest');
  box.classList.remove('has');
  const code = icao || '???';
  crest.textContent = code;
  box.style.background = icao ? 'hsl(' + hue(code) + ' 55% 36%)' : '#2a3746';
  if (!icao) { img.removeAttribute('src'); return; }
  img.onload = () => { if (cache.logoIcao === icao) { box.classList.add('has'); box.style.background = '#f2f5f8'; } };
  img.onerror = () => {};
  img.src = '/api/logo/' + icao;
}

function airportHtml(a, fallback) {
  if (!a) return '<b>' + fallback + '</b><span>unknown</span><i>&nbsp;</i>';
  const code = a.iata || a.icao || '---';
  return '<b>' + code + '</b><span>' + (a.city || a.name || '') + '</span><i>' + (a.country || '') + '</i>';
}

function renderCard(st) {
  const d = st.detail;
  const card = $('#card');
  $('#card-live').hidden = !d;
  $('#card-idle').hidden = !!d;
  card.classList.toggle('em', !!(d && d.em));
  if (!d) return renderIdle(st);

  setText('callsign', d.flight_no && d.airline ? d.callsign : (d.callsign || d.hex.toUpperCase()));
  setLogo(d.airline && d.airline.icao);
  setText('airline', d.airline ? d.airline.name + (d.flight_no && d.flight_no !== d.callsign ? ' · ' + d.flight_no : '') : (d.ownop || (d.military ? 'Military / state aircraft' : 'Private / unknown operator')));

  const badges = [];
  if (d.em) badges.push('<span class="badge em">' + (st.emergency ? st.emergency.label : 'EMERGENCY') + '</span>');
  if (d.military) badges.push('<span class="badge mil">MIL</span>');
  if (d.vip) badges.push('<span class="badge mil">VIP</span>');
  if (d.rare) badges.push('<span class="badge rare">RARE</span>');
  if (st.locked) badges.push('<span class="badge lock">LOCKED</span>');
  setHtml('badges', badges.join(''));

  // route
  const r = d.route, routeEl = $('#route');
  routeEl.classList.toggle('unknown', !r || r.progress == null);
  setHtml('apt-o', airportHtml(r && r.origin, '---'));
  setHtml('apt-d', airportHtml(r && r.dest, '---'));
  const pct = r && r.progress != null ? clamp(r.progress, 0, 1) : 0;
  $('#prog-fill').style.width = (pct * 100).toFixed(1) + '%';
  $('#prog-glyph').style.left = (pct * 100).toFixed(1) + '%';
  if (!cache.glyph) { cache.glyph = 1; $('#prog-glyph').innerHTML = planeSvg('jet'); }
  if (r && r.progress != null) { const [v, u] = fmtDist(r.remaining_km); setText('prog-txt', Math.round(pct * 100) + '% · ' + v + ' ' + u + ' to go'); }
  else setText('prog-txt', r ? ' ' : (d.route_rejected ? 'listed route doesn’t match flight path' : 'route unknown'));

  // aircraft
  setHtml('sil', planeSvg(d.cls));
  setText('model', d.type_name || d.type || 'Unknown aircraft');
  setText('reg', d.reg || 'no reg');
  setText('typecode', d.type || '----');

  // telemetry
  const [av, au] = d.alt == null ? [null, U().alt(0)[1]] : U().alt(d.alt);
  setText('t-alt', d.on_ground ? 'GND' : fmt(av)); setText('u-alt', au);
  const [sv, su] = d.gs == null ? [null, U().spd(0)[1]] : U().spd(d.gs);
  setText('t-spd', fmt(sv)); setText('u-spd', su);
  const [vv, vu] = d.vs == null ? [null, U().vs(0)[1]] : U().vs(d.vs);
  const vsEl = $('#t-vs');
  setText('t-vs', d.vs == null ? '—' : (d.vs > 0 ? '▲' : d.vs < 0 ? '▼' : '') + fmt(Math.abs(vv), vu === 'm/s' ? 1 : 0));
  vsEl.className = d.vs > 100 ? 'up' : d.vs < -100 ? 'down' : '';
  setText('u-vs', vu);
  setText('t-trk', d.trk == null ? '—' : String(Math.round(d.trk)).padStart(3, '0'));
  setText('t-sq', d.squawk || '—');
  $('#t-sq').className = ['7500', '7600', '7700'].includes(d.squawk) ? 'alert' : '';
  const [dv, du] = fmtDist(d.dist);
  setText('t-dist', dv); setText('u-dist', du);

  // look-up vector
  $('#needle').style.transform = 'rotate(' + d.bearing + 'deg)';
  setText('look-main', 'Look ' + String(d.bearing).padStart(3, '0') + '° ' + d.compass);
  let sub;
  if (d.on_ground) sub = 'on the ground';
  else if (d.elevation < 0) sub = 'below the horizon (' + fmt(Math.abs(d.elevation), 0) + '°)';
  else if (d.elevation > 75) sub = 'almost directly overhead!';
  else sub = fmt(d.elevation, 0) + '° above horizon';
  setText('look-sub', sub);
  $('#elev-fill').style.width = clamp(d.elevation / 90, 0, 1) * 100 + '%';

  setText('reason', (d.reasons && d.reasons.length && !st.locked ? '★ ' : '') + (st.reason || ''));
}

function renderIdle(st) {
  const t = new Date();
  setText('clock', t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
  setText('idle-sub', st.filter === 'interesting' ? 'No interesting traffic in range — filter: interesting only' : (st.count ? 'Nothing overhead — ' + st.count + ' aircraft at airports, on the ground or resting' : 'Waiting for aircraft…'));
  setText('idle-today', statsData ? String(statsData.total) : '—');
  const l = st.last_spotted;
  setText('idle-last', l ? l.callsign : '—');
  setText('idle-last-sub', l ? 'last: ' + (l.type || 'aircraft') + ' · ' + new Date(l.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'nothing yet');
  setText('reason', 'standing by');
}

/* ------------------------------------------------------------------ chrome / chips / alert */
function renderChrome(st) {
  const src = $('#chip-src');
  src.textContent = st.source.label; src.className = 'chip ' + (st.source.ok ? 'ok' : 'bad');
  setText('chip-count', st.count + (st.count === 1 ? ' aircraft' : ' aircraft'));
  $('#chip-filter').hidden = st.filter !== 'interesting';
  $('#no-data').hidden = st.source.ok;
  setText('no-data-msg', st.source.error || '');
  const al = $('#alert');
  if (st.emergency) {
    al.hidden = false;
    setText('alert-txt', st.emergency.label + ' · ' + st.emergency.cs + ' · SQUAWK ' + st.emergency.squawk + ' · ' + fmtDist(st.emergency.dist).join(' '));
  } else al.hidden = true;
  const showBar = st.hardware.mode === 'touch';
  $('#touch-bar').hidden = !showBar;
  $('#btn-lock').classList.toggle('on', st.locked);
  $('#btn-filter').classList.toggle('on', st.filter === 'interesting');
  setText('foot-right', (st.zoom_offset ? 'zoom ' + (st.zoom_offset > 0 ? '+' : '') + st.zoom_offset + '  ' : '') + st.count + ' in range' + (st.airport_count ? ' · ' + st.airport_count + ' at airport' : ''));
}

/* ------------------------------------------------------------------ stats view */
function renderStats(st) {
  if (!statsData) return;
  const s = statsData, titles = ['TODAY', 'HALL OF FAME', 'RARE VISITORS'];
  setText('stats-title', titles[st.stats_page]);
  setText('stats-date', new Date().toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' }));
  document.querySelectorAll('#dots i').forEach((el, i) => el.classList.toggle('on', i === st.stats_page));
  document.querySelectorAll('.page').forEach((el, i) => el.classList.toggle('on', i === st.stats_page));

  // page 0
  setText('s-total', String(s.total));
  setText('s-unique', String(s.unique));
  setText('s-peak', s.peak_hour == null ? '—' : String(s.peak_hour).padStart(2, '0') + ':00');
  setText('s-peak-sub', s.peak_hour == null ? 'peak hour' : 'peak hour · ' + s.hours[s.peak_hour] + ' aircraft');
  const max = Math.max(1, ...s.hours), nowH = new Date().getHours();
  setHtml('hours', s.hours.map((n, h) => '<i class="' + (h === s.peak_hour && n ? 'peak ' : '') + (h === nowH ? 'now' : '') + '" style="height:' + (n / max * 100) + '%">' + (n ? '<span>' + n + '</span>' : '') + '</i>').join(''));
  const li = (a) => a.length ? a.map((x) => '<li><span>' + x.name + '</span><b>' + x.n + '</b></li>').join('') : '<li><span style="color:var(--dim)">nothing yet</span></li>';
  setHtml('s-airlines', li(s.top_airlines)); setHtml('s-types', li(s.top_types));

  // page 1
  const rec = (r, kind) => {
    if (!r) return '<div class="val">—</div><div class="what">no data yet</div>';
    let val, sub;
    if (kind === 'lowest') { const [v, u] = U().alt(r.min_alt_ft); val = fmt(v) + ' <small>' + u + '</small>'; sub = ''; }
    else if (kind === 'fastest') { const [v, u] = U().spd(r.max_gs); val = fmt(v) + ' <small>' + u + '</small>'; sub = ''; }
    else { const [v, u] = fmtDist(r.min_dist_km); val = v + ' <small>' + u + '</small>'; sub = r.alt_at_closest != null ? ' at ' + fmt(U().alt(r.alt_at_closest)[0]) + ' ' + U().alt(0)[1] : ''; }
    return '<div class="val">' + val + '</div><div class="who">' + (r.callsign || r.hex.toUpperCase()) + '</div><div class="what">' + (r.type_name || r.type || '') + sub + '</div>';
  };
  const card = (title, key) => '<div class="hof-card"><h2>' + title + ' · today</h2>' + rec(s.records_today[key], key) + '<hr><div class="all"><h2>All-time</h2>' + rec(s.records_all[key], key) + '</div></div>';
  setHtml('hof', card('Lowest altitude pass', 'lowest') + card('Fastest groundspeed', 'fastest') + card('Closest fly-by', 'closest'));

  // page 2
  setHtml('rare-list', s.rare.length ? s.rare.map((r) => '<li><span class="t">' + new Date(r.first_seen * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + '</span><span class="c">' + (r.callsign || r.hex.toUpperCase()) + '</span><span class="d">' + (r.type_name || r.type || 'Unknown') + (r.reasons ? '<small>' + r.reasons + '</small>' : '') + '</span></li>').join('') : '<div class="empty">No military or rare visitors logged today — yet.</div>');
}

async function refreshStats(force) {
  if (statsFetching || (!force && Date.now() - statsAt < 20000)) return;
  statsFetching = true;
  try { statsData = await api('/api/stats'); statsAt = Date.now(); } catch (e) {} finally { statsFetching = false; }
}

/* ------------------------------------------------------------------ main loop */
function showNotice(text) {
  let el = $('#notice');
  if (!el) { el = document.createElement('div'); el.id = 'notice'; $('#app').appendChild(el); }
  el.textContent = text;
  el.classList.toggle('show', !!text);
}

function applyState(st) {
  STATE = st;
  showNotice(st.notice || '');
  const stats = st.view === 'stats';
  const wasHidden = $('#tracker').hidden;
  $('#tracker').hidden = stats;
  $('#stats').hidden = !stats;
  if (stats) { refreshStats(false); renderStats(st); return; }
  if (wasHidden && map) { map.invalidateSize(false); viewInit = false; }
  if (st.cfg_rev !== cfgRev) return;          // wait for new config before drawing
  syncPlanes(st.aircraft, st);
  selectedHex = st.selected;
  renderChrome(st);
  renderCard(st);
  updateView(st);
  if (!st.detail) refreshStats(false);
}

async function loadConfig() {
  CFG = await api('/api/config');
  return CFG;
}

async function tick() {
  try {
    const st = await api('/api/state');
    const stamp = st.version + '|' + st.reload_token;      // new release, service restart, or POST /api/reload
    if (window.__ver && stamp !== window.__ver) { location.reload(); return; }
    window.__ver = stamp;
    if (st.cfg_rev !== cfgRev) {
      await loadConfig();
      applyRotation();
      if (!map) initMap();
      applyMapConfig();
      cfgRev = st.cfg_rev;
      statsAt = 0;
    }
    applyState(st);
  } catch (e) {
    document.querySelector('#chip-src').textContent = 'BACKEND OFFLINE';
    document.querySelector('#chip-src').className = 'chip bad';
  }
  setTimeout(tick, 1000);
}

function boot() {
  document.querySelectorAll('.dial-ticks').forEach((g) => {
    let h = '';
    for (let i = 0; i < 36; i++) { const a = i * 10 * Math.PI / 180, r1 = i % 9 === 0 ? 36 : 40, r2 = 44; h += '<line x1="' + (Math.sin(a) * r1).toFixed(1) + '" y1="' + (-Math.cos(a) * r1).toFixed(1) + '" x2="' + (Math.sin(a) * r2).toFixed(1) + '" y2="' + (-Math.cos(a) * r2).toFixed(1) + '"/>'; }
    g.innerHTML = h;
  });
  document.querySelectorAll('#touch-bar button').forEach((b) => b.addEventListener('click', () => {
    const act = b.dataset.act;
    if (act === 'filter') control('set_filter', { filter: STATE && STATE.filter === 'interesting' ? 'all' : 'interesting' });
    else control(act);
  }));
  $('#stats').addEventListener('click', () => control('next'));
  $('#back-btn').addEventListener('click', (e) => { e.stopPropagation(); control('set_view', { view: 'tracker' }); });
  // the pointer stays hidden (enclosed kiosk); press "c" on a keyboard to show/hide it for debugging
  // keyboard for development / USB keypads
  const keys = { ArrowUp: 'zoom_in', ArrowDown: 'zoom_out', ArrowRight: 'next', ArrowLeft: 'prev', Enter: 'toggle_lock', m: 'toggle_view' };
  window.addEventListener('keydown', (e) => { if (keys[e.key]) { e.preventDefault(); control(keys[e.key]); } if (e.key === 'c') document.body.classList.toggle('cursor-active'); });
  requestAnimationFrame(frame);
  tick();
}
boot();
})();
