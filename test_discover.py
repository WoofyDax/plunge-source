"""Tests: Discover search and filters, one-click download-and-apply, multiplayer wishes and added-multiplayer rules. Temp dirs only."""
import io
import json
import os
import sys
import tempfile
import threading
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(tmp / "local")
os.environ["APPDATA"] = str(tmp / "roam")
sys.path.insert(0, str(Path(__file__).parent))
from core import api, hub, hub_server, paths, prefs, profiles, prompt, recipe, settings  # noqa: E402

paths.ensure()
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# ---- a local hub with a few builds ---------------------------------------------------------------
hub_server.STATE.update(dir=tmp / "hubdata", require_auth=False)
hub_server.STATE["dir"].mkdir(parents=True, exist_ok=True)
hub_server.LIMITS["upload"] = (1000, 3600)
srv = ThreadingHTTPServer(("127.0.0.1", 0), hub_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
hub.HUB_URL = "http://127.0.0.1:%d" % srv.server_address[1]
settings.set("account", {"token": "t" * 43, "username": "tester", "email": "t@example.com"})

BASE = {"schema": 2, "title": "Foo VR", "tagline": "Fly it", "steamAppId": 4242, "engine": "unity", "tier": "native", "author": "me",
        "license": "MIT", "comfort": "gentle", "controls": "motion", "version": "1.0.0",
        "tested": {"gameVersion": "1", "buildId": "1000", "minutesPlayed": 9, "headset": "q"},
        "recipe": {"runtime": None, "install": [{"from": "files/a.cfg", "to": "{game}/a.cfg"}], "launch": {"mode": "steam"}}}
MP = {"maxPlayers": 4, "officialServers": False, "manualJoin": True}


def zip_of(meta, files=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("plunge.json", json.dumps(meta))
        for n, d in (files or {"files/a.cfg": "x=1"}).items():
            z.writestr(n, d)
    return buf.getvalue()


def up(meta):
    return hub._req("/profiles", zip_of(meta), "application/zip")["id"]


foo = up(BASE)
bar = up({**BASE, "title": "Bar Racing VR", "steamAppId": 777, "tier": "injected", "tagline": "Race friends",
          "recipe": {**BASE["recipe"], "multiplayer": MP}, "tested": {**BASE["tested"], "multiplayer": "hosted and joined on two copies"}})
baz = up({**BASE, "title": "Baz VR", "steamAppId": 888, "tier": "theater"})
hub.like(bar)

# ---- the game library the player has ---------------------------------------------------------------
gdir = tmp / "steam" / "Foo"
gdir.mkdir(parents=True)
GAME = {"appid": "4242", "name": "Foo", "path": str(gdir), "exe": None, "engine": "unity", "anticheat": [], "buildId": "1000",
        "status": "experimental", "why": "", "route": {"id": "agent-unity", "label": "x", "maturity": "m", "note": "n"}}
api._STATE.update(games=[GAME], demo=False)
launched = []
recipe.launch = lambda *a, **k: launched.append(a) or {"mode": "stub", "started": True, "how": "steam"}

ids = lambda r: sorted(x["id"] for x in r["profiles"])
check("browse with no filters lists everything", ids(api.discover_browse()) == sorted([foo, bar, baz]))
check("search by title", ids(api.discover_browse("racing")) == [bar])
check("search by tagline", ids(api.discover_browse("fly it")) == [foo, baz] or ids(api.discover_browse("fly it")) == sorted([foo, baz]))
check("search by creator", len(api.discover_browse("me")["profiles"]) == 3)
check("filter by game", ids(api.discover_browse(appid="777")) == [bar])
check("filter by type", ids(api.discover_browse(tier="theater")) == [baz])
check("multiplayer only", ids(api.discover_browse(mp=True)) == [bar])
check("most liked comes first", api.discover_browse(sort="liked")["profiles"][0]["id"] == bar)
check("only games I own", ids(api.discover_browse(mine=True)) == [foo])
check("results say whether the game is owned", {r["id"]: r["gameOwned"] for r in api.discover_browse()["profiles"]} == {foo: True, bar: False, baz: False})
check("an unknown sort falls back to newest", len(api.discover_browse(sort="'; drop")["profiles"]) == 3)
check("filters combine", ids(api.discover_browse("baz", tier="theater", mp=False)) == [baz] and ids(api.discover_browse("baz", mp=True)) == [])
check("multiplayer kind is listed", next(r for r in api.discover_browse()["profiles"] if r["id"] == bar)["multiplayerKind"] == "native")

# ---- download and apply to my game ---------------------------------------------------------------
check("nothing is applied at first", api.game_info("4242")["installedProfile"] is None)
api.get_profile(foo)
try:
    api.apply_build("4242", bar)
    check("a build for another game is refused", False)
except Exception as e:
    check("a build for another game is refused", True)
r = api.apply_build("4242", foo)
check("apply puts the files into the game and records which build", (gdir / "a.cfg").exists() and r["installed"] == 1 and api.game_info("4242")["installedProfile"] == foo)
check("apply does not start the game", not launched)
api.uninstall("4242")
check("removing restores the game and clears the record", not (gdir / "a.cfg").exists() and api.game_info("4242")["installedProfile"] is None)

# a build that ships third-party programs needs the player's OK first
import hashlib  # noqa: E402
sha = hashlib.sha256(b"MZ").hexdigest()
try:
    zip_ = zip_of({**BASE, "title": "Loader2 VR", "bundled": [{"path": "files/winhttp.dll", "name": "BepInEx", "author": "BepInEx team", "license": "LGPL-2.1", "url": "https://github.com/BepInEx/BepInEx", "sha256": sha}]},
                  {"files/a.cfg": "x=1", "files/winhttp.dll": b"MZ"})
    lid = hub._req("/profiles", zip_, "application/zip")["id"]
except hub.HubError:
    lid = None
if lid:
    api.get_profile(lid)
    try:
        api.apply_build("4242", lid)
        check("apply refuses third-party binaries until trusted", False)
    except ValueError as e:
        check("apply refuses third-party binaries until trusted", str(e).startswith("TRUST_REQUIRED"))
    api.trust_profile(lid)
    check("after trusting, apply works", api.apply_build("4242", lid)["installed"] >= 1)
    api.uninstall("4242")
else:
    check("apply refuses third-party binaries until trusted (test build rejected by hub)", False)

# anti-cheat games are never changed, even by a download
GAME["status"] = "blocked"
GAME["why"] = "anti-cheat"
try:
    api.apply_build("4242", foo)
    check("a game with anti-cheat is never changed", False)
except ValueError:
    check("a game with anti-cheat is never changed", not (gdir / "a.cfg").exists())
GAME["status"] = "experimental"

# ---- multiplayer wishes ----------------------------------------------------------------------------
check("multiplayer defaults to single player and adds nothing to the brief", prefs.clean({})["multiplayer"] == "no" and prefs.brief_text(prefs.clean({})) == "")
check("a bad multiplayer value falls back", prefs.clean({"multiplayer": "everything"})["multiplayer"] == "no")
check("finishing the guided setup alone changes nothing in the brief", prefs.is_default({"guided": True}) and prefs.brief_text({"guided": True}) == "")
check("wanting multiplayer is no longer a default", not prefs.is_default({"multiplayer": "add"}))
check("added multiplayer is requested in the brief block", "experimental" in prefs.brief_text({"multiplayer": "add"}))
prefs.save("4242", {"multiplayer": "add", "guided": True})
brief = api.make_prompt("4242")["prompt"]
check("the brief carries the added-multiplayer instructions only when asked", "Adding multiplayer to a single-player game" in brief)
check("it says to be honest, experimental, no relay or accounts", all(s in brief for s in ("experimental", "No third-party relay", "Tailscale", "never combine two games")))
check("the old 'no public library' line is gone", "no public library yet" not in brief and "press Publish" in brief)

# ---- rules for multiplayer an agent adds ----------------------------------------------------------
d = paths.PROFILES / "added-mp"
(d / "files").mkdir(parents=True)
(d / "files" / "a.cfg").write_text("x")
meta = {**BASE, "title": "Added", "recipe": {**BASE["recipe"], "multiplayer": {**MP, "kind": "added"}}, "tested": {**BASE["tested"], "multiplayer": "worked on two copies"}}
(d / "plunge.json").write_text(json.dumps(meta))
errs = [f["msg"] for f in profiles.validate("added-mp") if f["level"] == "error"]
check("added multiplayer that does not say experimental is refused", any("experimental" in e for e in errs))
meta["tested"]["multiplayer"] = "experimental: same PC only; shares player positions, not world state"
(d / "plunge.json").write_text(json.dumps(meta))
check("added multiplayer labelled experimental passes", not [f for f in profiles.validate("added-mp") if f["level"] == "error"])
meta["recipe"]["multiplayer"]["kind"] = "weird"
(d / "plunge.json").write_text(json.dumps(meta))
check("an unknown multiplayer kind is refused", any("kind" in f["msg"] for f in profiles.validate("added-mp") if f["level"] == "error"))

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
