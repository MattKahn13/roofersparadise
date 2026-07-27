/* RoofersParadise hail map -- MapLibre with dynamic RASTER TILES (/tiles/{z}/{x}/{y}.png).
   Tiles load per viewport-tile, so the map streams in progressively and only loads what's on
   screen; zooming shows the coarse parent tile (blurry) until the sharp child arrives. Colors
   are baked into the tiles server-side to match the legend below. */

const LEGEND_SIZE = '<b>Max hail</b><i style="background:#8f1010"></i>2&quot;+ ' +
  '<i style="background:#f2542d"></i>1.5&quot; <i style="background:#fb9a3c"></i>1&quot; <i style="background:#ffd24d"></i>0.75&quot;';
const LEGEND_FREQ = '<b>Storm-days (repeat hits)</b><i style="background:#4b1fa6"></i>8+ ' +
  '<i style="background:#7b52cc"></i>5 <i style="background:#a98fe0"></i>3 <i style="background:#d9d2f0"></i>2';

// Carto basemaps -- app-friendly (OSM's public tiles block deployed apps -> blank map).
const BASE_LIGHT = 'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png';
const BASE_DARK  = 'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png';
const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    sources: { osm: { type: 'raster', tiles: [BASE_LIGHT], tileSize: 256,
      attribution: '&copy; OpenStreetMap &copy; CARTO' } },
    layers: [{ id: 'osm', type: 'raster', source: 'osm' }]
  },
  center: [-95, 30], zoom: 6, attributionControl: false,   // Gulf/Texas (hail-heavy) -- small bbox = fast first load; geolocate moves to the user if allowed
  dragRotate: false, pitchWithRotate: false, touchPitch: false, bearing: 0, pitch: 0
});
map.touchZoomRotate.disableRotation();   // north-up ALWAYS -- the map can never tilt "sideways"
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
const geolocate = new maplibregl.GeolocateControl({
  positionOptions: { enableHighAccuracy: true }, trackUserLocation: false, showAccuracyCircle: false });
map.addControl(geolocate, 'top-right');
map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');

let DATES = [], curIdx = 0, totalMode = true, searchMarker = null;
let metric = 'size';   // 'size' (max hail) | 'frequency' (repeat-hit hot zones)
const $ = id => document.getElementById(id);

map.on('load', async () => {
  map.addSource('hail', { type: 'raster', tiles: [tileUrl()], tileSize: 256,
    minzoom: 0, maxzoom: 22, attribution: 'Hail: NOAA MRMS' });
  map.addLayer({ id: 'hail', type: 'raster', source: 'hail',
    paint: { 'raster-opacity': 0.82, 'raster-resampling': 'linear' } });   // linear = smooth / blur-in

  map.on('click', onMapClick);
  map.on('dataloading', e => { if (e.sourceId === 'hail') setBar('load'); });
  map.on('idle', () => setBar('done'));

  const d = await (await fetch('/api/dates')).json();
  DATES = d.dates || [];
  curIdx = DATES.length - 1;
  totalMode = true;
  if (DATES.length) {
    const pk = $('t-picker');
    pk.min = DATES[0].date; pk.max = DATES[DATES.length - 1].date; pk.value = DATES[curIdx].date;
  }
  updateTime();
  reloadTiles();   // apply the real date range now that DATES is loaded

  // Start at the user's own area if they allow location; otherwise keep the Gulf/Texas default.
  await new Promise(res => {
    if (!navigator.geolocation) return res();
    let done = false; const finish = () => { if (!done) { done = true; res(); } };
    const t = setTimeout(finish, 4500);
    navigator.geolocation.getCurrentPosition(
      p => { clearTimeout(t); map.jumpTo({ center: [p.coords.longitude, p.coords.latitude], zoom: 8 }); finish(); },
      () => { clearTimeout(t); finish(); },
      { enableHighAccuracy: false, timeout: 4000, maximumAge: 600000 });
  });
  const hide = () => { const l = $('loading'); if (l) l.classList.add('gone'); };
  map.once('idle', hide);
  setTimeout(hide, 15000);
});

