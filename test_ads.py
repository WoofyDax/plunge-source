"""Tests for sponsored cards. Temp dirs only; the browser launch and impression ping are stubbed."""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(tmp / "local")
os.environ.pop("PLUNGE_ADS_URL", None)
sys.path.insert(0, str(Path(__file__).parent))
from core import ads, paths  # noqa: E402

paths.ensure()
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


GOOD = {"id": "acme-1", "title": "Acme VR Headset", "body": "20% off for Plunge players", "image": "https://cdn.acme.test/a.jpg",
        "link": "https://acme.test/deal", "cta": "Shop", "advertiser": "Acme", "viewUrl": "https://acme.test/view?c=1"}

# ---- normalize ------------------------------------------------------------------------------
n = ads.normalize({"ad": GOOD})
check("valid ad accepted (wrapped)", n and n["title"] == "Acme VR Headset")
check("valid ad accepted (bare)", ads.normalize(GOOD)["id"] == "acme-1")
check("javascript: link rejected", ads.normalize({**GOOD, "link": "javascript:alert(1)"}) is None)
check("http link rejected", ads.normalize({**GOOD, "link": "http://acme.test"}) is None)
check("file: link rejected", ads.normalize({**GOOD, "link": "file:///C:/Windows/system32/calc.exe"}) is None)
check("missing title rejected", ads.normalize({**GOOD, "title": " "}) is None)
check("non-https image dropped, ad kept", ads.normalize({**GOOD, "image": "http://x/y.jpg"})["image"] is None)
check("non-https viewUrl dropped", ads.normalize({**GOOD, "viewUrl": "ftp://x"})["viewUrl"] is None)
check("text is length-capped", len(ads.normalize({**GOOD, "title": "t" * 500, "body": "b" * 500})["title"]) == 80)
check("garbage is safe", ads.normalize("nope") is None and ads.normalize(None) is None and ads.normalize([]) is None)
check("html in text stays text (UI uses textContent)", "<script>" in ads.normalize({**GOOD, "title": "<script>x</script>"})["title"])
check("UI copy hides viewUrl", "viewUrl" not in ads.public(n))

# ---- source + caching -----------------------------------------------------------------------
HITS = []
BODY = {"v": json.dumps({"ad": GOOD}).encode()}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        HITS.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(BODY["v"])


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d/ad.json" % srv.server_address[1]

check("dormant with no source", ads.current() is None and ads.status()["configured"] is False)
(paths.DATA / "ads.json").write_text(json.dumps({"url": URL}))
check("source read from ads.json", ads.status()["configured"] and ads.status()["host"].startswith("127.0.0.1"))
a = ads.current()
check("ad fetched from the source", a and a["id"] == "acme-1" and len(HITS) == 1)
ads.current()
check("ad is cached (no second request)", len(HITS) == 1)
os.environ["PLUNGE_ADS_URL"] = URL + "?x=1"
check("env var overrides ads.json", ads.source_url().endswith("?x=1"))
del os.environ["PLUNGE_ADS_URL"]

ads.set_enabled(False)
check("disabled by the player -> no ad", ads.current() is None and ads.status()["enabled"] is False)
ads.set_enabled(True)
check("re-enabled -> ad again", ads.current() is not None)

ads._CACHE.update(ad=None, t=0)
BODY["v"] = b"<html>not json</html>"
check("bad source response -> no ad, no crash", ads.current() is None)
ads._CACHE.update(ad=None, t=0)
BODY["v"] = json.dumps({"ad": {**GOOD, "link": "javascript:1"}}).encode()
check("unsafe ad from source -> no ad", ads.current() is None)
ads._CACHE.update(ad=None, t=0)
os.environ["PLUNGE_ADS_URL"] = "http://127.0.0.1:1/none"
check("unreachable source -> no ad, no crash", ads.current() is None)
del os.environ["PLUNGE_ADS_URL"]

# a failure is retried after RETRY seconds, not cached for the full TTL
ads._CACHE.update(ad=None, t=0)
BODY["v"] = b"garbage"
before = len(HITS)
ads.current(); ads.current()
check("failed fetch is not hammered (cached briefly)", len(HITS) == before + 1)
BODY["v"] = json.dumps({"ad": GOOD}).encode()
ads._CACHE["t"] -= ads.RETRY + 1
check("failed fetch is retried after the short delay", ads.current() is not None)

# ---- click + impression (stubbed) -----------------------------------------------------------
BODY["v"] = json.dumps({"ad": GOOD}).encode()
ads._CACHE.update(ad=None, t=0)
ads.current()
OPENED, PINGED = [], []
ads.os.startfile = lambda u: OPENED.append(u)
real_urlopen = ads.urllib.request.urlopen
ads.urllib.request.urlopen = lambda req, timeout=5: (PINGED.append(req.full_url if hasattr(req, "full_url") else req), type("R", (), {"read": lambda s, n=-1: b""})())[1]
ads.seen("acme-1")
ads.seen("acme-1")
check("impression pinged exactly once per session", PINGED == ["https://acme.test/view?c=1"])
check("impression for an unknown ad does nothing", ads.seen("other") == {"ok": False})
ads.urllib.request.urlopen = real_urlopen
ads.click("acme-1")
check("click opens the ad's own link in the browser", OPENED == ["https://acme.test/deal"])
try:
    ads.click("not-the-current-ad")
    check("UI cannot open a URL of its choosing", False)
except ValueError:
    check("UI cannot open a URL of its choosing", True)

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
