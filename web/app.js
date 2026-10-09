// Wasserturm – Web-UI. Einstellungen werden aus dem Schema des Servers aufgebaut.
'use strict';
const $ = (id) => document.getElementById(id);
const canvas = $('view'), ctx = canvas.getContext('2d');
let ws = null, settings = {}, schema = [], meta = null, status = {};
const inputs = {};   // key -> Funktion, die den Wert ins Bedienelement schreibt

function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }

// Doppelklick ins Bild setzt den Zielpunkt (dort, wo der Strahl auftrifft)
canvas.addEventListener('dblclick', (e) => {
  const r = canvas.getBoundingClientRect();
  const pct = (p) => Math.max(-45, Math.min(45, Math.round((p - 0.5) * 100)));
  send({ t: 'set', k: 'aim_x', v: pct((e.clientX - r.left) / r.width) });
  send({ t: 'set', k: 'aim_y', v: pct((e.clientY - r.top) / r.height) });
});
function chip(id, cls, text) { const e = $(id); e.className = 'chip ' + cls; if (text) e.textContent = text; }

function connect() {
  ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
  ws.binaryType = 'blob';
  ws.onopen = () => chip('c-conn', 'ok', 'Connected');
  ws.onclose = () => { chip('c-conn', 'bad', 'Disconnected'); setTimeout(connect, 1500); };
  ws.onmessage = (ev) => {
    if (typeof ev.data !== 'string') { drawFrame(ev.data, meta); return; }
    const m = JSON.parse(ev.data);
    if (m.t === 'f') meta = m;
    else if (m.t === 'status') { status = m; showStatus(); }
    else if (m.t === 'settings') { settings = m.settings; fill(); }
    else if (m.t === 'hello') { schema = m.schema; settings = m.settings; build(); fill(); }
    else if (m.t === 'log') { const l = $('log'); l.textContent = m.msg + '\n' + l.textContent.slice(0, 4000); }
  };
}

// ------------------------------------------------------------------ Bild
const COLORS = { cat: '#f5b942', person: '#3fa7ff' };
const NAMES = { cat: 'Cat', person: 'Person' };
let busy = false;
async function drawFrame(blob, m) {
  if (busy || !m) return;
  busy = true;
  try {
    const img = await createImageBitmap(blob);
    if (canvas.width !== m.w || canvas.height !== m.h) { canvas.width = m.w; canvas.height = m.h; }
    ctx.drawImage(img, 0, 0);
    img.close();
    ctx.font = '14px system-ui';
    ctx.lineWidth = 2;
    m.dets.forEach((d, i) => {
      const [x1, y1, x2, y2, score, label] = d;
      const col = COLORS[label] || '#fff';
      ctx.strokeStyle = col;
      ctx.lineWidth = i === m.idx ? 4 : 2;
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      const text = (NAMES[label] || label) + ' ' + Math.round(score * 100) + ' %';
      const tw = ctx.measureText(text).width + 8;
      ctx.fillStyle = col;
      ctx.fillRect(x1, Math.max(0, y1 - 18), tw, 18);
      ctx.fillStyle = '#000';
      ctx.fillText(text, x1 + 4, Math.max(13, y1 - 5));
    });
    // Zielpunkt
    const [ax, ay] = m.aim;
    ctx.strokeStyle = m.ready ? '#ff5d5d' : (m.locked ? '#3ecf8e' : 'rgba(255,255,255,.6)');
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(ax - 14, ay); ctx.lineTo(ax + 14, ay);
    ctx.moveTo(ax, ay - 14); ctx.lineTo(ax, ay + 14);
    ctx.stroke();
    const zone = (settings.fire_zone || 0) / 100;
    ctx.strokeRect(ax - zone * m.w / 2, ay - zone * m.h / 2, zone * m.w, zone * m.h);
    $('badge').textContent = m.ready ? 'In fire window' : m.locked ? 'Target locked' :
      m.dets.length ? m.dets.length + ' detected' : 'nothing detected';
  } catch (e) { /* defektes Bild überspringen */ }
  busy = false;
}

// ---------------------------------------------------------------- Status
const SRC = { rc: 'Remote control', coral: 'Coral', idle: 'Idle' };
function showStatus() {
  const s = status, c = s.core_status || {};
  chip('c-cam', s.cam_ok ? 'ok' : 'bad', s.cam_ok ? 'Camera' : 'Camera missing');
  chip('c-core', s.core ? 'ok' : 'bad', s.core ? 'Core' : 'Core missing');
  chip('c-rc', c.rc ? 'ok' : '', c.rc ? 'Remote on' : 'Remote off');
  chip('c-armed', s.armed ? 'warn' : 'ok', s.firing && s.armed ? 'FIRING' : s.armed ? 'ARMED' : 'Safe');
  $('arm').checked = !!s.armed;
  $('fire').disabled = !s.armed;
  const parts = [
    ['Camera', s.cam_fps + ' fps'], ['Detection', s.det_fps + ' fps'], ['TPU', s.infer_ms + ' ms'],
    ['Control', SRC[c.src] || '–'], ['Pan', c.pan === undefined ? '–' : c.pan + ' %'],
    ['Heading ≈', c.pan_est === undefined ? '–' : c.pan_est + '°'],
    ['Tilt', c.tilt === undefined ? '–' : c.tilt + '°'],
    ['Trigger', c.trig === undefined ? '–' : c.trig + '°'], ['CPU', s.temp + ' °C'],
  ];
  if (s.blocked) parts.push(['Blocked', 'person in view']);
  if (s.model_error) parts.push(['Model error', s.model_error]);
  if (s.rc_raw) parts.push(['RC raw', s.rc_raw.join(' ')]);
  $('stats').innerHTML = parts.map(([k, v]) => k + ' <b>' + v + '</b>').join('');
  if (c.trig !== undefined) $('trig-val').textContent = c.trig;
}