function human(iso) {
  const [y, m, dd] = iso.split('-');
  return ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+m - 1] + ' ' + (+dd) + ', ' + y;
}
// tile URL for the current metric + date ('' date = cumulative "all hail")
function tileUrl() {
  const d = (!totalMode && DATES[curIdx]) ? '&date=' + DATES[curIdx].date : '';
  return `${location.origin}/tiles/{z}/{x}/{y}.png?metric=${metric}${d}`;
}
function reloadTiles() {
  updateTime();
  const src = map.getSource('hail');
  if (src) src.setTiles([tileUrl()]);
}
// top progress bar (nprogress-style): creeps to 90% while tiles load, completes on idle
function setBar(state) {
  const b = $('progress'); if (!b) return;
  if (state === 'load') {
    if (b._done) { clearTimeout(b._done); b._done = null; }
    b.style.transition = 'none'; b.style.opacity = '1'; b.style.width = '8%';
    requestAnimationFrame(() => { b.style.transition = 'width 9s cubic-bezier(.1,.7,.25,1)'; b.style.width = '90%'; });
  } else {
    b.style.transition = 'width .3s ease'; b.style.width = '100%';
    b._done = setTimeout(() => { b.style.opacity = '0'; b.style.width = '0'; }, 400);
  }
}
// tap the map -> nearest cell's value (raster tiles carry no clickable features)
async function onMapClick(e) {
  const { lat, lng } = e.lngLat;
  let r; try { r = await (await fetch(`/api/point?lat=${lat}&lng=${lng}`)).json(); } catch (_) { return; }
  if (metric === 'frequency') {
    if (r.hits) { showBadge(e.point, null, `${r.hits} storm-days`);
      openSheet(`${r.hits} storm-days here`, 'How often hail has hit this spot -- repeat-hit zones are the highest-opportunity neighborhoods.', ''); }
  } else if (r.max_in) {
    showBadge(e.point, r.max_in);
    const when = totalMode ? 'Worst hail recorded here' : (DATES[curIdx] ? human(DATES[curIdx].date) : '');
    openSheet(`${r.max_in.toFixed(2)}" hail`, `${when} -- radar-estimated max stone size.`, '');
  }
}
function updateTime() {
  $('t-all').classList.toggle('active', totalMode);
  const dt = DATES[curIdx];
  if (dt && !totalMode) $('t-picker').value = dt.date;
}
function loadDate(i) {
  curIdx = Math.max(0, Math.min(DATES.length - 1, i));
  return reloadTiles();
}

/* time controls: "All hail" default + calendar date-picker + prev/next storm-day (no autoplay) */
$('t-all').onclick = () => { totalMode = true; reloadTiles(); };
$('t-prev').onclick = () => { totalMode = false; loadDate(curIdx - 1); };
$('t-next').onclick = () => { totalMode = false; loadDate(curIdx + 1); };
$('t-picker').onchange = e => {
  const iso = e.target.value;
  if (!iso || !DATES.length) return;
  totalMode = false;
  let i = DATES.findIndex(x => x.date === iso);       // exact storm-day
  if (i < 0) i = DATES.findIndex(x => x.date > iso);  // else the next storm-day after it
  if (i < 0) i = DATES.length - 1;                    // else the latest on record
  loadDate(i);
};

function showBadge(pt, inches, label) {
  const b = $('hailbadge');
  b.style.left = pt.x + 'px'; b.style.top = pt.y + 'px';
  b.textContent = label || `${(+inches).toFixed(2)}" hail`; b.style.display = 'block';
  clearTimeout(showBadge._t); showBadge._t = setTimeout(() => b.style.display = 'none', 2600);
}

/* Hot-zones toggle: size (max hail) <-> frequency (repeat-hit) */
function toggleMetric() {
  metric = metric === 'size' ? 'frequency' : 'size';
  const freq = metric === 'frequency';
  $('legend').innerHTML = freq ? LEGEND_FREQ : LEGEND_SIZE;
  const b = $('btn-mode'); b.classList.toggle('active', freq); b.textContent = freq ? 'Hot zones' : 'Hail size';
  reloadTiles();
}
$('btn-mode').onclick = toggleMetric;

/* address search -> fly there (moveend refetches viewport) + hail history */
const q = $('q');
q.addEventListener('keydown', async e => {
  if (e.key !== 'Enter' || !q.value.trim()) return;
  q.blur();
  const r = await (await fetch('https://nominatim.openstreetmap.org/search?format=json&limit=1&q='
    + encodeURIComponent(q.value))).json();
  if (!r.length) { openSheet('Address not found', 'Try a street address or city.', ''); return; }
  const lat = +r[0].lat, lng = +r[0].lon;
  map.flyTo({ center: [lng, lat], zoom: 11 });
  if (searchMarker) searchMarker.remove();
  searchMarker = new maplibregl.Marker({ color: '#f2a71b' }).setLngLat([lng, lat]).addTo(map);
  const h = await (await fetch(`/api/address_history?lat=${lat}&lng=${lng}`)).json();
  const rows = (h.hits || []).map(x =>
    `<div class="row"><span>${human(x.date)}</span><b>${x.max_in.toFixed(2)}"</b></div>`).join('');
  const label = r[0].display_name.split(',').slice(0, 2).join(',');
  const report = `<button class="cta" style="background:#12202e;margin-top:14px" onclick="window.open('/static/report.html?lat=${lat}&lng=${lng}&address='+encodeURIComponent(${JSON.stringify(label)}),'_blank')">Get the full hail report<small>Printable -- hand it to the homeowner or their adjuster</small></button>`;
  openSheet(label,
    h.hits && h.hits.length ? `Hit by hail ${h.hits.length} time(s):` : 'No radar-detected hail on record here.', rows + report);
});

/* bottom sheet */
const sheet = $('sheet');
function openSheet(title, sub, html) {
  $('sheet-title').textContent = title; $('sheet-sub').textContent = sub;
  $('sheet-content').innerHTML = html || ''; sheet.classList.add('open');
}
$('grip').onclick = () => sheet.classList.remove('open');
$('modal').addEventListener('click', e => { if (e.target.id === 'modal') e.currentTarget.classList.remove('on'); });

