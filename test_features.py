"""Tests: VR detection, preferences, prefsFile, community hub (upload/validate/sort/feature/download). Temp dirs only."""
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
os.environ["PLUNGE_HUB_ADMIN"] = "s3cret"
sys.path.insert(0, str(Path(__file__).parent))
from core import hub, hub_server, paths, prefs, profiles, prompt, recipe, vrinfo  # noqa: E402

paths.ensure()
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# ---- VR support detection ------------------------------------------------------------------
check("steam category 53 -> supported", vrinfo.level_from_categories([{"id": 2}, {"id": 53, "description": "VR Supported"}]) == "supported")
check("steam category 54 -> only", vrinfo.level_from_categories([{"id": 54, "description": "VR Only"}, {"id": 53}]) == "only")
check("no VR category -> None", vrinfo.level_from_categories([{"id": 2, "description": "Single-player"}]) is None)
check("empty categories -> None", vrinfo.level_from_categories(None) is None)
g = tmp / "vrgame"
(g / "bin").mkdir(parents=True)
(g / "bin" / "openvr_api.dll").write_bytes(b"x")
check("openvr dll in the install is detected", vrinfo.from_files(g) == "OpenVR")
check("clean install has no VR files", vrinfo.from_files(tmp / "nothing") is None)
d = vrinfo.describe("1", str(g))
check("file hint is labelled unconfirmed", d["level"] == "supported" and "unconfirmed" in d["via"])
vrinfo._save({"2": {"level": None, "vac": False, "t": __import__("time").time()}})
check("Steam 'no VR' answer beats a file hint", vrinfo.describe("2", str(g))["level"] is None)
vrinfo._save({"3": {"level": "only", "vac": False, "t": __import__("time").time()}})
check("Steam answer is used when cached", vrinfo.describe("3", str(tmp / "x")) == {"level": "only", "via": "Steam", "vac": False})

# ---- preferences ---------------------------------------------------------------------------
check("defaults are default", prefs.is_default(prefs.get(111)))
dirty = {"perspective": "third", "bindingsMode": "custom", "comfort": {"snapTurn": False, "locomotion": "teleport"},
         "bindings": [{"input": "Right grip", "action": "Reload"}, {"input": "Right grip", "action": "dup"},
                      {"input": "Banana", "action": "bad"}, {"input": "Y", "action": "  "}, {"input": "A", "action": "Jump"}],
         "notes": "x" * 5000}
c = prefs.clean(dirty)
check("perspective kept", c["perspective"] == "third")
check("invalid and duplicate bindings dropped", [b["input"] for b in c["bindings"]] == ["Right grip", "A"])
check("notes capped at 2000", len(c["notes"]) == 2000)
check("unknown perspective falls back", prefs.clean({"perspective": "god"})["perspective"] == "auto")
check("garbage input is safe", prefs.clean("nonsense") == prefs.clean({}))
prefs.save(111, dirty)
check("preferences persist", prefs.get(111)["perspective"] == "third" and not prefs.is_default(prefs.get(111)))
bt = prefs.brief_text(prefs.get(111))
check("brief text has perspective and bindings", "Keep third person" in bt and "Right grip -> Reload" in bt)
check("default prefs add nothing to the brief", prefs.brief_text(prefs.clean({})) == "")
# bindings are optional: auto mode keeps what you typed but doesn't apply it
check("bindings default to auto mode", prefs.clean({})["bindingsMode"] == "auto")
auto = {**dirty, "bindingsMode": "auto"}
check("auto mode keeps stored bindings", len(prefs.clean(auto)["bindings"]) == 2)
check("auto mode applies no bindings", prefs.effective(auto)["bindings"] == [])
check("auto mode brief lets the build decide", "VR build decides" in prefs.brief_text(auto) and "Right grip" not in prefs.brief_text(auto))
check("custom mode brief lists bindings", "Right grip -> Reload" in prefs.brief_text(dirty) and "VR build decides" not in prefs.brief_text(dirty))
check("bindings alone in auto mode count as default", prefs.is_default({"bindingsMode": "auto", "bindings": [{"input": "A", "action": "Jump"}]}))
check("custom mode with bindings is not default", not prefs.is_default({"bindingsMode": "custom", "bindings": [{"input": "A", "action": "Jump"}]}))
check("garbage bindingsMode falls back to auto", prefs.clean({"bindingsMode": "xyz"})["bindingsMode"] == "auto")
game = {"name": "Foo", "appid": "111", "engine": "unity", "path": "C:/g", "exe": None, "anticheat": [], "route": {"label": "x", "maturity": "y", "note": "z"}}
p = prompt.build(game, "plunge-cli tool", paths.PROFILES, bt, {"level": "supported", "via": "Steam"})
check("brief includes preferences", "Keep third person" in p and "requirements, not suggestions" in p)
check("brief tells agent to build on built-in VR", "already has official VR support" in p)
check("brief covers weapon-to-hand attachment and aim", "Decouple the weapon" in p and "muzzle" in p and "Two-handed" in p)
check("brief cites the UEVR 6DoF guide", "docs.uevr.io/usage/adding_6dof.html" in p and "UObjectHook" in p)
check("brief cites Unity references", "NewUnityModder/UnityVRMod" in p and "DaXcess/CWVR" in p)
check("brief does not pretend Flat2VR docs exist", "could not find official public documentation" in p)
check("brief warns about GPL code", "GPL-3.0" in p)
import re as _re  # noqa: E402
check("brief still has no unfilled placeholders", not _re.search(r"\{[a-z_]+\}", p.replace("{game}", "").replace("{uevr-config}", "").replace("{address}", "").replace("{port}", "")))
p2 = prompt.build(game, "plunge-cli tool", paths.PROFILES, "", None)
check("no VR note for non-VR games", "official VR support" not in p2)

