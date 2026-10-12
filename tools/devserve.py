"""DEV ONLY: serve the UI in a normal browser with the real Python backend behind a /rpc endpoint,
so the UI can be clicked through and screenshotted. The shipped app does not use this (no ports)."""
import json
import mimetypes
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import app  # noqa: E402
from core import paths  # noqa: E402

paths.ensure()
BRIDGE = app.Bridge()
UI = ROOT / "ui"
SHIM = """<script>
window.pywebview = { api: new Proxy({}, { get: (_, name) => async (...args) => {
  const r = await fetch('/rpc/' + name, { method: 'POST', body: JSON.stringify(args) }); return r.json(); } }) };
addEventListener('DOMContentLoaded', () => setTimeout(() => window.dispatchEvent(new Event('pywebviewready')), 50));
</script>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        rel = "index.html" if self.path in ("/", "") else self.path.split("?")[0].lstrip("/")
        f = (UI / rel).resolve()
        if not f.is_file() or UI.resolve() not in f.parents:
            self.send_error(404)
            return
        data = f.read_bytes()
        if rel == "index.html":
            data = re.sub(rb'<meta http-equiv="Content-Security-Policy"[^>]*>', b"", data)     # dev only: the shim needs fetch()
            data = data.replace(b'<script src="app.js"></script>', SHIM.encode() + b'<script src="app.js"></script>')
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        name = self.path.rsplit("/", 1)[-1]
        n = int(self.headers.get("Content-Length") or 0)
        args = json.loads(self.rfile.read(n) or b"[]")
        fn = getattr(BRIDGE, name, None) if not name.startswith("_") else None
        out = fn(*args) if fn else {"error": "no such method " + name}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print("dev UI on http://127.0.0.1:7788")
    ThreadingHTTPServer(("127.0.0.1", 7788), H).serve_forever()