/* ---- accounts + live hail alerts (Google sign-in -> Resend email; the HailTrace "be there first" value) ---- */
let ME = null;
async function loadMe() {
  try { ME = (await (await fetch('/api/me')).json()).user; } catch (e) { ME = null; }
  return ME;
}

function alertCardSignedOut() {
  $('card').innerHTML = `<h3>Get hail alerts &mdash; free</h3>
    <p>The moment 1&quot;+ hail lands near a ZIP you watch, we email you &mdash; so you beat the competition to the damage.</p>
    <a class="go" style="display:block;text-align:center;text-decoration:none;box-sizing:border-box" href="/auth/login">Sign in with Google</a>
    <p style="margin-top:10px;font-size:12px">We only use your email to send the alerts you ask for. The map stays free with no login.</p>`;
}

function alertCardSignedIn() {
  const c = map.getCenter();
  $('card').innerHTML = `<h3>Alert me when hail hits</h3>
    <p>Signed in as <b>${ME.email}</b>. Watch a ZIP (or the center of your current map) and we'll email you the moment 1&quot;+ hail lands within ~15 miles.</p>
    <input id="a-zip" placeholder="ZIP to watch (blank = current map center)" inputmode="numeric">
    <button class="go" onclick="submitAlert(${c.lat.toFixed(4)},${c.lng.toFixed(4)})">Watch for hail</button>
    <div style="margin-top:12px;display:flex;justify-content:space-between;font-size:13px">
      <a href="#" onclick="showMyAlerts();return false">My alerts</a>
      <a href="#" onclick="logout();return false" style="color:var(--mute)">Sign out</a>
    </div>`;
}

$('btn-alert').onclick = async () => {
  await loadMe();
  ME ? alertCardSignedIn() : alertCardSignedOut();
  $('modal').classList.add('on');
};

window.submitAlert = async function (lat, lng) {
  const zip = ($('a-zip').value || '').trim();
  let plat = lat, plng = lng;
  if (zip) {
    try {
      const r = await (await fetch('https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=us&q='
        + encodeURIComponent(zip))).json();
      if (r.length) { plat = +r[0].lat; plng = +r[0].lon; }
    } catch (e) { /* fall back to map center */ }
  }
  const res = await (await fetch('/api/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ zip, lat: plat, lng: plng, radius_mi: 15 }) })).json();
  if (res.ok) {
    $('card').innerHTML = `<div class="ok">Watching ${zip || 'this area'}. We'll email ${ME.email} the moment hail hits.</div>`;
    setTimeout(() => $('modal').classList.remove('on'), 2100);
  } else {
    $('card').innerHTML = `<div class="ok">${res.error || 'Something went wrong -- try again.'}</div>`;
  }
};

window.showMyAlerts = async function () {
  $('modal').classList.remove('on');
  const subs = (await (await fetch('/api/my_subscriptions')).json()).subscriptions || [];
  const al = (await (await fetch('/api/my_alerts')).json()).alerts || [];
  const subRows = subs.length ? subs.map(s =>
    `<div class="row"><span>Watching ${s.zip || (s.lat.toFixed(2) + ',' + s.lng.toFixed(2))}</span>` +
    `<b onclick="delSub('${s.id}')" style="cursor:pointer;color:#c01818">remove</b></div>`).join('')
    : '<p class="sub">No ZIPs watched yet.</p>';
  const alRows = al.length ? al.map(a =>
    `<div class="row"><span>${human((a.fired_at || '').slice(0, 10))} &mdash; ${a.zip || ''}</span>` +
    `<b>${(+a.max_in).toFixed(2)}"</b></div>`).join('')
    : '<p class="sub">No alerts fired yet &mdash; we\'ll email you the moment one does.</p>';
  openSheet('My alerts', ME ? ME.email : '',
    '<h2 style="font-size:15px;margin:6px 0">Watching</h2>' + subRows +
    '<h2 style="font-size:15px;margin:14px 0 6px">Recent alerts</h2>' + alRows);
};

window.delSub = async function (id) {
  await fetch('/api/subscribe/' + id, { method: 'DELETE' });
  showMyAlerts();
};

window.logout = async function () {
  await fetch('/auth/logout', { method: 'POST' });
  ME = null; $('modal').classList.remove('on');
};

// returning from the Google redirect (/?auth=ok) -> reflect signed-in state, reopen the watch card
if (location.search.includes('auth=ok')) {
  history.replaceState({}, '', location.pathname);
  loadMe().then(() => { if (ME) { alertCardSignedIn(); $('modal').classList.add('on'); } });
}

/* layers: dark basemap toggle */
let dark = false;
$('btn-layers').onclick = e => {
  dark = !dark;
  if (map.getSource('osm')) map.getSource('osm').setTiles([dark ? BASE_DARK : BASE_LIGHT]);
  e.currentTarget.classList.toggle('active', dark);
  e.currentTarget.textContent = dark ? 'Light' : 'Dark';
};