// --------------------------------------------------------- Einstellungen
function build() {
  const root = $('settings');
  root.innerHTML = '';
  const open = JSON.parse(localStorage.getItem('open') || '["Operation","Detection"]');
  const secs = {};
  for (const f of schema) {
    if (f.key === 'target') continue;            // eigene Knöpfe
    if (!secs[f.sec]) {
      const d = document.createElement('details');
      d.open = open.includes(f.sec);
      d.innerHTML = '<summary>' + f.sec + '</summary><div class="fields"></div>';
      d.addEventListener('toggle', () => localStorage.setItem('open', JSON.stringify(
        [...root.querySelectorAll('details[open] summary')].map((s) => s.textContent))));
      root.appendChild(d);
      secs[f.sec] = d.querySelector('.fields');
    }
    secs[f.sec].appendChild(field(f));
  }
}

function field(f) {
  const div = document.createElement('div');
  div.className = 'field ' + f.type;
  const set = (v) => send({ t: 'set', k: f.key, v });
  if (f.type === 'bool') {
    div.innerHTML = '<label><input type="checkbox"> <span></span></label>';
    div.querySelector('span').textContent = f.label;
    const cb = div.querySelector('input');
    cb.onchange = () => set(cb.checked);
    inputs[f.key] = (v) => { cb.checked = !!v; };
  } else if (f.type === 'select') {
    div.innerHTML = '<label></label><select></select>';
    div.querySelector('label').textContent = f.label;
    const sel = div.querySelector('select');
    for (const [val, text] of f.opts) sel.add(new Option(text, val));
    sel.onchange = () => set(sel.value);
    inputs[f.key] = (v) => { sel.value = String(v); };
  } else if (f.type === 'text') {
    div.innerHTML = '<label></label><input type="text">';
    div.querySelector('label').textContent = f.label;
    const inp = div.querySelector('input');
    inp.onchange = () => set(inp.value);
    inputs[f.key] = (v) => { if (document.activeElement !== inp) inp.value = v; };
  } else {
    div.innerHTML = '<label><span></span></label><div class="row"><input type="range"><input type="number"></div>';
    div.querySelector('span').textContent = f.label;
    const [range, num] = div.querySelectorAll('input');
    for (const e of [range, num]) { e.min = f.min; e.max = f.max; e.step = f.step; }
    range.oninput = () => { num.value = range.value; };
    range.onchange = () => set(parseFloat(range.value));
    num.onchange = () => set(parseFloat(num.value));
    inputs[f.key] = (v) => {
      if (document.activeElement !== range) range.value = v;
      if (document.activeElement !== num) num.value = v;
    };
  }
  if (f.hint) {
    const p = document.createElement('p');
    p.className = 'hint';
    p.textContent = f.hint;
    div.appendChild(p);
  }
  return div;
}

function fill() {
  for (const k in inputs) if (k in settings) inputs[k](settings[k]);
  document.querySelectorAll('#modes button').forEach((b) =>
    b.classList.toggle('on', b.dataset.target === settings.target));
}

// --------------------------------------------------------------- Bedienung
document.querySelectorAll('#modes button').forEach((b) => {
  b.onclick = () => send({ t: 'set', k: 'target', v: b.dataset.target });
});
$('stop').onclick = () => send({ t: 'cmd', c: 'stop' });
$('arm').onchange = (e) => send({ t: 'cmd', c: 'arm', v: e.target.checked });
$('fire').onclick = () => send({ t: 'cmd', c: 'fire' });
$('home').onclick = () => send({ t: 'cmd', c: 'tilt_home' });
$('zero').onclick = () => send({ t: 'cmd', c: 'pan_zero' });
$('trig').oninput = (e) => send({ t: 'cmd', c: 'trig', v: parseInt(e.target.value, 10) });

// Halten zum Bewegen: solange gehalten wird, alle 100 ms senden; der Server stoppt von selbst.
const held = new Set();
let timer = null;
function pump() {
  let pan = 0, tilt = 0;
  held.forEach((d) => { const [x, y] = d.split(',').map(Number); pan += x; tilt += y; });
  send({ t: 'manual', pan, tilt });
  if (!held.size) { clearInterval(timer); timer = null; }
}
function hold(dir, on) {
  if (on) held.add(dir); else held.delete(dir);
  document.querySelectorAll('.pad [data-dir]').forEach((b) => b.classList.toggle('held', held.has(b.dataset.dir)));
  if (on && !timer) timer = setInterval(pump, 100);
  pump();
}
document.querySelectorAll('.pad [data-dir]').forEach((b) => {
  b.addEventListener('pointerdown', (e) => { e.preventDefault(); b.setPointerCapture(e.pointerId); hold(b.dataset.dir, true); });
  for (const ev of ['pointerup', 'pointercancel', 'lostpointercapture']) b.addEventListener(ev, () => hold(b.dataset.dir, false));
});
const KEYS = { ArrowUp: '0,-1', ArrowDown: '0,1', ArrowLeft: '-1,0', ArrowRight: '1,0', w: '0,-1', s: '0,1', a: '-1,0', d: '1,0' };
function typing(e) { return /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName); }
addEventListener('keydown', (e) => { if (KEYS[e.key] && !typing(e)) { e.preventDefault(); if (!e.repeat) hold(KEYS[e.key], true); } });
addEventListener('keyup', (e) => { if (KEYS[e.key]) hold(KEYS[e.key], false); });
addEventListener('blur', () => { [...held].forEach((d) => hold(d, false)); });

connect();
