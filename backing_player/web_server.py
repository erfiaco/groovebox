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
  IDLE:      '#222',
  ARMED:     '#4a2c00',
  COUNTDOWN: '#bf360c',
  PLAYING:   '#1b5e20',
  RECORDING: '#b71c1c',
  LOOPING:   '#4a148c',
  CODA:      '#0d47a1',
};

let beatTimer = null;

function flash(isAccent) {
  beatEl.className = isAccent ? 'accent' : 'pulse';
  clearTimeout(beatTimer);
  beatTimer = setTimeout(() => { beatEl.className = ''; }, 120);
}

function renderList(sel) {
  let html = '<div class="fl-dir-label">' + sel.dir + '</div>';
  sel.items.forEach(function(item, i) {
    const active = i === sel.idx ? ' sel' : '';
    var cls = '', label = item.name;
    if (item.kind === 'wav') {
      cls = 'fl-wav';
      label = item.name.replace(/_/g, ' ').replace(/\\.wav$/i, '');
    } else if (item.kind === 'dir') {
      cls = 'fl-dir-item';
    } else if (item.kind === 'up') {
      cls = 'fl-up';
    }
    html += '<div class="fl-item ' + cls + active + '">' + label + '</div>';
  });
  fileListEl.innerHTML = html;
  fileListEl.className = 'visible';
  var selEl = fileListEl.querySelector('.sel');
  if (selEl) selEl.scrollIntoView({block: 'nearest'});
}

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
      flash(d.is_accent);
    } else if (d.type === 'state') {
      stateEl.textContent = d.state;
      stateEl.style.background = STATE_BG[d.state] || '#222';
      trackEl.textContent = d.track ? d.track.replace(/_/g,' ') : '—';
      metaEl.textContent  = d.tempo ? d.tempo + ' BPM  ·  ' + d.time_sig : '';
      barEl.textContent   = d.bar > 0 ? 'Bar ' + d.bar + ' / ' + d.total_bars : '';
      if (d.selection) {
        renderList(d.selection);
      } else {
        fileListEl.className = '';
      }
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
