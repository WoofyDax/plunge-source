"""Production-hardening tests: each one tries to break a defence. Temp dirs only; nothing real is touched or launched."""
import io
import json
import os
import re
import stat
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(tmp / "local")
os.environ["APPDATA"] = str(tmp / "roam")
os.environ.pop("PLUNGE_UPDATE_URL", None)
os.environ["PLUNGE_TRUST_PROXY"] = "1"
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import app  # noqa: E402
from core import api, hub, hub_server, lobby, lobby_server, log, paths, recipe, safety, settings, updates  # noqa: E402

paths.ensure()
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


def raises(fn, *exc):
    try:
        fn()
        return False
    except exc or Exception:
        return True


# ---- addresses (they end up in launch arguments and config files) ----------------------------------------------------
GOOD = ["10.0.0.5", "10.0.0.5:7777", "my-host.example.com", "my-host.example.com:25565", "a", "[::1]", "[::1]:7777", "[2001:db8::1]:80", "Host1:65535", "1:1"]
BAD = ["", " ", "host name", "host\n", "host\r\nexec evil", "a;b", "a&b", "a|b", "+connect evil", "-flag", "--x=1", "1.2.3.4:0", "1.2.3.4:65536", "1.2.3.4:99999",
       "host:port", "host:1:2", "../x", "a..b", "a\"b", "a'b", "a b:1", "$(calc)", "`calc`", "a%20b", "a\\b", "a/b", "http://x", "x" * 300, "[::1", "::1]:1", None, 5, "host:\n", "\u202ehost"]
check("every plain address is accepted", all(safety.valid_address(a) for a in GOOD))
bad_ok = [b for b in BAD if safety.valid_address(b)]
check("nothing that could carry a command or newline is accepted (%d tried)" % len(BAD), not bad_ok)
if bad_ok:
    print("   accepted:", bad_ok)

# ---- secure URLs -----------------------------------------------------------------------------------------------------
check("https is accepted", safety.require_secure_url("https://hub.example.com") == "https://hub.example.com")
check("http to this same PC is accepted", all(safety.require_secure_url(u) for u in ("http://127.0.0.1:8788", "http://localhost:8787", "http://[::1]:1")))
check("http to another machine is refused", all(raises(lambda u=u: safety.require_secure_url(u), ValueError) for u in ("http://hub.example.com", "http://10.0.0.5", "http://127.0.0.1.evil.com", "ftp://x", "file:///x", "//x", "")))

# ---- clean_text ------------------------------------------------------------------------------------------------------
check("control and direction-override characters are removed", safety.clean_text("a\u202eb\u200bc\x00d\n\te", 50) == "abcd e")
check("text is capped", len(safety.clean_text("x" * 500, 40)) == 40 and safety.clean_text(None, 5) == "")

# ---- rate limiter ----------------------------------------------------------------------------------------------------
rl = safety.RateLimiter()
check("limiter allows up to the limit then refuses", [rl.allow("a", 3, 60) for _ in range(5)] == [True, True, True, False, False])
check("limiter keeps keys separate", rl.allow("b", 3, 60))
rl2 = safety.RateLimiter()
rl2.allow("x", 1, 0.2)
time.sleep(0.3)
check("limiter forgets after the window", rl2.allow("x", 1, 0.2))
rl3 = safety.RateLimiter(max_keys=50)
for i in range(500):
    rl3.allow(i, 1, 0.01)
time.sleep(0.05)
rl3.allow("trigger", 1, 0.01)
check("limiter memory stays bounded under a flood", len(rl3.hits) < 500)

# ---- atomic writes ----------------------------------------------------------------------------------------------------
f = tmp / "w" / "data.json"
paths.atomic_write(f, '{"a": 1}')
check("atomic write creates the file", f.read_text() == '{"a": 1}')
real_replace = os.replace
os.replace = lambda *a: (_ for _ in ()).throw(OSError("disk full"))
try:
    paths.atomic_write(f, '{"a": 2}')
    check("a failed write raises", False)
except OSError:
    check("a failed write raises", True)
finally:
    os.replace = real_replace
check("a failed write leaves the old file untouched", f.read_text() == '{"a": 1}')
check("a failed write leaves no stray temp file", [p.name for p in f.parent.iterdir()] == ["data.json"])
settings.set("k", "v")
check("settings still work through atomic writes", settings.get("k") == "v")

