/* RoofersParadise hail map -- MapLibre spatial cockpit (v5, viewport loading).
   Swaths are contoured on demand for the CURRENT MAP VIEWPORT, so it scales to the whole
   US: pan/zoom -> refetch only what's on screen. Stale responses are dropped. */

const NWS = ['interpolate', ['linear'], ['get', 'hail_in'],
  0.75, '#ffd24d', 1.0, '#fb9a3c', 1.5, '#f2542d', 2.0, '#c01818', 2.75, '#7a0c0c'];
// "hot zones": color by how many storm-days hit a cell (repeat-hit = highest opportunity)
const FREQ = ['interpolate', ['linear'], ['get', 'hits'],
  2, '#d9d2f0', 3, '#a98fe0', 5, '#7b52cc', 8, '#4b1fa6'];
const LEGEND_SIZE = '<b>Max hail</b><i style="background:#8f1010"></i>2&quot;+ ' +
  '<i style="background:#f2542d"></i>1.5&quot; <i style="background:#fb9a3c"></i>1&quot; <i style="background:#ffd24d"></i>0.75&quot;';
const LEGEND_FREQ = '<b>Storm-days (repeat hits)</b><i style="background:#4b1fa6"></i>8+ ' +
  '<i style="background:#7b52cc"></i>5 <i style="background:#a98fe0"></i>3 <i style="background:#d9d2f0"></i>2';

const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256, attribution: '&copy; OpenStreetMap' } },
    layers: [{ id: 'osm', type: 'raster', source: 'osm' }]
  },
  center: [-83.4, 28.2], zoom: 6, attributionControl: false
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
map.addControl(new maplibregl.GeolocateControl({
  positionOptions: { enableHighAccuracy: true }, trackUserLocation: true }), 'top-right');
map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');

let DATES = [], curIdx = 0, totalMode = true, playTimer = null, searchMarker = null, fetchSeq = 0, winStart = '';
let metric = 'size';   // 'size' (max hail) | 'frequency' (repeat-hit hot zones)
const $ = id => document.getElementById(id);

map.on('load', async () => {
  map.addSource('swaths', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
  map.addLayer({ id: 'swath-fill', type: 'fill', source: 'swaths',
    paint: { 'fill-color': NWS, 'fill-opacity': 0.72 } });
  map.addLayer({ id: 'swath-line', type: 'line', source: 'swaths',
    paint: { 'line-color': '#5a2a08', 'line-width': 1.1, 'line-opacity': 0.7 } });

  map.on('click', 'swath-fill', e => {
    const p = e.features[0].properties;
    if (metric === 'frequency') {
      showBadge(e.point, null, `${p.hits}+ storms`);
      openSheet(`${p.hits}+ storm-days here`, 'How often hail has hit this spot -- repeat-hit zones are the highest-opportunity neighborhoods.', '');
    } else {
      const inches = +p.hail_in;
      showBadge(e.point, inches);
      const dt = DATES[curIdx];
      openSheet(`${inches.toFixed(2)}" hail`,
        `${totalMode ? 'Worst hail recorded here' : (dt ? human(dt.date) : '')} -- radar-estimated max stone size.`, '');
    }
  });
  map.on('mouseenter', 'swath-fill', () => map.getCanvas().style.cursor = 'pointer');
  map.on('mouseleave', 'swath-fill', () => map.getCanvas().style.cursor = '');

  // refetch swaths for the new viewport whenever the map settles after a pan/zoom
  let moveT;
  map.on('moveend', () => { clearTimeout(moveT); moveT = setTimeout(refresh, 350); });

  const d = await (await fetch('/api/dates')).json();
  DATES = d.dates || [];
  const range = $('t-range');
  range.max = Math.max(0, DATES.length - 1);
  curIdx = DATES.length - 1;
  range.value = curIdx;
  $('t-total').checked = true;
  await refresh();
  const hide = () => { const l = $('loading'); if (l) l.classList.add('gone'); };
  map.once('idle', hide);
  setTimeout(hide, 15000);
});

function human(iso) {
  const [y, m, dd] = iso.split('-');
  return ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+m - 1] + ' ' + (+dd) + ', ' + y;
}
function mapBbox() {
  const b = map.getBounds();
  return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map(v => v.toFixed(3)).join(',');
}
function updateLabel() {
  const dt = DATES[curIdx];
  if (totalMode) {
    $('t-date').firstChild.nodeValue = 'All hail';
    const s = winStart || (DATES[0] && DATES[0].date);
    $('t-year').textContent = (s ? human(s).replace(/,.*/, '') : '') +
      ' to ' + (DATES.length ? human(DATES[DATES.length - 1].date).replace(', ', ' ') : '');
  } else if (dt) {
    $('t-date').firstChild.nodeValue = human(dt.date).replace(', ' + dt.date.slice(0, 4), '');
    $('t-year').textContent = dt.date.slice(0, 4) + ' · ' + dt.cells.toLocaleString() + ' cells nationwide';
  }
}
function spin(on) { $('updating').classList.toggle('on', on); }

