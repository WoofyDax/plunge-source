"""Production wiring: default addresses, health endpoints, the generated website and the deploy files."""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
for k in ("PLUNGE_HUB", "PLUNGE_LOBBY", "PLUNGE_UPDATE_URL"):
    os.environ.pop(k, None)
from core import hub, lobby, safety, updates, hub_server, lobby_server

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


check("hub default is the https hub address", hub.HUB_URL == "https://hub.plungevr.com")
check("lobby default is the https lobby address", lobby.LOBBY_URL == "https://lobby.plungevr.com")
check("update default is on the main site", updates.DEFAULT_UPDATE_URL == "https://plungevr.com/latest.json")
check("all defaults pass the https rule", all(safety.require_secure_url(u) for u in (hub.HUB_URL, lobby.LOBBY_URL, updates.DEFAULT_UPDATE_URL)))

for name, mod in (("hub", hub_server), ("lobby", lobby_server)):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = json.load(urllib.request.urlopen("http://127.0.0.1:%d/health" % srv.server_address[1], timeout=5))
        check("%s /health answers" % name, r == {"ok": True, "service": name})
    finally:
        srv.shutdown()
        srv.server_close()

out = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "build_site.py")], capture_output=True, text=True)
site = ROOT / "site"
check("the website builds", out.returncode == 0 and (site / "index.html").is_file())
import hashlib as _hl
_fake = Path(tempfile.mkdtemp()) / "PlungeSetup-9.9.9.exe"
_fake.write_bytes(b"MZ" + b"x" * 5000)
_withdl = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "build_site.py"), "--installer", str(_fake)], capture_output=True, text=True)
_dl = (site / "download" / "index.html").read_text(encoding="utf-8")
_latest = json.loads((site / "latest.json").read_text(encoding="utf-8"))
check("an installer is copied into the site and linked on the download page and home page", _withdl.returncode == 0 and (site / "download" / _fake.name).read_bytes() == _fake.read_bytes()
      and "https://plungevr.com/download/PlungeSetup-9.9.9.exe" in _dl and "https://plungevr.com/download/PlungeSetup-9.9.9.exe" in (site / "index.html").read_text(encoding="utf-8"))
check("the page shows its SHA-256 and latest.json carries it", _hl.sha256(_fake.read_bytes()).hexdigest() in _dl and _latest.get("sha256") == _hl.sha256(_fake.read_bytes()).hexdigest() and _latest.get("size") == _fake.stat().st_size)
subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "build_site.py")], capture_output=True, text=True)   # back to the plain site for the rest of the checks

pages = [p for p in site.rglob("*.html")]
check("every page exists (home, download, credits, account, invite, five legal pages)", len(pages) == 10)
import re as _re
_scripts = {p.relative_to(site).as_posix(): _re.findall(r"<script[^>]*>", p.read_text(encoding="utf-8").lower()) for p in pages}
check("only the home, account and invite pages have scripts: same-site modules, nothing inline", sorted(k for k, v in _scripts.items() if v) == ["account/index.html", "index.html", "join/index.html"]
      and _scripts["index.html"] == ['<script type="module" src="/js/hero.js">', '<script type="module" src="/js/scroll.js">', '<script type="module" src="/js/nav.js">']
      and _scripts["account/index.html"] == ['<script type="module" src="/js/account.js">'] and _scripts["join/index.html"] == ['<script src="/js/join.js">'])
