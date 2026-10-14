"""Tests: multiplayer the way Melty does it: free ports, join links, Steam join links, reachable addresses, open games, safe environment names."""
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(tmp / "local")
os.environ["APPDATA"] = str(tmp / "roam")
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from core import api, lobby, lobby_server, paths, profiles, recipe, safety  # noqa: E402

paths.ensure()
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# ---- safe environment names and join links ---------------------------------------------------------------
check("a mod's own variable is allowed", not safety.bad_env_name("MYMOD_JOIN") and not safety.bad_env_name("DOORSTOP_ENABLED"))
check("system and runtime variables are refused", all(safety.bad_env_name(n) for n in ("PATH", "COMSPEC", "TEMP", "DOTNET_STARTUP_HOOKS", "COR_PROFILER", "LD_PRELOAD", "JAVA_TOOL_OPTIONS", "PYTHONPATH", "NODE_OPTIONS")))
check("odd names are refused", all(safety.bad_env_name(n) for n in ("mymod_join", "A", "X Y", "A;B", "", None, 5)))
check("a steam join link is allowed", safety.valid_join_uri("steam://connect/{address}") and safety.valid_join_uri("steam://rungameid/123//+connect%20x") is False)
check("other links, commands and double placeholders are refused", not any(safety.valid_join_uri(u) for u in ("http://x/{address}", "steam://x;calc", "steam://a b", "file:///c:/x", "steam://{address}/{address}", "", None)))

# ---- a fake game with a multiplayer build ---------------------------------------------------------------
gdir = tmp / "steam" / "Foo"
gdir.mkdir(parents=True)
GAME = {"appid": "4242", "name": "Foo", "path": str(gdir), "exe": None, "engine": "unity", "anticheat": [], "buildId": "1",
        "status": "experimental", "why": "", "route": {"id": "agent-unity", "label": "x", "maturity": "m", "note": "n"}}
api._STATE.update(games=[GAME], demo=False)
BASE = {"schema": 2, "title": "Foo VR", "tagline": "t", "steamAppId": 4242, "engine": "unity", "tier": "native", "author": "me", "license": "MIT",
        "comfort": "gentle", "controls": "motion", "version": "1.0.0",
        "tested": {"gameVersion": "1", "buildId": "1", "minutesPlayed": 9, "headset": "q", "multiplayer": "hosted and joined on two copies"},
        "recipe": {"runtime": None, "install": [{"from": "files/a.cfg", "to": "{game}/a.cfg"}], "launch": {"mode": "steam"}}}


def mk(slug, mp):
    d = paths.PROFILES / slug
    (d / "files").mkdir(parents=True, exist_ok=True)
    (d / "files" / "a.cfg").write_text("x")
    meta = json.loads(json.dumps(BASE))
    meta["title"] = slug
    meta["recipe"]["multiplayer"] = {"maxPlayers": 4, "officialServers": False, **mp}
    (d / "plunge.json").write_text(json.dumps(meta))
    return [f["msg"] for f in profiles.validate(slug) if f["level"] == "error"]


check("joinUri alone is a valid way to join", mk("uri-vr", {"joinUri": "steam://connect/{address}"}) == [])
check("a bad joinUri is refused", any("joinUri" in e for e in mk("baduri-vr", {"joinUri": "http://evil/{address}"})))
check("a system environment variable in hostEnv is refused", any("PATH" in e for e in mk("env-vr", {"joinArgs": ["+c"], "hostEnv": {"PATH": "C:/x"}})))
check("a mod's own variable passes", mk("env2-vr", {"joinArgs": ["+c"], "hostEnv": {"MYMOD_HOST": "1"}, "joinEnv": {"MYMOD_JOIN": "{address}"}}) == [])
try:
    recipe.launch(GAME, {"multiplayer": {"hostEnv": {"PATH": "x"}}}, "host", None, 25000)
    check("a hostile build cannot set PATH at launch either", False)
except recipe.RecipeError:
    check("a hostile build cannot set PATH at launch either", True)

# joinUri starts the Steam link with the host's address
opened = []
recipe.os.startfile = lambda u: opened.append(u)
res = recipe.launch(GAME, {"multiplayer": {"joinUri": "steam://connect/{address}"}}, "join", "100.64.0.9:27015")
check("join link opens steam://connect/<address>", opened == ["steam://connect/100.64.0.9:27015"] and res["how"] == "steam link")
try:
    recipe.launch(GAME, {"multiplayer": {"joinUri": "steam://connect/{address}"}}, "join", "x;calc")
    check("a bad address never reaches the link", False)
except recipe.RecipeError:
    check("a bad address never reaches the link", len(opened) == 1)

# ---- a free port, picked for real ---------------------------------------------------------------------
busy_t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
busy_t.bind(("0.0.0.0", 0))
base = busy_t.getsockname()[1]
p = lobby.free_port(base)
check("a port that is taken is skipped", p != base and p > base)
busy_u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    busy_u.bind(("0.0.0.0", p))
    check("a port taken by UDP is skipped too", lobby.free_port(base) not in (base, p))
finally:
    busy_u.close()
    busy_t.close()

# ---- reachable addresses -----------------------------------------------------------------------------------
lobby._ipconfig = lambda: "Windows IP\n\nEthernet adapter Ethernet:\n   IPv4 Address. . . : 192.168.1.5\n\nUnknown adapter Tailscale:\n   IPv4 Address. . . : 100.101.102.103\n"
check("Tailscale is found", lobby.private_network() == {"name": "Tailscale", "ip": "100.101.102.103"})
check("a home-only address is swapped for the Tailscale one", lobby.reachable("192.168.1.5:7777") == ("100.101.102.103:7777", "Tailscale")
      and lobby.reachable("127.0.0.1:1") == ("100.101.102.103:1", "Tailscale") and lobby.reachable("localhost")[0] == "100.101.102.103")
