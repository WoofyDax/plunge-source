"""Tests: profile validation, recipe install/uninstall, lobby service, agent CLI. Uses temp dirs only."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(tmp / "local")
os.environ["APPDATA"] = str(tmp / "roam")
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from core import lobby, lobby_server, paths, profiles, recipe  # noqa: E402

paths.ensure()
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# ---- a fake game ---------------------------------------------------------------------------
game_dir = tmp / "steam" / "FooGame"
(game_dir / "Foo" / "Binaries").mkdir(parents=True)
(game_dir / "Foo" / "settings.ini").write_text("original")
GAME = {"appid": "4242", "name": "Foo", "path": str(game_dir), "exe": str(game_dir / "Foo" / "Binaries" / "Foo-Win64-Shipping.exe")}

GOOD = {"schema": 2, "title": "Foo VR", "tagline": "t", "steamAppId": 4242, "engine": "unity", "tier": "native",
        "author": "me", "license": "MIT", "comfort": "gentle", "controls": "motion",
        "tested": {"gameVersion": "1.0", "minutesPlayed": 12, "headset": "Quest 3"},
        "recipe": {"runtime": None,
                   "install": [{"from": "files/mod.cfg", "to": "{game}/BepInEx/config/mod.cfg"},
                               {"from": "files/settings.ini", "to": "{game}/Foo/settings.ini"}],
                   "launch": {"mode": "steam"}}}


def make(slug, meta, files=None):
    d = paths.PROFILES / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "plunge.json").write_text(json.dumps(meta))
    for name, data in (files or {"files/mod.cfg": "a=1", "files/settings.ini": "vr=1"}).items():
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(data if isinstance(data, bytes) else data.encode())
    return d


def errors(slug, game=GAME):
    return [f["msg"] for f in profiles.validate(slug, game) if f["level"] == "error"]


def mut(**kw):
    m = json.loads(json.dumps(GOOD))
    for k, v in kw.items():
        m[k] = v
    return m


# ---- validator -----------------------------------------------------------------------------
make("good-vr", GOOD)
check("clean profile has no errors", errors("good-vr") == [])
make("untested-vr", mut(tested={}))
check("untested profile rejected", any("tested" in e for e in errors("untested-vr")))
make("tier-vr", mut(tier="magic"))
check("unknown tier rejected", any("tier" in e for e in errors("tier-vr")))
make("pak-vr", GOOD, {"files/mod.cfg": "a", "files/settings.ini": "b", "files/data.pak": b"x"})
check("game content rejected", any("data.pak" in e for e in errors("pak-vr")))
make("dll-vr", GOOD, {"files/mod.cfg": "a", "files/settings.ini": "b", "files/winhttp.dll": b"MZ"})
check("undeclared DLL rejected", any("winhttp.dll" in e for e in errors("dll-vr")))
sha = hashlib.sha256(b"MZ").hexdigest()
bundled = {"path": "files/winhttp.dll", "name": "BepInEx", "author": "BepInEx team", "license": "LGPL-2.1",
           "url": "https://github.com/BepInEx/BepInEx", "sha256": sha}
make("dll-ok-vr", mut(bundled=[bundled]), {"files/mod.cfg": "a", "files/settings.ini": "b", "files/winhttp.dll": b"MZ"})
check("declared DLL with matching sha256 accepted", errors("dll-ok-vr") == [])
make("dll-bad-vr", mut(bundled=[{**bundled, "sha256": "0" * 64}]), {"files/mod.cfg": "a", "files/settings.ini": "b", "files/winhttp.dll": b"MZ"})
check("DLL with wrong sha256 rejected", any("sha256" in e for e in errors("dll-bad-vr")))
make("lic-vr", mut(bundled=[{**bundled, "license": ""}]), {"files/mod.cfg": "a", "files/settings.ini": "b", "files/winhttp.dll": b"MZ"})
check("bundled entry without license rejected", any("license" in e for e in errors("lic-vr")))
bad = mut()
bad["recipe"]["install"] = [{"from": "files/mod.cfg", "to": "{game}/../outside.txt"}]
make("trav-vr", bad)
check("destination with .. rejected", any("recipe.install" in e for e in errors("trav-vr")))
bad = mut()
bad["recipe"]["install"] = [{"from": "files/mod.cfg", "to": "C:/Windows/evil.dll"}]
make("abs-vr", bad)
check("destination outside {game} rejected", any("recipe.install" in e for e in errors("abs-vr")))
bad = mut()
bad["recipe"]["install"] = [{"from": "../../etc/passwd", "to": "{game}/x"}]
make("src-vr", bad)
check("source outside profile rejected", any("recipe.install" in e for e in errors("src-vr")))
make("secret-vr", GOOD, {"files/mod.cfg": "Authorization: Bearer llc_k-abcdefghijklmnopqrstuvwxyz0123456789", "files/settings.ini": "b"})
check("leaked token rejected", any("secret" in e for e in errors("secret-vr")))
make("missing-vr", {"schema": 2})
check("missing fields listed", len(errors("missing-vr")) >= 8)
MP = {"maxPlayers": 4, "officialServers": False, "joinArgs": ["+connect", "{address}"], "hostArgs": ["+host", "{port}"]}
bad = mut(); bad["recipe"]["multiplayer"] = MP
make("mp-untested-vr", bad)
check("multiplayer without a recorded test rejected", any("tested.multiplayer" in e for e in errors("mp-untested-vr")))
ok = mut(); ok["recipe"]["multiplayer"] = MP; ok["tested"]["multiplayer"] = "hosted and joined with two instances"
make("mp-ok-vr", ok)
check("tested multiplayer profile accepted", errors("mp-ok-vr") == [])
bad = json.loads(json.dumps(ok)); bad["recipe"]["multiplayer"]["officialServers"] = True
make("mp-official-vr", bad)
check("official servers refused", any("officialServers" in e for e in errors("mp-official-vr")))
bad = json.loads(json.dumps(ok)); bad["recipe"]["multiplayer"]["maxPlayers"] = 1
make("mp-max-vr", bad)
check("maxPlayers must be >= 2", any("maxPlayers" in e for e in errors("mp-max-vr")))
try:
    profiles.profile_dir("../escape")
    check("bad slug rejected", False)
except ValueError:
    check("bad slug rejected", True)

# ---- recipe install / uninstall ------------------------------------------------------------
r = recipe.install(paths.PROFILES / "good-vr", GOOD["recipe"], GAME)
check("install reports files", r["files"] == 2)
check("install creates new file", (game_dir / "BepInEx/config/mod.cfg").read_text() == "a=1")
check("install replaces existing file", (game_dir / "Foo/settings.ini").read_text() == "vr=1")
check("manifest written", recipe.is_installed("4242"))
u = recipe.uninstall("4242")
check("uninstall restores the original", (game_dir / "Foo/settings.ini").read_text() == "original")
check("uninstall removes created files and empty folders", not (game_dir / "BepInEx").exists())
check("uninstall clears manifest", not recipe.is_installed("4242") and u["restored"] == 1 and u["removed"] == 1)

broken = json.loads(json.dumps(GOOD["recipe"]))
broken["install"].append({"from": "files/missing.cfg", "to": "{game}/x.cfg"})
try:
    recipe.install(paths.PROFILES / "good-vr", broken, GAME)
    check("failed install raises", False)
except recipe.RecipeError:
    check("failed install raises", True)
check("failed install rolls back fully", (game_dir / "Foo/settings.ini").read_text() == "original"
      and not (game_dir / "BepInEx").exists() and not recipe.is_installed("4242"))

# joinFile: join writes the address, solo launch empties it, uninstall restores
recipe.install(paths.PROFILES / "good-vr", GOOD["recipe"], GAME)
spec = {"path": "{game}/Foo/net.cfg", "key": "join"}
recipe.write_join_file(spec, GAME, "10.0.0.5:7777", "4242")
check("joinFile writes address", "join=10.0.0.5:7777" in (game_dir / "Foo/net.cfg").read_text())
recipe.write_join_file(spec, GAME, "", "4242")
check("joinFile empties address for solo", "join=" not in (game_dir / "Foo/net.cfg").read_text())
recipe.uninstall("4242")
check("uninstall removes the joinFile it created", not (game_dir / "Foo/net.cfg").exists())

# ---- lobby service -------------------------------------------------------------------------
srv = ThreadingHTTPServer(("127.0.0.1", 0), lobby_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
lobby.LOBBY_URL = "http://127.0.0.1:%d" % srv.server_address[1]

r = lobby.open_lobby("4242", "good-vr", "Foo night", 2, "10.0.0.5:7777", True)
code = r["code"]
check("lobby code is 6 chars", len(code) == 6)
check("public lobby is listed", [l["code"] for l in lobby.list_open("4242")] == [code])
check("listing hides the address", all("address" not in l for l in lobby.list_open("4242")))
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
os.environ["PLUNGE_TRUST_PROXY"] = "1"      # lets this test play several different players by address


def join_as(ip, c):
    req = urllib.request.Request(lobby.LOBBY_URL + "/lobbies/%s/join" % c, data=b"{}", headers={"Content-Type": "application/json", "X-Forwarded-For": ip})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


first_key = lobby._HOSTED["4242"]["key"]
j = lobby.resolve("plunge://join/" + code.lower())
check("join resolves the host address", j["address"] == "10.0.0.5:7777" and j["profile"] == "good-vr")
check("the same player joining again doesn't use another slot", lobby.resolve(code)["address"] == "10.0.0.5:7777")
status, body = join_as("10.1.1.2", code)
check("a full lobby refuses another player", status == 409 and "full" in body["error"])
private = lobby.open_lobby("4242", "good-vr", "Secret", 4, "10.0.0.6:1", False)
check("private lobby is not listed", private["code"] not in [l["code"] for l in lobby.list_open()])
check("private lobby is joinable by code", lobby.resolve(private["code"])["address"] == "10.0.0.6:1")
try:
    lobby._call("/lobbies/%s/close" % code, {"hostKey": "wrong"})
    check("wrong host key cannot close", False)
except lobby.LobbyError:
    check("wrong host key cannot close", True)
lobby._call("/lobbies/%s/close" % code, {"hostKey": first_key})
check("the host can close their lobby", True)
try:
    lobby.resolve(code)
    check("closed lobby disappears", False)
except lobby.LobbyError:
    check("closed lobby disappears", True)
check("close_lobby closes the lobby the app is hosting", lobby.close_lobby("4242")["closed"])
lobby_server.TTL = 0.2
stale = lobby.open_lobby("999", "x", "Stale", 2, "1.1.1.1:1", True)
time.sleep(0.5)
check("lobby expires without heartbeat", lobby.list_open("999") == [])
lobby_server.TTL = 45
try:
    lobby._call("/lobbies", {"appid": "1"})
    check("lobby requires an address", False)
except lobby.LobbyError:
    check("lobby requires an address", True)

# host address discovery from a log file
log = game_dir / "Foo" / "latest.log"
log.write_text("starting\nHosting at 192.168.1.9:7777 ok\n")
spec = {"log": "{game}/Foo/latest.log", "after": "Hosting at "}
check("address is found in the log", lobby.find_address(spec, GAME, timeout=2) == "192.168.1.9:7777")
log.write_text("nothing here\n")
check("missing address times out cleanly", lobby.find_address(spec, GAME, timeout=1.2) is None)

# ---- agent CLI -----------------------------------------------------------------------------
env = {**os.environ}
p = subprocess.run([sys.executable, "-I", str(HERE / "app.py"), "tool", "game_info", "no-such-game"],
                   capture_output=True, text=True, env=env)
check("CLI reports unknown game as JSON error, exit 1", p.returncode == 1 and "error" in json.loads(p.stdout))
p = subprocess.run([sys.executable, "-I", str(HERE / "app.py"), "tool", "validate_profile", "good-vr", "4242"],
                   capture_output=True, text=True, env=env)
check("CLI validate_profile fails cleanly for a game not in the library", p.returncode == 1)
p = subprocess.run([sys.executable, "-I", str(HERE / "app.py"), "tool", "bogus"], capture_output=True, text=True, env=env)
check("CLI lists tools on bad command", p.returncode == 2 and "game_info" in p.stdout)

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