# ---- prefsFile through the recipe ----------------------------------------------------------
gd = tmp / "steam" / "Foo"
(gd / "cfg").mkdir(parents=True)
(gd / "cfg" / "plunge-prefs.json").write_text("old")
GAME = {"appid": "111", "name": "Foo", "path": str(gd), "exe": None}
recipe.managed_write(recipe.safe_dest("{game}/cfg/plunge-prefs.json", GAME), "seed", "111")
recipe.write_prefs({"path": "{game}/cfg/plunge-prefs.json", "format": "json"}, GAME, prefs.get(111), "111")
written = json.loads((gd / "cfg" / "plunge-prefs.json").read_text())
check("prefsFile json carries preferences", written["perspective"] == "third" and written["bindings"][0]["action"] == "Reload")
recipe.write_prefs({"path": "{game}/cfg/auto.json", "format": "json"}, GAME, prefs.effective(auto), "111")
w = json.loads((gd / "cfg" / "auto.json").read_text())
check("prefsFile in auto mode carries no bindings", w["bindings"] == [] and w["bindingsMode"] == "auto")
recipe.write_prefs({"path": "{game}/cfg/p.ini", "format": "ini"}, GAME, prefs.get(111), "111")
ini = (gd / "cfg" / "p.ini").read_text()
check("prefsFile ini has keys", "perspective=third" in ini and "snapTurn=false" in ini and "bind.Right_grip=Reload" in ini)
try:
    recipe.write_prefs({"path": "{game}/../evil.json"}, GAME, prefs.get(111), "111")
    check("prefsFile cannot escape the game folder", False)
except recipe.RecipeError:
    check("prefsFile cannot escape the game folder", True)
recipe.uninstall("111")
check("uninstall restores the original prefs file", (gd / "cfg" / "plunge-prefs.json").read_text() == "old")
check("uninstall removes the ini it created", not (gd / "cfg" / "p.ini").exists())

# ---- validator: prefsFile ------------------------------------------------------------------
BASE = {"schema": 2, "title": "Foo VR", "tagline": "t", "steamAppId": 111, "engine": "unity", "tier": "native", "author": "me",
        "license": "MIT", "comfort": "gentle", "controls": "motion", "version": "1.0.0",
        "tested": {"gameVersion": "1", "minutesPlayed": 9, "headset": "q"},
        "recipe": {"runtime": None, "install": [{"from": "files/a.cfg", "to": "{game}/a.cfg"}],
                   "prefsFile": {"path": "{game}/cfg/plunge-prefs.json", "format": "json"}}}


def mk(slug, meta, root=paths.PROFILES, files=None):
    d = root / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "plunge.json").write_text(json.dumps(meta))
    for n, data in (files or {"files/a.cfg": "x=1"}).items():
        (d / n).parent.mkdir(parents=True, exist_ok=True)
        (d / n).write_bytes(data if isinstance(data, bytes) else data.encode())


mk("pf-ok-vr", BASE)
errs = lambda s: [f["msg"] for f in profiles.validate(s, GAME) if f["level"] == "error"]  # noqa: E731
check("profile with prefsFile is valid", errs("pf-ok-vr") == [])
bad = json.loads(json.dumps(BASE)); bad["recipe"]["prefsFile"] = {"path": "{game}/../x.json"}
mk("pf-bad-vr", bad)
check("prefsFile outside the game rejected", any("prefsFile" in e for e in errs("pf-bad-vr")))
bad = json.loads(json.dumps(BASE)); bad["recipe"]["prefsFile"]["format"] = "xml"
mk("pf-fmt-vr", bad)
check("prefsFile bad format rejected", any("format" in e for e in errs("pf-fmt-vr")))

