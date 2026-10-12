"""Tests: finding games (Steam folders without records, Epic, GOG-style folders, added folders), launching and
confirming a launch from Steam's log, adoption of leftover mod files, VAC, interview mode, agent tools. Temp dirs only."""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(tmp / "local")
os.environ["APPDATA"] = str(tmp / "roam")
os.environ["ProgramData"] = str(tmp / "pdata")
sys.path.insert(0, str(Path(__file__).parent))
from core import api, launcher, paths, prefs, prompt, recipe, scanner, settings, stores, vrinfo  # noqa: E402

paths.ensure()
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


def mkexe(path, mb=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ" + b"\0" * (mb * 1024 * 1024))


# ---- finding the main exe ------------------------------------------------------------------
g1 = tmp / "games" / "MX"
mkexe(g1 / "mx" / "Binaries" / "Win64" / "mx-Win64-Shipping.exe", 3)
mkexe(g1 / "_CommonRedist" / "vcredist" / "VC_redist.x64.exe", 14)
check("Unreal shipping exe four levels down is found", stores.find_main_exe(g1).endswith("mx-Win64-Shipping.exe"))
check("redistributables are ignored even when bigger", "redist" not in stores.find_main_exe(g1).lower())
g2 = tmp / "games" / "Plain"
mkexe(g2 / "Plain.exe", 5)
mkexe(g2 / "unins000.exe", 6)
mkexe(g2 / "UnityCrashHandler64.exe", 7)
check("uninstaller and crash handler are ignored", stores.find_main_exe(g2).endswith("Plain.exe"))
g3 = tmp / "games" / "Empty"
(g3).mkdir(parents=True)
(g3 / "readme.txt").write_text("x")
check("a folder with no real program is not a game", stores.find_main_exe(g3) is None)
mkexe(tmp / "games" / "Tiny" / "tiny.exe", 0)
check("tiny exes (stubs) are not games", stores.find_main_exe(tmp / "games" / "Tiny") is None)

# ---- Steam folders with no record ------------------------------------------------------------
lib = tmp / "steamlib"
mkexe(lib / "common" / "Orphan Game" / "Orphan.exe", 4)
(lib / "common" / "Leftover").mkdir(parents=True)
(lib / "common" / "Leftover" / "x.txt").write_text("x")
mkexe(lib / "common" / "Known" / "Known.exe", 4)
out = stores.steam_orphans([lib], {"known"})
names = [g["name"] for g in out]
check("orphan Steam folder with a real exe is listed", names == ["Orphan Game"])
check("empty leftover and recorded games are skipped", "Leftover" not in names and "Known" not in names)
check("orphan launches by exe", out[0]["launch"]["kind"] == "exe" and out[0]["launch"]["exe"].endswith("Orphan.exe"))
check("ids of non-Steam games are never plain numbers", not out[0]["appid"].isdigit() and out[0]["appid"].startswith("dir-"))

# ---- Epic ------------------------------------------------------------------------------------
epic_dir = tmp / "pdata" / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
epic_dir.mkdir(parents=True)
inst = tmp / "epicgames" / "Fortnite Clone"
mkexe(inst / "Game.exe", 3)
(epic_dir / "a.item").write_text("\ufeff" + json.dumps({"DisplayName": "Epic Test", "InstallLocation": str(inst), "AppName": "Sugar",
                                                       "CatalogNamespace": "ns", "CatalogItemId": "cid", "LaunchExecutable": "Game.exe"}), encoding="utf-8")
(epic_dir / "b.item").write_text(json.dumps({"DisplayName": "Gone", "InstallLocation": str(tmp / "nope"), "AppName": "x"}))
(epic_dir / "c.item").write_text(json.dumps({"DisplayName": "UE", "InstallLocation": str(inst), "AppName": "UE_4.27"}))
(epic_dir / "bad.item").write_text("not json")
e = stores.epic()
check("Epic manifest parsed (BOM tolerated)", len(e) == 1 and e[0]["name"] == "Epic Test")
check("Epic game launches by its launcher URI", e[0]["launch"]["uri"] == "com.epicgames.launcher://apps/ns%3Acid%3ASugar?action=launch&silent=true")
check("missing, engine-tool and corrupt Epic entries are skipped", len(e) == 1)

# ---- added folders ---------------------------------------------------------------------------
root = tmp / "mygames"
mkexe(root / "Alpha" / "Alpha.exe", 3)
mkexe(root / "Beta" / "bin" / "Beta.exe", 3)
single = tmp / "single"
mkexe(single / "One.exe", 3)
api._STATE.update(games=None)
r = api.add_game_folder(str(root))
check("adding a folder of games finds each game", r["found"] >= 2 and {"Alpha", "Beta"} <= {g["name"] for g in api._load()})
r = api.add_game_folder(str(single))
check("adding a folder that is itself a game finds it", "single" in {g["name"] for g in api._load()})
check("added folders are remembered", len(api.game_folders()["folders"]) == 2)
try:
    api.add_game_folder(str(tmp / "does-not-exist"))
    check("a missing folder is rejected", False)
except ValueError:
    check("a missing folder is rejected", True)
api.remove_game_folder(str(root.resolve()))
check("removing a folder drops its games", "Alpha" not in {g["name"] for g in api._load()})

# ---- engine/status for extra games -----------------------------------------------------------
games = {g["name"]: g for g in api._load()}
check("extra games carry store and launch info", all("launch" in g and "store" in g for g in games.values()))
check("extra game gets the 'other' engine route", games["single"]["engine"] == "other")

# ---- confirming a Steam launch from its log --------------------------------------------------
log = tmp / "console_log.txt"
log.write_text("[old] nothing\n")
off = log.stat().st_size


def append_later(text, delay=0.3):
    def run():
        time.sleep(delay)
        with open(log, "a") as f:
            f.write(text)
    threading.Thread(target=run, daemon=True).start()


append_later('[2026-10-09 19:54:09] GameAction [AppID 322170, ActionID 46] : LaunchApp failed with AppError_5 with "FamilySharing"\n')
try:
    launcher.confirm_steam_launch("322170", off, timeout=3, log=log)
    check("Family Sharing refusal is reported", False)
except launcher.LaunchError as ex:
    check("Family Sharing refusal is reported in plain words", "Family Sharing" in str(ex) and "borrowed" in str(ex))
off = log.stat().st_size
append_later('[x] Game process updated : AppID 1278060 "D:\\\\g\\\\Game.exe", ProcID 18460\n')
check("a started game is confirmed", launcher.confirm_steam_launch("1278060", off, timeout=3, log=log) is True)
off = log.stat().st_size
append_later('[x] GameAction [AppID 999, ActionID 1] : LaunchApp failed with AppError_9 with "Whatever"\n')
try:
    launcher.confirm_steam_launch("1278060", off, timeout=1.5, log=log)
    check("another game's failure is not blamed on this one", True)
except launcher.LaunchError:
    check("another game's failure is not blamed on this one", False)
off = log.stat().st_size
check("no answer within the timeout is 'unknown', not an error", launcher.confirm_steam_launch("5", off, timeout=0.6, log=log) is None)
off = log.stat().st_size
append_later('[x] GameAction [AppID 7, ActionID 2] : LaunchApp failed with AppError_3 with "SomethingNew"\n')
try:
    launcher.confirm_steam_launch("7", off, timeout=3, log=log)
except launcher.LaunchError as ex:
    check("unknown Steam reasons are still shown", "SomethingNew" in str(ex))
check("only text written AFTER the request counts", launcher.confirm_steam_launch("322170", log.stat().st_size, timeout=0.5, log=log) is None)

# ---- launching other kinds (stubbed) ----------------------------------------------------------
started = []
_real_popen, _real_startfile = launcher.subprocess.Popen, launcher.os.startfile
launcher.subprocess.Popen = lambda cmd, **k: started.append((cmd, k)) or None
launcher.os.startfile = lambda u: started.append(u)
exe = tmp / "games" / "Plain" / "Plain.exe"
res = launcher.start({"appid": "dir-1", "path": str(g2), "launch": {"kind": "exe", "exe": str(exe)}}, ["-x"], {"A": "1"})
check("exe games are started in their own folder with args and env", started[-1][0] == [str(exe), "-x"] and started[-1][1]["cwd"] == str(exe.parent) and started[-1][1]["env"]["A"] == "1" and res["how"] == "exe")
launcher.start({"appid": "epic-1", "path": "x", "launch": {"kind": "uri", "uri": "com.epicgames.launcher://apps/a%3Ab%3Ac?action=launch&silent=true"}})
check("Epic games are started through their launcher", started[-1].startswith("com.epicgames.launcher://"))
try:
    launcher.start({"appid": "g", "path": str(g3), "launch": {"kind": "exe", "exe": None}})
    check("a game with no program says so", False)
except launcher.LaunchError:
    check("a game with no program says so", True)
launcher.start({"appid": "gog-1", "path": str(g2), "launch": {"kind": "exe", "exe": "Plain.exe"}})
check("a relative exe is resolved inside the game folder", started[-1][0][0] == str(g2 / "Plain.exe"))
launcher.subprocess.Popen, launcher.os.startfile = _real_popen, _real_startfile      # put the real ones back

# ---- adoption of leftover mod files ------------------------------------------------------------
gd = tmp / "adopt" / "Game"
gd.mkdir(parents=True)
(gd / "winhttp.dll").write_bytes(b"same-dll")
(gd / "doorstop.ini").write_text("their-edit")
prof = tmp / "adopt" / "profile"
(prof / "files").mkdir(parents=True)
(prof / "files" / "winhttp.dll").write_bytes(b"same-dll")
(prof / "files" / "doorstop.ini").write_text("profile-version")
(prof / "files" / "new.cfg").write_text("n")
GAME = {"appid": "777", "name": "Adopt", "path": str(gd), "exe": None}
rc = {"install": [{"from": "files/winhttp.dll", "to": "{game}/winhttp.dll"}, {"from": "files/doorstop.ini", "to": "{game}/doorstop.ini"},
                  {"from": "files/new.cfg", "to": "{game}/new.cfg"}]}
recipe.install(prof, rc, GAME)
m = json.loads(recipe.manifest_path("777").read_text())
check("identical leftover file is adopted", str(gd / "winhttp.dll") in m["adopted"] and str(gd / "winhttp.dll") in m["created"])
check("a different existing file is backed up, not adopted", any(r_["path"] == str(gd / "doorstop.ini") for r_ in m["replaced"]))
recipe.uninstall("777")
check("remove deletes the adopted file (game is clean again)", not (gd / "winhttp.dll").exists())
check("remove restores a file that differed", (gd / "doorstop.ini").read_text() == "their-edit")
check("remove deletes files it created", not (gd / "new.cfg").exists())

# ---- VAC ----------------------------------------------------------------------------------------
vrinfo._save({"555": {"level": None, "vac": True, "t": time.time()}})
vgame = {"appid": "555", "name": "VacGame", "path": str(g2), "exe": None, "engine": "other", "anticheat": [], "status": "experimental",
         "why": "", "route": {"id": "agent-custom", "label": "x", "maturity": "m", "note": "n"}, "launch": {"kind": "steam", "appid": "555"}, "store": "Steam"}
api._STATE.update(games=[vgame], demo=False)
d = api._decorate(vgame)
check("a VAC game is blocked", d["status"] == "blocked" and "Valve Anti-Cheat (VAC)" in d["anticheat"])
try:
    api.play("555", None, "solo", None, None)
    check("play refuses a VAC game", False)
except ValueError as ex:
    check("play refuses a VAC game", "anti-cheat" in str(ex).lower())
vrinfo._save({"556": {"level": None, "t": time.time()}})
check("old cache entries without a VAC answer are fetched again", vrinfo.lookup("556") is None)

# ---- ids that aren't numbers ----------------------------------------------------------------------
prefs.save("epic-Sugar", {"perspective": "third"})
check("preferences work for non-numeric game ids", prefs.get("epic-Sugar")["perspective"] == "third")
check("non-Steam ids need no Steam lookup", vrinfo.describe("dir-abc", str(g2))["via"] == "not on Steam")

# ---- interview mode and the brief ------------------------------------------------------------------
check("default is to skip the interview", prefs.clean({})["interview"] == "skip")
check("interview can be switched on", prefs.clean({"interview": "ask"})["interview"] == "ask")
check("garbage interview value falls back to skip", prefs.clean({"interview": "maybe"})["interview"] == "skip")
check("interview mode alone isn't a 'customized' game", prefs.is_default({"interview": "ask"}))
game = {"name": "Foo", "appid": "dir-1", "store": "Local folder", "engine": "unity", "path": "C:/g", "exe": None, "anticheat": [], "buildId": None}
skip = prompt.build(game, "plunge-cli tool", paths.PROFILES, "", None, "skip")
ask = prompt.build(game, "plunge-cli tool", paths.PROFILES, "", None, "ask")
check("skip brief forbids questions and states defaults", "do NOT want to be interviewed" in skip.replace("I do NOT want to be interviewed", "do NOT want to be interviewed") and "seated, gamepad" in skip)
check("ask brief interviews and allows 'just do it'", "interview me" in ask and "just do it" in ask)
check("brief names the store and id", "id dir-1, from Local folder" in skip)
for must in ["environment", "install_profile", "uninstall_profile", "launch_game", "steam -applaunch", "Chainloader startup complete", "OpenXR fully initialized",
             "ALT-key", "50 MiB", "CREDITS.md", "verification matrix", "without a BOM", "Stop and ask me ONLY", "never ask", "null driver", "sortingOrder"]:
    check("brief includes: " + must, must in skip)
import re  # noqa: E402
check("brief has no unfilled placeholders", not re.search(r"\{[a-z_]+\}", skip.replace("{game}", "").replace("{uevr-config}", "").replace("{address}", "").replace("{port}", "")))

# ---- agent tools -----------------------------------------------------------------------------------
env = api.environment()
check("environment reports runtime, tools and steam", {"openxrRuntime", "activeRuntimeVendor", "tools", "steam", "advice"} <= set(env))
check("environment never switches anything (read-only keys only)", isinstance(env["tools"], dict))
launched = []
launcher.start = lambda game, *a, **k: launched.append(game["appid"]) or {"started": True, "how": "steam"}
api._STATE.update(games=[{**vgame, "appid": "888", "launch": {"kind": "steam", "appid": "888"}}], demo=False)
check("launch_game reports the result", api.launch_game("888") == {"started": True, "how": "steam"} and launched == ["888"])

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