check("a public address or host name is left alone", lobby.reachable("8.8.8.8:1") == ("8.8.8.8:1", None) and lobby.reachable("play.example.com:9") == ("play.example.com:9", None))
lobby._ipconfig = lambda: "Windows IP\n\nEthernet adapter Ethernet:\n   IPv4 Address. . . : 192.168.1.5\n"
check("without a friends network nothing is changed", lobby.private_network() is None and lobby.reachable("192.168.1.5:7777") == ("192.168.1.5:7777", None))
lobby._ipconfig = lambda: "Windows IP\n\nUnknown adapter ZeroTier One:\n   IPv4 Address. . . : 10.147.17.8\n"
check("ZeroTier is found", lobby.private_network()["name"] == "ZeroTier")

# ---- hosting, invite link and joining through a local lobby ------------------------------------------------
lobby_server.LIMITS.update({k: (1000, 3600) for k in lobby_server.LIMITS}) if hasattr(lobby_server, "LIMITS") else None
srv = ThreadingHTTPServer(("127.0.0.1", 0), lobby_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
lobby.LOBBY_URL = "http://127.0.0.1:%d" % srv.server_address[1]
started = []
recipe.launch = lambda game, rc, mode="solo", address=None, port=None: started.append((mode, address, port)) or {"mode": mode, "started": True, "how": "steam"}

mk("mp-vr", {"hostArgs": ["+host", "{port}"], "joinArgs": ["+connect", "{address}"]})
lobby._ipconfig = lambda: "Unknown adapter Tailscale:\n   IPv4 Address. . . : 100.101.102.103\n"
h = api.host("4242", "mp-vr", True, None)
check("hosting needs an address when the game does not report one, and suggests the Tailscale one", h.get("needAddress") and (h["suggest"] or "").startswith("100.101.102.103:") and h["network"] == "Tailscale")
check("the host got a free port to listen on", started[-1][0] == "host" and 25000 <= started[-1][2] < 25100 + 1000)
h = api.host("4242", "mp-vr", True, "192.168.1.5:25001")
check("a typed address is the player's choice and is kept", h["address"] == "192.168.1.5:25001" and h["network"] is None)
check("hosting returns a shareable invite link", h["link"] == "https://plungevr.com/join/" + h["code"])
api.stop_hosting("4242")

# the build's own log reports a home address: it is swapped for the friends-network one
log = gdir / "latest.log"
log.write_text("starting\nHosting at 192.168.1.5:25005\n")
mk("mplog-vr", {"hostArgs": ["+host", "{port}"], "joinArgs": ["+connect", "{address}"], "address": {"log": "{game}/latest.log", "after": "Hosting at "}})
h = api.host("4242", "mplog-vr", True, None)
check("a home-only address from the log is swapped for the Tailscale address", h["address"] == "100.101.102.103:25005" and h["network"] == "Tailscale")
code = h["code"]
check("the open game is listed on the build's page", any(l["code"] == code and l["profile"] == "mplog-vr" for l in api.lobbies("4242")["lobbies"]))
ji = api.join_info(code)
check("join_info says what the code is for and never shows the address", ji["profile"] == "mplog-vr" and ji["ownsGame"] and ji["haveBuild"] and "address" not in ji and "100.101" not in json.dumps(ji))
r = api.join(code)
check("joining starts the game on the host's address", started[-1] == ("join", "100.101.102.103:25005", None) and "manualAddress" not in r)
api.stop_hosting("4242")

# a game that can only be joined from its own menu: the address is handed over
mk("manual-vr", {"manualJoin": True, "hostArgs": ["+host", "{port}"]})
h = api.host("4242", "manual-vr", False, "8.8.8.8:7777")
r = api.join(h["code"])
check("manual-join games hand the joiner the address to paste", r["manualAddress"] == "8.8.8.8:7777")
api.stop_hosting("4242")

# a joiner without the build is told, and join_info says so
h = api.host("4242", "mp-vr", False, "8.8.4.4:1")
import shutil  # noqa: E402
shutil.rmtree(paths.PROFILES / "mp-vr")
check("join_info reports a missing build so the app can fetch it", api.join_info(h["code"])["haveBuild"] is False)
try:
    api.join(h["code"])
    check("join refuses until the build is here", False)
except ValueError as e:
    check("join refuses until the build is here", "need the build" in str(e))
api.stop_hosting("4242")

# ---- the invite page on the website ------------------------------------------------------------------------
site = HERE / "site"
sys.path.insert(0, str(HERE / "tools"))
import build_site  # noqa: E402
out = build_site.build("")
page = (Path(out) / "join" / "index.html").read_text(encoding="utf-8")
js = (Path(out) / "js" / "join.js").read_text(encoding="utf-8")
check("the website has an invite page that opens plunge://join/<code>", 'id="jopen"' in page and "plunge://join/" in js and "/js/join.js" in page)
check("invite links of any code are routed to that page", "/join/*  /join/index.html  200" in (Path(out) / "_redirects").read_text(encoding="utf-8") and "/join/:code" in (Path(out) / "vercel.json").read_text(encoding="utf-8"))
check("the invite page only accepts well-formed codes and writes text, never HTML", "[A-Z2-9]{4,12}" in js and "innerHTML" not in js)

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