# ---- hub -----------------------------------------------------------------------------------
hub_server.STATE["dir"] = tmp / "hub"
hub_server.STATE["admin"] = "s3cret"
hub_server.STATE["require_auth"] = False          # these suites test the hub itself; sign-in rules are tested in test_accounts.py
hub_server.LIMITS["upload"] = (1000, 3600)          # this test uploads many bad zips from one address; the limit itself is tested in test_hardening
srv = ThreadingHTTPServer(("127.0.0.1", 0), hub_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
hub.HUB_URL = "http://127.0.0.1:%d" % srv.server_address[1]
from core import settings as _settings
_settings.set("account", {"token": "t" * 43, "username": "tester", "email": "t@example.com"})    # signed in (this test hub doesn't require it)


def zip_of(meta, files=None, extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("plunge.json", json.dumps(meta))
        for n, d in (files or {"files/a.cfg": "x=1"}).items():
            z.writestr(n, d)
        for n, d in (extra or {}).items():
            z.writestr(n, d)
    return buf.getvalue()


def up(data):
    return hub._req("/profiles", data, "application/zip")


a = up(zip_of({**BASE, "title": "Alpha"}))["id"]
b = up(zip_of({**BASE, "title": "Beta", "steamAppId": 222}))["id"]
check("valid upload accepted", a.startswith("alpha-"))
hub.like(b)
try:
    hub.like(b)
    check("one like per profile per address (a second is refused)", False)
except hub.HubError as e:
    check("one like per profile per address (a second is refused)", "slow down" in str(e))
check("new sort puts the newest first", [r["title"] for r in hub.browse("new")] == ["Beta", "Alpha"])
check("popular sort uses likes", hub.browse("popular")[0]["title"] == "Beta")
check("filter by game", [r["title"] for r in hub.browse("new", appid="222")] == ["Beta"])
check("text search matches title", [r["title"] for r in hub.browse("new", text="alp")] == ["Alpha"])
check("featured list starts empty", hub.browse("featured") == [])
try:
    hub._req("/profiles/%s/feature" % a, b"{}")
    check("feature needs the admin token", False)
except hub.HubError:
    check("feature needs the admin token", True)
import urllib.request  # noqa: E402
urllib.request.urlopen(urllib.request.Request(hub.HUB_URL + "/profiles/%s/feature" % a, data=b"{}", headers={"X-Admin": "s3cret"}))
check("admin can feature", [r["title"] for r in hub.browse("featured")] == ["Alpha"])

for name, data, expect in [
    ("not a zip", b"hello", "zip"),
    ("zip-slip path", zip_of(BASE, extra={"../evil.txt": "x"}), "unsafe"),
    ("no plunge.json", (lambda: (lambda b_: (zipfile.ZipFile(b_, "w").writestr("x.txt", "1"), b_.getvalue())[1])(io.BytesIO()))(), "plunge.json"),
    ("game content", zip_of(BASE, extra={"files/data.pak": b"x"}), "game content"),
    ("undeclared dll", zip_of(BASE, extra={"files/x.dll": b"MZ"}), "bundled"),
    ("untested", zip_of({**BASE, "tested": {}}), "tested"),
    ("leaked token", zip_of(BASE, files={"files/a.cfg": "Authorization: Bearer llc_k-abcdefghijklmnopqrstuvwxyz0123456789"}), "secret"),
]:
    try:
        up(data)
        check("hub rejects: " + name, False)
    except hub.HubError as e:
        check("hub rejects: " + name, expect in str(e).lower())
check("rejected uploads are not listed", len(hub.browse("new")) == 2)

got = hub.get(a)
check("get downloads into local profiles", (paths.PROFILES / a / "plunge.json").exists() and got["slug"] == a)
check("download is counted", [r for r in hub.browse("new") if r["id"] == a][0]["downloads"] == 1)
try:
    hub.get(a)
    check("get refuses to overwrite an existing profile", False)
except hub.HubError:
    check("get refuses to overwrite an existing profile", True)
try:
    hub.get("../../etc")
    check("get rejects a bad id", False)
except hub.HubError:
    check("get rejects a bad id", True)
mk("my-own-vr", {**BASE, "title": "Mine"}, files={"files/a.cfg": "y"})
pub = hub.publish("my-own-vr")
check("publish uploads a local profile", any(r["id"] == pub["id"] for r in hub.browse("new")))
mk("broken-vr", {**BASE, "tested": {}})
try:
    hub.publish("broken-vr")
    check("publish refuses an invalid local profile", False)
except hub.HubError:
    check("publish refuses an invalid local profile", True)

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