_hdr = (site / "_headers").read_text()
check("the site may only connect to the hub, nowhere else", "connect-src https://hub.plungevr.com;" in _hdr and _hdr.count("connect-src") == 1)
_acct = (ROOT / "web" / "account.js").read_text(encoding="utf-8")
check("the account page never builds HTML from text (no innerHTML)", "innerHTML" not in _acct and "insertAdjacentHTML" not in _acct and ("document." + "write") not in _acct and ("ev" + "al(") not in _acct)
check("the browser sign-in sends cookies and our header, and never stores a token itself", 'credentials: "include"' in _acct and "X-Plunge-Client" in _acct and "localStorage" not in _acct and "sessionStorage" not in _acct)
check("the account page is kept out of search results", 'name="robots" content="noindex"' in (site / "account" / "index.html").read_text(encoding="utf-8"))
_credits = json.loads((ROOT / "web" / "credits.json").read_text(encoding="utf-8-sig"))
_imgs = sorted(p.stem for p in (site / "img").glob("*.jpg"))
check("every screenshot on the site has a credit with a licence and a source page", _imgs == sorted(c["slug"] for c in _credits)
      and all(c["license"] and c["page"].startswith("https://commons.wikimedia.org/") and c["artist"] for c in _credits))
check("only open licences are used for screenshots", all(any(k in c["license"] for k in ("CC0", "CC BY", "GPL", "Public domain")) for c in _credits))
check("the credits page lists every screenshot", all(c["game"] in (site / "credits" / "index.html").read_text(encoding="utf-8") for c in _credits))
_hero = (ROOT / "web" / "hero.js").read_text(encoding="utf-8")
_scroll = (ROOT / "web" / "scroll.js").read_text(encoding="utf-8")
_home0 = (site / "index.html").read_text(encoding="utf-8")
check("the page is complete without scripts: content is only hidden once scroll.js adds the 'js' class", ".js [data-reveal]" in _home0 and 'classList.add("js")' in _scroll)
check("the scroll lock always has a way out: skip button, a timeout, and a failure path", "data-skip" in _home0 and "8000" in _hero and "unlock(); });" in _hero)
check("scrolling up from the top replays the animation backwards, and needs a fresh gesture so momentum cannot trigger it", "function replay" in _hero and "gap > 140" in _hero and "atTopSince > 350" in _hero)
check("the lock is not applied to people who prefer reduced motion", "!reduced && scrollY < 40" in _hero)
_home = (site / "index.html").read_text(encoding="utf-8")
check("the home page loads nothing from other sites", not _re.search(r'(src|href)="https?://', _home) and "@import" not in _home)
check("the 3D library ships with its licence", (site / "vendor" / "three.module.min.js").is_file() and (site / "vendor" / "three.LICENSE").is_file())
check("the CSP allows only this site's scripts", "script-src 'self'" in (site / "_headers").read_text() and "unsafe-eval" not in (site / "_headers").read_text())
latest = json.loads((site / "latest.json").read_text())
check("latest.json passes the app's own update check rules", updates._same_site(latest["url"], updates.DEFAULT_UPDATE_URL) and latest["url"].startswith("https://"))
check("the site sets security headers for both host types", "Content-Security-Policy" in (site / "_headers").read_text() and "Strict-Transport-Security" in (site / "vercel.json").read_text())
sys.path.insert(0, str(ROOT / "tools"))
import build_site
evil = build_site.md("# T\n<script>alert(1)</script> [x](javascript:alert(1)) <img src=x onerror=alert(1)>")
check("document text is HTML-escaped and javascript: links are not links", "<script" not in evil and "<img" not in evil and "<a href" not in evil)
bad = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "build_site.py"), "--download-url", "http://x"], capture_output=True, text=True)
check("an http download link is refused", bad.returncode != 0)
compose = (ROOT / "deploy" / "docker-compose.yml").read_text()
check("compose checks the health of hub and lobby", compose.count("healthcheck:") == 2 and "/health" in compose)
env = (ROOT / "deploy" / ".env.example").read_text()
check(".env.example uses the real subdomains and no secret", "hub.plungevr.com" in env and "lobby.plungevr.com" in env and env.strip().endswith("PLUNGE_HUB_ADMIN="))
check("shell scripts use Unix line endings", all(b"\r" not in (ROOT / "deploy" / f).read_bytes() for f in ("setup-server.sh", "backup.sh")))
check("the real .env is never committed", ".env" in (ROOT / ".gitignore").read_text())
sys.exit(1 if fails else 0)
