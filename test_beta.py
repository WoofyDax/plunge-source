"""Tests: the unlisted beta download on the hub (installer for testers). Temp dirs only."""
import hashlib
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(tmp / "local")
os.environ["APPDATA"] = str(tmp / "roam")
sys.path.insert(0, str(Path(__file__).parent))
from core import hub_server, paths  # noqa: E402

paths.ensure()
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


hub_server.STATE.update(dir=tmp / "hubdata", admin="a" * 40, require_auth=True)
hub_server.STATE["dir"].mkdir(parents=True, exist_ok=True)
srv = ThreadingHTTPServer(("127.0.0.1", 0), hub_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]
TOKEN = "k3Jx9-Qm2_vB7nLw4TzR8s"
DATA = os.urandom(300_000) + b"MZ"


def call(method, path, data=None, headers=None):
    for attempt in range(4):                       # Windows loopback occasionally resets a connection that carries a few hundred KB; a retry is the harness's problem, not the hub's
        req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)
        except ConnectionResetError:
            if attempt == 3:
                raise


st, _, _ = call("POST", "/admin/beta/%s/PlungeSetup-0.9.0.exe" % TOKEN, DATA)
check("putting a file needs the admin key", st == 403)
st, _, _ = call("POST", "/admin/beta/%s/PlungeSetup-0.9.0.exe" % TOKEN, DATA, {"X-Admin": "wrong"})
check("a wrong admin key is refused", st == 403)
for bad_path, why in (("/admin/beta/short/PlungeSetup.exe", "a short token"), ("/admin/beta/%s/evil.sh" % TOKEN, "a script name"), ("/admin/beta/%s/..%%2Fx.exe" % TOKEN, "a path in the name"),
                      ("/admin/beta/%s/a%%20b.exe" % TOKEN, "a space")):
    st, _, _ = call("POST", bad_path, DATA, {"X-Admin": "a" * 40})
    check("refused: " + why, st == 400)
st, body, _ = call("POST", "/admin/beta/%s/PlungeSetup-0.9.0.exe" % TOKEN, DATA, {"X-Admin": "a" * 40})
r = json.loads(body)
check("the admin can put an installer on the hub, and gets its SHA-256", st == 200 and r["size"] == len(DATA) and r["sha256"] == hashlib.sha256(DATA).hexdigest())

st, body, h = call("GET", "/beta/%s/PlungeSetup-0.9.0.exe" % TOKEN)
check("the file downloads byte for byte with attachment, noindex and a length", st == 200 and body == DATA and "attachment" in h["Content-Disposition"] and "noindex" in h["X-Robots-Tag"] and int(h["Content-Length"]) == len(DATA) and h["Accept-Ranges"] == "bytes")
st, body, h = call("GET", "/beta/%s/PlungeSetup-0.9.0.exe" % TOKEN, headers={"Range": "bytes=1000-"})
check("an interrupted download can resume (Range)", st == 206 and body == DATA[1000:] and h["Content-Range"] == "bytes 1000-%d/%d" % (len(DATA) - 1, len(DATA)))
st, body, h = call("GET", "/beta/%s/PlungeSetup-0.9.0.exe" % TOKEN, headers={"Range": "bytes=10-19"})
check("a middle range works", st == 206 and body == DATA[10:20])
st, _, h = call("GET", "/beta/%s/PlungeSetup-0.9.0.exe" % TOKEN, headers={"Range": "bytes=99999999-"})
check("a range past the end is refused properly", st == 416)

st, body, h = call("GET", "/beta/%s/" % TOKEN)
page = body.decode()
check("the page shows the download link, the SHA-256 and the unsigned notice, and is not indexable", st == 200 and "PlungeSetup-0.9.0.exe" in page and hashlib.sha256(DATA).hexdigest() in page and "Run anyway" in page and "noindex" in h["X-Robots-Tag"] and "default-src 'none'" in h["Content-Security-Policy"])
check("the page is also reachable without the trailing slash", call("GET", "/beta/%s" % TOKEN)[0] == 200)

check("a wrong token finds nothing", call("GET", "/beta/%s/PlungeSetup-0.9.0.exe" % ("x" * 22))[0] == 404 and call("GET", "/beta/%s/" % ("x" * 22))[0] == 404)
check("a short or odd token finds nothing", call("GET", "/beta/abc/")[0] == 404 and call("GET", "/beta/")[0] == 404 and call("GET", "/beta")[0] == 404)
check("path tricks find nothing", all(call("GET", p)[0] in (404, 400) for p in ("/beta/%s/..%%2F..%%2Findex.json" % TOKEN, "/beta/%s/../PlungeSetup-0.9.0.exe" % TOKEN, "/beta/%s/%%2e%%2e/x.exe" % TOKEN)))
(hub_server.STATE["dir"] / "index.json").write_text("{}")
check("the hub's own data files can never be fetched this way", call("GET", "/beta/%s/index.json" % TOKEN)[0] == 404)
check("nothing about it appears in the public build list", b"Plunge" not in call("GET", "/profiles")[1] and call("GET", "/profiles")[0] == 200)

hub_server.LIMITS["beta"] = (3, 3600)
hub_server.LIMITER.__init__() if hasattr(hub_server.LIMITER, "__init__") else None
codes = [call("GET", "/beta/%s/PlungeSetup-0.9.0.exe" % TOKEN)[0] for _ in range(6)]
check("downloads are rate limited per address", 429 in codes)

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
