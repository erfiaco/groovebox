import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Backing Player</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:#0d0d0d;color:#eee;
  font-family:-apple-system,system-ui,sans-serif;
  display:flex;flex-direction:column;align-items:center;
  min-height:100vh;padding:28px 16px;gap:18px;
}
#conn{
  position:fixed;top:14px;right:14px;
  width:10px;height:10px;border-radius:50%;
  background:#333;transition:background .3s;
}
#conn.ok{background:#4caf50}
#track{font-size:1.25em;font-weight:600;text-align:center;color:#fff;min-height:1.5em}
#meta{font-size:.88em;color:#777;min-height:1.2em}
#beat-wrap{
  margin:12px 0;
  width:180px;height:180px;
  display:flex;align-items:center;justify-content:center;
}
#beat{
  width:140px;height:140px;border-radius:50%;
  background:#1a1a1a;
  transition:background .04s,box-shadow .04s;
}
#beat.accent{
  background:#ff5722;
  box-shadow:0 0 50px 14px rgba(255,87,34,.5);
}
#beat.pulse{
  background:#1565c0;
  box-shadow:0 0 35px 10px rgba(21,101,192,.4);
}
#state-badge{
  padding:9px 28px;border-radius:28px;
  font-size:1em;font-weight:700;letter-spacing:.1em;
  background:#222;color:#fff;
  transition:background .3s;
  min-width:160px;text-align:center;
}
#bar-info{font-size:.9em;color:#666;min-height:1.2em}
#file-list{
  width:100%;max-width:420px;
  border-radius:12px;
  overflow:hidden;
  background:#111;
  display:none;
}
#file-list.visible{display:block}
.fl-dir-label{
  font-size:.75em;color:#555;letter-spacing:.06em;
  padding:8px 14px;border-bottom:1px solid #1a1a1a;
}
.fl-item{
  padding:13px 16px;
  border-bottom:1px solid #1a1a1a;
  font-size:.9em;color:#999;
}
.fl-item:last-child{border-bottom:none}
.fl-item.sel{background:#102840;color:#7ec8ff;font-weight:700}
.fl-wav::before{content:'\\266A  '}
.fl-dir-item{color:#ffa726}
.fl-dir-item::before{content:'\\25B8  ';color:#ffa726}
.fl-up{color:#555;font-style:italic}
.fl-up::before{content:'\\21A9  '}
</style>
</head>
<body>
<div id="conn"></div>
<div id="track">—</div>
<div id="meta"></div>
<div id="beat-wrap"><div id="beat"></div></div>
<div id="state-badge">IDLE</div>
<div id="bar-info"></div>
<div id="file-list"></div>
<script>
const beatEl     = document.getElementById('beat');
const stateEl    = document.getElementById('state-badge');
const trackEl    = document.getElementById('track');
const metaEl     = document.getElementById('meta');
const barEl      = document.getElementById('bar-info');
const connEl     = document.getElementById('conn');
const fileListEl = document.getElementById('file-list');

const STATE_BG = {
  IDLE:'#222', COUNTDOWN:'#bf360c',
  PLAYING:'#1b5e20', RECORDING:'#b71c1c', LOOPING:'#4a148c', CODA:'#0d47a1',
};

// ── Flash visual ──────────────────────────────────────────────────────────
let _beatTimer = null;
function flash(isAccent) {
  beatEl.className = isAccent ? 'accent' : 'pulse';
  clearTimeout(_beatTimer);
  _beatTimer = setTimeout(() => { beatEl.className = ''; }, 120);
}

// ── AudioContext look-ahead scheduler ─────────────────────────────────────
// SSE beats have 10-100ms of variable jitter from the network/event loop.
// Instead of flashing directly on SSE arrival, we run a local scheduler
// using AudioContext.currentTime (hardware clock, sub-ms precision).
// SSE beats are used only for gentle phase correction.
let _ctx          = null;
let _interval     = 0;       // seconds per beat
let _bpb          = 4;
let _nextTime     = 0;       // next beat time in audioCtx.currentTime
let _nextBIB      = 1;       // next beat-in-bar (1-based)
let _flashQ       = [];
let _schedTimer   = null;
let _rafId        = null;
let _curBpm       = 0;
let _pendingStart = null;    // {bpm, bpb} — waiting for AudioContext unlock (iOS)

const LOOKAHEAD_S = 0.1;
const TICK_MS     = 25;

function _getCtx() {
  if (!_ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (AC) _ctx = new AC();
  }
  if (_ctx && _ctx.state === 'suspended') _ctx.resume();
  return _ctx;
}

function _shouldFlash(bib, bpb) {
  return bpb === 4 ? (bib === 1 || bib === 3) : bib === 1;
}

function _startScheduler(bpm, bpb) {
  _stopScheduler();
  _getCtx();
  if (!_ctx || _ctx.state !== 'running') {
    _pendingStart = { bpm: bpm, bpb: bpb };
    return;
  }
  _interval = 60.0 / bpm;
  _bpb      = bpb;
  _nextBIB  = 1;
  _nextTime = _ctx.currentTime + 0.05;
  _flashQ   = [];
  _schedTimer = setInterval(_tick, TICK_MS);
  _raf();
}

function _stopScheduler() {
  if (_schedTimer)  { clearInterval(_schedTimer);        _schedTimer   = null; }
  if (_rafId)       { cancelAnimationFrame(_rafId);      _rafId        = null; }
  _flashQ       = [];
  _interval     = 0;
  _curBpm       = 0;
  _pendingStart = null;
}

function _tick() {
  if (!_ctx || !_interval || _ctx.state !== 'running') return;
  const deadline = _ctx.currentTime + LOOKAHEAD_S;
  while (_nextTime < deadline) {
    if (_shouldFlash(_nextBIB, _bpb))
      _flashQ.push({ time: _nextTime, isAccent: _nextBIB === 1 });
    _nextTime += _interval;
    _nextBIB = (_nextBIB % _bpb) + 1;
  }
}

function _syncPhase(beatInBar, isAccent) {
  if (!_ctx || _ctx.state !== 'running' || !_interval) {
    // AudioContext not running yet: flash directly from SSE (fallback)
    flash(isAccent);
    return;
  }
  // SSE arrived slightly late — nudge nextTime 15% toward true next beat
  _nextTime += (_ctx.currentTime + _interval - _nextTime) * 0.15;
  _nextBIB   = (beatInBar % _bpb) + 1;
  // Drop events already in the past
  _flashQ = _flashQ.filter(function(e) { return e.time > _ctx.currentTime + 0.02; });
}

function _raf() {
  _rafId = requestAnimationFrame(function frame() {
    if (!_interval) { _rafId = null; return; }
    if (_ctx && _ctx.state === 'running') {
      const now = _ctx.currentTime;
      while (_flashQ.length && _flashQ[0].time <= now)
        flash(_flashQ.shift().isAccent);
    }
    _rafId = requestAnimationFrame(frame);
  });
}

// Unlock AudioContext on first user gesture (required by iOS Safari)
function _unlock() {
  if (_ctx && _ctx.state === 'suspended') {
    _ctx.resume().then(function() {
      if (_pendingStart) {
        _startScheduler(_pendingStart.bpm, _pendingStart.bpb);
        _pendingStart = null;
      }
    });
  } else if (!_ctx && _pendingStart) {
    _startScheduler(_pendingStart.bpm, _pendingStart.bpb);
    _pendingStart = null;
  }
}
document.addEventListener('touchstart', _unlock, { passive: true });
document.addEventListener('click', _unlock);

// ── File list ─────────────────────────────────────────────────────────────
// Virtual window — renders only VISIBLE items centred on the selection,
// mirroring the scroll_offset logic in boot_menu.py.
var VISIBLE = 5;
function renderList(sel) {
  var total = sel.items.length;
  var idx   = sel.idx;

  var wStart = idx - Math.floor(VISIBLE / 2);
  if (wStart < 0) wStart = 0;
  if (wStart + VISIBLE > total) wStart = Math.max(0, total - VISIBLE);
  var wEnd = Math.min(wStart + VISIBLE, total);

  var hasAbove = wStart > 0;
  var hasBelow = wEnd < total;

  var html = '<div class="fl-dir-label">'
    + (hasAbove ? '▲ ' : '')
    + sel.dir
    + (hasBelow ? ' ▼' : '')
    + '<span style="float:right">' + (idx + 1) + '/' + total + '</span>'
    + '</div>';

  for (var i = wStart; i < wEnd; i++) {
    var item  = sel.items[i];
    var cls   = '';
    var label = item.name;
    if (item.kind === 'wav') {
      cls   = 'fl-wav';
      label = item.name.replace(/_/g,' ').replace(/\.wav$/i,'');
    } else if (item.kind === 'dir') {
      cls = 'fl-dir-item';
    } else if (item.kind === 'up') {
      cls = 'fl-up';
    }
    var active = (i === idx) ? ' sel' : '';
    html += '<div class="fl-item ' + cls + active + '">' + label + '</div>';
  }

  fileListEl.innerHTML = html;
  fileListEl.className = 'visible';
}

// ── SSE ───────────────────────────────────────────────────────────────────
function connect() {
  const es = new EventSource('/events');
  es.onopen  = () => connEl.className = 'ok';
  es.onerror = () => {
    connEl.className = '';
    es.close();
    setTimeout(connect, 2000);
  };
  es.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.type === 'beat') {
      _syncPhase(d.beat_in_bar, d.is_accent);
    } else if (d.type === 'state') {
      stateEl.textContent      = d.state;
      stateEl.style.background = STATE_BG[d.state] || '#222';
      trackEl.textContent      = d.track ? d.track.replace(/_/g,' ') : '—';
      metaEl.textContent       = d.tempo ? d.tempo + ' BPM  ·  ' + d.time_sig : '';
      var barText = d.bar > 0 ? 'Bar ' + d.bar + ' / ' + d.total_bars : '';
      if (d.last_rep) barText += '  · → CODA';
      barEl.textContent = barText;
      const bpm = d.tempo || 0;
      const bpb = d.time_sig ? (parseInt(d.time_sig) || 4) : 4;
      if (!bpm || d.state === 'IDLE') {
        _stopScheduler();
      } else if (bpm !== _curBpm) {
        _curBpm = bpm;
        _startScheduler(bpm, bpb);
      }
      if (d.selection) renderList(d.selection);
      else             fileListEl.className = '';
    }
  };
}
connect();
</script>
</body>
</html>
"""


class WebServer:

    def __init__(self, port=8080):
        self._clients = []
        self._lock    = threading.Lock()

        server = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/events':
                    server._sse(self)
                else:
                    server._html(self)

            def log_message(self, *_):
                pass

        self._httpd = ThreadingHTTPServer(('', port), _Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        print(f'[Web] http://0.0.0.0:{port}')

    # ── Public ───────────────────────────────────────────────────────────

    def push(self, data: dict):
        msg = ('data: ' + json.dumps(data) + '\n\n').encode()
        with self._lock:
            dead = []
            for q in self._clients:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._clients.remove(q)

    # ── Handlers ─────────────────────────────────────────────────────────

    def _sse(self, req):
        req.send_response(200)
        req.send_header('Content-Type', 'text/event-stream')
        req.send_header('Cache-Control', 'no-cache')
        req.send_header('Access-Control-Allow-Origin', '*')
        req.end_headers()

        q = queue.Queue(maxsize=20)
        with self._lock:
            self._clients.append(q)

        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                    req.wfile.write(msg)
                    req.wfile.flush()
                except queue.Empty:
                    req.wfile.write(b': keepalive\n\n')
                    req.wfile.flush()
        except Exception:
            pass
        finally:
            with self._lock:
                try:
                    self._clients.remove(q)
                except ValueError:
                    pass

    def _html(self, req):
        body = _HTML.encode('utf-8')
        req.send_response(200)
        req.send_header('Content-Type', 'text/html; charset=utf-8')
        req.send_header('Content-Length', len(body))
        req.end_headers()
        req.wfile.write(body)