# ---- zip safety (hub upload AND app download) ------------------------------------------------------------------------------
BASE = {"schema": 2, "title": "T VR", "tagline": "t", "steamAppId": 1, "engine": "unity", "tier": "native", "author": "me", "license": "MIT", "comfort": "gentle",
        "controls": "motion", "version": "1.0.0", "tested": {"gameVersion": "1", "minutesPlayed": 9, "headset": "q"},
        "recipe": {"runtime": None, "install": [{"from": "files/a.cfg", "to": "{game}/a.cfg"}], "launch": {"mode": "steam"}}}


def make_zip(extra=None, meta=BASE, symlink=None, big=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("plunge.json", json.dumps(meta))
        z.writestr("files/a.cfg", "x=1")
        for n, d in (extra or {}).items():
            z.writestr(n, d)
        if symlink:
            zi = zipfile.ZipInfo(symlink)
            zi.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(zi, "C:/Windows")
        if big:
            z.writestr("files/big.cfg", b"\0" * big)
    return buf.getvalue()


def unpack(data):
    d = tmp / ("u%d" % time.time_ns())
    d.mkdir()
    return hub_server.unpack_checked(data, d)[1]


check("a normal profile unpacks", unpack(make_zip()) is None)
check("a zip bomb (tiny file that unpacks huge) is rejected", "suspicious compression" in (unpack(make_zip(big=50 * 1024 * 1024)) or ""))
check("a symbolic-link entry is rejected", "links are not allowed" in (unpack(make_zip(symlink="files/evil")) or ""))
check("a path escape is rejected", "unsafe path" in (unpack(make_zip(extra={"../evil.txt": "x"})) or ""))
check("an absolute path is rejected", "unsafe path" in (unpack(make_zip(extra={"/abs/evil.txt": "x"})) or ""))
check("a Windows drive path is rejected", "unsafe path" in (unpack(make_zip(extra={"C:/evil.txt": "x"})) or ""))
check("too many files are rejected", "too large" in (unpack(make_zip(extra={"f/%d.txt" % i: "x" for i in range(hub_server.MAX_FILES + 5)})) or ""))
orig = hub_server.MAX_ONE_FILE
hub_server.MAX_ONE_FILE = 1000
check("an oversized single file is rejected", "too large" in (unpack(make_zip(extra={"files/b.cfg": os.urandom(5000)})) or ""))
hub_server.MAX_ONE_FILE = orig

# ---- hub server ------------------------------------------------------------------------------------------------------------
hub_server.STATE["dir"] = tmp / "hub"
hub_server.STATE["admin"] = "s3cret"
hub_server.STATE["require_auth"] = False          # these suites test the hub itself; sign-in rules are tested in test_accounts.py
hub_server.LIMITS.update(read=(1000, 60), upload=(1000, 3600), like=(1000, 60), likeone=(1000, 86400), admin=(1000, 60))
srv = ThreadingHTTPServer(("127.0.0.1", 0), hub_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
hub.HUB_URL = "http://127.0.0.1:%d" % srv.server_address[1]


def raw(method, path, body=None, headers=None, base=None):
    req = urllib.request.Request((base or hub.HUB_URL) + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


pid = hub._req("/profiles", make_zip(meta={**BASE, "title": "Ev\u202eil\x00 title", "author": "a\u200bu"}), "application/zip")["id"]
row = hub.browse("new")[0]
check("titles and authors from uploads are cleaned in listings", row["title"] == "Evil title" and row["author"] == "au")
st, hd, body = raw("GET", "/profiles")
check("hub responses carry security headers", hd.get("X-Content-Type-Options") == "nosniff" and "default-src 'none'" in hd.get("Content-Security-Policy", ""))
st, hd, body = raw("GET", "/profiles/%s/download" % pid)
check("downloads are sent as attachments", "attachment" in hd.get("Content-Disposition", "") and hd.get("Content-Type") == "application/zip")
import socket  # noqa: E402


def raw_socket(request_bytes, port):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(request_bytes)
    first = s.recv(200).split(b"\r\n")[0]
    s.close()
    return first


port = srv.server_address[1]
check("a non-numeric Content-Length gets a 400, not a crash", b" 400 " in raw_socket(b"POST /profiles HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n", port))
check("a negative Content-Length is refused", b" 413 " in raw_socket(b"POST /profiles HTTP/1.1\r\nHost: x\r\nContent-Length: -5\r\n\r\n", port))
check("an enormous Content-Length is refused before reading", b" 413 " in raw_socket(b"POST /profiles HTTP/1.1\r\nHost: x\r\nContent-Length: 99999999999\r\n\r\n", port))
check("the hub still works after those", raw("GET", "/profiles")[0] == 200)
st, _, _ = raw("POST", "/profiles", b"x" * 10, {"Content-Type": "application/zip"})
check("garbage uploads are rejected with 400", st == 400)
check("a path-traversal profile id finds nothing", raw("GET", "/profiles/..%2f..%2fetc/download")[0] == 404)

hub_server.LIMITS["upload"] = (2, 3600)
hub_server.LIMITER.hits.clear()
codes = [raw("POST", "/profiles", make_zip(meta={**BASE, "title": "R%d" % i}), {"Content-Type": "application/zip", "X-Forwarded-For": "9.9.9.9"})[0] for i in range(4)]
check("uploads are rate limited per address", codes[:2] == [200, 200] and codes[2:] == [429, 429])
st, _, _ = raw("POST", "/profiles", make_zip(meta={**BASE, "title": "Other"}), {"Content-Type": "application/zip", "X-Forwarded-For": "8.8.8.8"})
check("another address isn't affected", st == 200)
hub_server.LIMITS["upload"] = (1000, 3600)
hub_server.LIMITS["read"] = (3, 60)
hub_server.LIMITER.hits.clear()
codes = [raw("GET", "/profiles", headers={"X-Forwarded-For": "7.7.7.7"})[0] for _ in range(5)]
check("reads are rate limited", codes == [200, 200, 200, 429, 429])
hub_server.LIMITS["read"] = (1000, 60)
hub_server.LIMITS["likeone"] = (1, 86400)
hub_server.LIMITER.hits.clear()
c = [raw("POST", "/profiles/%s/like" % pid, b"{}", {"X-Forwarded-For": "6.6.6.6"})[0] for _ in range(3)]
check("one like per profile per address per day", c == [200, 429, 429])
check("a different address can like", raw("POST", "/profiles/%s/like" % pid, b"{}", {"X-Forwarded-For": "6.6.6.7"})[0] == 200)
hub_server.LIMITS["admin"] = (3, 60)
hub_server.LIMITER.hits.clear()
c = [raw("POST", "/profiles/%s/feature" % pid, b"{}", {"X-Admin": "wrong", "X-Forwarded-For": "5.5.5.5"})[0] for _ in range(5)]
check("wrong admin tokens are refused and then rate limited", c[:3] == [403, 403, 403] and c[3:] == [429, 429])
hub_server.LIMITS["admin"] = (1000, 60)
hub_server.LIMITER.hits.clear()
old_max = hub_server.MAX_PROFILES
hub_server.MAX_PROFILES = 1
st, _, body = raw("POST", "/profiles", make_zip(meta={**BASE, "title": "Overflow"}), {"Content-Type": "application/zip"})
check("a full hub says so instead of growing forever", st == 507)
hub_server.MAX_PROFILES = old_max

# hub client refuses a dangerous hub
hub_url = hub.HUB_URL
hub.HUB_URL = "http://hub.example.com"
check("the hub client refuses a plain-http hub on another machine", raises(lambda: hub.browse("new"), hub.HubError))
hub.HUB_URL = hub_url
orig_dl = hub.MAX_DOWNLOAD
hub.MAX_DOWNLOAD = 100
check("the hub client refuses an oversized download", raises(lambda: hub._req("/profiles/%s/download" % pid, raw=True), hub.HubError))
hub.MAX_DOWNLOAD = orig_dl

# app-side download re-checks the zip, and leaves no half-extracted profile
bomb_id = "bomb-test-aaa111"
(hub_server.STATE["dir"] / "zips").mkdir(parents=True, exist_ok=True)
(hub_server.STATE["dir"] / "zips" / (bomb_id + ".zip")).write_bytes(make_zip(big=50 * 1024 * 1024))
idx = hub_server._read()
idx[bomb_id] = {"meta": BASE, "downloads": 0, "likes": 0, "created": time.time(), "featured": False}
hub_server._write(idx)
check("the app refuses a hostile zip even if a hub serves it", raises(lambda: hub.get(bomb_id), hub.HubError))
check("...and leaves no half-extracted profile behind", not (paths.PROFILES / bomb_id).exists())

# ---- lobby server and client -------------------------------------------------------------------------------------------------------
lsrv = ThreadingHTTPServer(("127.0.0.1", 0), lobby_server.Handler)
threading.Thread(target=lsrv.serve_forever, daemon=True).start()
lobby.LOBBY_URL = "http://127.0.0.1:%d" % lsrv.server_address[1]
lobby_server.LIMITS.update(read=(1000, 60), create=(1000, 60), join=(1000, 60), other=(1000, 60), guess=(1000, 60))


def lraw(path, body=None, ip="1.1.1.1", method="POST"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(lobby.LOBBY_URL + path, data=data, method=method, headers={"X-Forwarded-For": ip, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


bad_addr = ["a b", "x\ny", "+connect evil", "1.2.3.4:99999", "", "a;b"]
check("the lobby refuses addresses that aren't plain host:port", all(lraw("/lobbies", {"appid": "1", "address": a})[0] == 400 for a in bad_addr))
st, r = lraw("/lobbies", {"appid": "1", "address": "10.0.0.5:7777", "title": "Ti\u202etle\x00", "profile": "p", "maxPlayers": "lots", "public": True})
check("a valid lobby is created, with a cleaned title and a safe default for a garbage max", st == 200 and lraw("/lobbies?appid=1", method="GET")[1]["lobbies"][0]["title"] == "Title"
      and lraw("/lobbies?appid=1", method="GET")[1]["lobbies"][0]["maxPlayers"] == 2)
check("a non-object JSON body doesn't crash the lobby", lraw("/lobbies", [1, 2, 3])[0] == 400)
check("the client refuses an invalid address before sending", raises(lambda: lobby.open_lobby("1", "p", "t", 2, "a b", True), lobby.LobbyError))
check("join codes are validated before use", all(raises(lambda c=c: lobby.resolve(c), lobby.LobbyError) for c in ("../x", "AB", "ABC 12", "ABC?x=1", "A" * 40, "")))
real_call = lobby._call
lobby._call = lambda path, body=None: {"address": "evil host\nexec calc", "appid": "1", "profile": "p"}
check("the client rejects a bad address from a lobby server", raises(lambda: lobby.resolve("ABC234"), lobby.LobbyError))
lobby._call = real_call
lobby_server.LIMITS["guess"] = (3, 60)
lobby_server.LIMITER.hits.clear()
c = [lraw("/lobbies/ZZZZZ%d/join" % i, {}, ip="4.4.4.4")[0] for i in range(6)]
check("guessing join codes is rate limited", c[:3] == [404, 404, 404] and 429 in c[3:])
lobby_server.LIMITS["guess"] = (1000, 60)
lobby_server.LIMITS["create"] = (2, 60)
lobby_server.LIMITER.hits.clear()
c = [lraw("/lobbies", {"appid": "1", "address": "1.1.1.1:1"}, ip="3.3.3.3")[0] for _ in range(4)]
check("creating lobbies is rate limited", c == [200, 200, 429, 429])
lobby_server.LIMITS["create"] = (1000, 60)
code = lraw("/lobbies", {"appid": "9", "address": "2.2.2.2:2", "maxPlayers": 3, "public": False}, ip="2.0.0.1")[1]["code"]
st = [lraw("/lobbies/%s/join" % code, {}, ip="2.0.0.2")[0] for _ in range(5)]
check("one address can't fill a lobby by joining repeatedly", st == [200] * 5 and lraw("/lobbies/%s" % code, method="GET")[1]["players"] == 2)
lobby_server.LIMITS["join"] = (1000, 60)
lob = lobby.LOBBY_URL
lobby.LOBBY_URL = "http://lobby.example.com"
check("the lobby client refuses a plain-http lobby on another machine", raises(lambda: lobby.list_open(), lobby.LobbyError))
lobby.LOBBY_URL = lob

# find_address: only a plain address from the log, and only from allowed folders
game_dir = tmp / "g"
(game_dir / "logs").mkdir(parents=True)
GAME = {"appid": "1", "name": "g", "path": str(game_dir), "exe": None}
(game_dir / "logs" / "latest.log").write_text("x\nHosting at 1.2.3.4:7777 +exec evil\n")
check("find_address returns just the address, not what follows it", lobby.find_address({"log": "{game}/logs/latest.log", "after": "Hosting at "}, GAME, timeout=2) == "1.2.3.4:7777")
(game_dir / "logs" / "latest.log").write_text("Hosting at ;calc\n")
check("find_address ignores a log line with no valid address", lobby.find_address({"log": "{game}/logs/latest.log", "after": "Hosting at "}, GAME, timeout=1.2) is None)
check("find_address refuses a log path outside the allowed folders", all(raises(lambda p=p: lobby.find_address({"log": p, "after": "x"}, GAME, timeout=1), lobby.LobbyError, ValueError, recipe.RecipeError)
                                                                        for p in ("{game}/../x.log", "C:/Windows/win.ini", "{localappdata}/../../x")))

# recipe: addresses go into launch args and a config file
check("joinFile refuses an address with a newline", raises(lambda: recipe.write_join_file({"path": "{game}/net.cfg", "key": "join"}, GAME, "1.2.3.4\nkill=1", "1"), recipe.RecipeError))
check("joinFile refuses a key that could inject a line", all(raises(lambda k=k: recipe.write_join_file({"path": "{game}/net.cfg", "key": k}, GAME, "1.2.3.4", "1"), recipe.RecipeError) for k in ("a\nb", "a=b", "", "x" * 80)))
check("a bad address is refused when joining", raises(lambda: recipe.launch(GAME, {"multiplayer": {"joinArgs": ["+connect", "{address}"]}}, "join", "x y"), recipe.RecipeError))

# ---- the window page (content security policy and navigation) ---------------------------------------------------------------------------------
html = (HERE / "ui" / "index.html").read_text(encoding="utf-8")
csp = re.search(r'Content-Security-Policy" content="([^"]+)"', html).group(1)
check("the page has a Content-Security-Policy", bool(csp))
for needed in ("default-src 'none'", "connect-src 'none'", "frame-src 'none'", "object-src 'none'", "base-uri 'none'", "form-action 'none'", "img-src https: data:"):
    check("CSP: " + needed, needed in csp)
check("CSP allows no remote script or style", "script-src 'unsafe-inline'" in csp and "script-src https" not in csp and "http:" not in csp)
check("the page loads nothing from the network by itself", not re.search(r'(src|href)="https?://', html))
js = (HERE / "ui" / "app.js").read_text(encoding="utf-8")
check("the page blocks links, form submits and new windows", "preventDefault" in js and "window.open = () => null" in js)
check("text from outside is never put into the page as HTML", "innerHTML" not in js and "insertAdjacentHTML" not in js and "document.write" not in js)

# ---- updates ---------------------------------------------------------------------------------------------------------------------------------
check("with nothing set, the update check uses the official site address", updates.update_url() == "https://plungevr.com/latest.json")
os.environ["PLUNGE_UPDATE_URL"] = "http://127.0.0.1:9/latest.json"                  # nothing listens here
_r = updates.check()
check("an unreachable update server never raises or claims an update", _r.get("available") is False and "error" in _r)
os.environ.pop("PLUNGE_UPDATE_URL", None)
us = ThreadingHTTPServer(("127.0.0.1", 0), type("H", (__import__("http.server", fromlist=["x"]).BaseHTTPRequestHandler,), {
    "log_message": lambda *a: None,
    "do_GET": lambda self: (self.send_response(200), self.send_header("Content-Type", "application/json"), self.end_headers(), self.wfile.write(MANIFEST["v"]))}))
MANIFEST = {"v": b""}
threading.Thread(target=us.serve_forever, daemon=True).start()
os.environ["PLUNGE_UPDATE_URL"] = "http://127.0.0.1:%d/latest.json" % us.server_address[1]
MANIFEST["v"] = json.dumps({"version": "9.9.9", "url": "https://127.0.0.1/download", "notes": "New\u202e stuff"}).encode()
u = updates.check("0.9.0")
check("a newer version is announced, with a cleaned note", u["available"] and u["version"] == "9.9.9" and u["notes"] == "New stuff")
check("the same or an older version is not an update", not updates.check("9.9.9")["available"] and not updates.check("10.0.0")["available"])
check("version numbers compare numerically (0.10 > 0.9)", updates._vkey("0.10.0") > updates._vkey("0.9.0"))
for name, manifest in (("a non-https download link", {"version": "9.9.9", "url": "http://127.0.0.1/x"}), ("a download link on another site", {"version": "9.9.9", "url": "https://evil.example/x"}),
                       ("a version that isn't a version", {"version": "latest; calc", "url": "https://127.0.0.1/x"}), ("a file link", {"version": "9.9.9", "url": "file:///C:/x.exe"})):
    MANIFEST["v"] = json.dumps(manifest).encode()
    r = updates.check("0.9.0")
    check("update file with %s is refused" % name, not r["available"] and "error" in r)
MANIFEST["v"] = b"{not json"
check("a broken update file never raises", not updates.check("0.9.0")["available"])
MANIFEST["v"] = b"x" * (updates.MAX_BYTES * 3)
check("an oversized update file never raises", not updates.check("0.9.0")["available"])
os.environ["PLUNGE_UPDATE_URL"] = "http://updates.example.com/latest.json"
check("a plain-http update address on another machine is refused", "error" in updates.check("0.9.0"))
MANIFEST["v"] = json.dumps({"version": "9.9.9", "url": "https://127.0.0.1/download"}).encode()
os.environ["PLUNGE_UPDATE_URL"] = "http://127.0.0.1:%d/latest.json" % us.server_address[1]
opened = []
updates.os.startfile = lambda p: opened.append(p)
updates.open_download()
check("open_download opens only the validated link", opened == ["https://127.0.0.1/download"])
os.environ.pop("PLUNGE_UPDATE_URL")
check("open_download refuses when there is no update", raises(updates.open_download, ValueError))

# ---- single instance, pending links ---------------------------------------------------------------------------------------------------------------
name = "Local\\PlungeTest%d" % os.getpid()
check("the first copy may run", app._single_instance(name) is True)
check("a second copy is told another one is running", app._single_instance(name) is False)
api.forward_link("plunge://join/abc234")
check("a join link forwarded by a second copy is picked up once", api.startup_link()["code"] == "ABC234" and api.startup_link()["code"] is None)
api.forward_link("plunge://launch/evil")
api.forward_link("plunge://join/AB")
check("malformed forwarded links are dropped", api.startup_link()["code"] is None)
(paths.DATA / "pending_link.txt").write_text("../../evil", encoding="utf-8")
check("a tampered pending file is ignored", api.startup_link()["code"] is None)

# ---- logging and error handling -----------------------------------------------------------------------------------------------------------------------
log.setup()
log.LOGGER.info("test line")
for h in log.LOGGER.handlers:
    h.flush()
check("the log file is created", (log.log_dir() / "plunge.log").exists() and "test line" in (log.log_dir() / "plunge.log").read_text())
b = app.Bridge()
api.boom_value = lambda: (_ for _ in ()).throw(ValueError("expected problem"))
api.boom_bug = lambda: {}["missing"]
setattr(app.Bridge, "boom_value", app.Bridge._wrap("boom_value"))
setattr(app.Bridge, "boom_bug", app.Bridge._wrap("boom_bug"))
check("an expected problem reaches the UI as its own message", b.boom_value() == {"error": "expected problem"})
r = b.boom_bug()
check("an unexpected bug shows a generic message, not internals", "KeyError" in r["error"] and "missing" not in r["error"] and "log" in r["error"].lower())
for h in log.LOGGER.handlers:
    h.flush()
check("the bug's details went to the log", "boom_bug crashed" in (log.log_dir() / "plunge.log").read_text() and "Traceback" in (log.log_dir() / "plunge.log").read_text())

# ---- repository hygiene ---------------------------------------------------------------------------------------------------------------------------------
reqs = [ln for ln in (HERE / "requirements.txt").read_text().splitlines() if ln.strip() and not ln.startswith("#")]
check("every dependency is pinned to an exact version", reqs and all(re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][A-Za-z0-9.]*", ln) for ln in reqs))
check("SECURITY.md covers reporting and limits", all(w in (HERE / "SECURITY.md").read_text() for w in ("Reporting a problem", "does **not**", "anti-cheat")))
df = (HERE / "deploy" / "Dockerfile").read_text()
dc = (HERE / "deploy" / "docker-compose.yml").read_text()
check("the server container runs as a normal user", re.search(r"^USER plunge", df, re.M) is not None)
check("the compose file drops capabilities, is read-only and limits resources", "cap_drop" in dc and "read_only: true" in dc and "mem_limit" in dc and "no-new-privileges" in dc)
check("only the proxy is published to the internet", dc.count("ports:") == 1 and "443:443" in dc)
check("the real .env and signing keys are never committed", all(x in (HERE / ".gitignore").read_text() for x in ("deploy/.env", "*.pfx", "*.key")))
check("no secret is baked into any source file", not [p.name for p in list((HERE / "core").glob("*.py")) + [HERE / "app.py"] if re.search(r"llc_[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}", p.read_text(encoding="utf-8"))])

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