async function refresh() {
  if (!DATES.length) return;
  const dt = DATES[curIdx];
  let url = `/api/hail?bbox=${mapBbox()}`;
  if (totalMode) {
    winStart = DATES[0].date;   // full scope -- every storm on record for this viewport
    url += `&start=${winStart}&end=${DATES[DATES.length - 1].date}`;
  } else {
    url += `&date=${dt.date}`;
  }
  url += '&metric=' + metric;
  updateLabel();
  const seq = ++fetchSeq;
  spin(true);
  try {
    const fc = await (await fetch(url)).json();
    if (seq !== fetchSeq) return;            // a newer request started -- drop this stale one
    map.getSource('swaths').setData(fc);
  } catch (e) { /* leave prior swaths on transient error */ }
  finally { if (seq === fetchSeq) spin(false); }
}
function loadDate(i) {
  curIdx = Math.max(0, Math.min(DATES.length - 1, i));
  $('t-range').value = curIdx;
  return refresh();
}

/* time controls */
$('t-range').oninput = e => loadDate(+e.target.value);
$('t-prev').onclick = () => loadDate(curIdx - 1);
$('t-next').onclick = () => loadDate(curIdx + 1);
$('t-total').onchange = e => { totalMode = e.target.checked; refresh(); };
$('t-play').onclick = e => {
  if (playTimer) { clearInterval(playTimer); playTimer = null; e.target.innerHTML = '&#9654;'; return; }
  if (totalMode) { $('t-total').checked = false; totalMode = false; }
  e.target.textContent = '❚❚';
  playTimer = setInterval(() => loadDate(curIdx >= DATES.length - 1 ? 0 : curIdx + 1), 1100);
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
  map.setPaintProperty('swath-fill', 'fill-color', freq ? FREQ : NWS);
  $('legend').innerHTML = freq ? LEGEND_FREQ : LEGEND_SIZE;
  const b = $('btn-mode'); b.classList.toggle('active', freq); b.textContent = freq ? 'Hot zones' : 'Hail size';
  refresh();
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
$('sheet-cta').onclick = () => ghost('addresses');

/* ghost doors -> waitlist modal (logs willingness to pay) */
const LABELS = {
  addresses: ['See every home in this hail zone', 'The exact homes under the hail, minus the ones that already got re-roofed -- your door-knock list, done.'],
  phones: ['See homeowner phone numbers', 'Reach the homeowner before you drive out.']
};
function ghost(door) {
  const [h, p] = LABELS[door];
  fetch('/api/ghost', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ door: door + '_open', zone: '' }) });
  $('card').innerHTML = `<h3>${h}</h3><p>${p}<br><br>Coming soon. Drop your email and you're first in line.</p>
     <input id="g-email" type="email" placeholder="you@company.com (optional)">
     <button class="go" onclick="submitGhost('${door}')">Notify me when it's ready</button>`;
  $('modal').classList.add('on');
}
window.submitGhost = function (door) {
  const email = $('g-email').value;
  fetch('/api/ghost', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ door, email, zone: '' }) })
    .then(() => { $('card').innerHTML = '<div class="ok">You\'re on the list. We\'ll email you the moment it opens.</div>';
      setTimeout(() => $('modal').classList.remove('on'), 1500); });
};
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
  const url = dark ? 'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'
                   : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  if (map.getSource('osm')) map.getSource('osm').setTiles([url]);
  e.currentTarget.classList.toggle('active', dark);
  e.currentTarget.textContent = dark ? 'Light' : 'Dark';
};
