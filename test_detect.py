"""Tests: finding games on any PC (many drives, engine markers, deep scan, old Steam library format), headset choice,
and the anti-cheat rule (never modify; launching an official-VR game untouched is allowed). Temp dirs only."""
import os
import sys
import tempfile
import time
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(tmp / "local")
os.environ["APPDATA"] = str(tmp / "roam")
os.environ["ProgramData"] = str(tmp / "pdata")
sys.path.insert(0, str(Path(__file__).parent))
from core import api, headset, paths, prompt, recipe, scanner, settings, stores, vrinfo  # noqa: E402

paths.ensure()
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


def mkexe(path, mb=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ" + b"\0" * (mb * 1024 * 1024))


# ---- two fake drives --------------------------------------------------------------------------------
D1, D2 = tmp / "C", tmp / "E"
D1.mkdir()
D2.mkdir()
stores.fixed_drives = lambda: [str(D1) + os.sep, str(D2) + os.sep]
check("common roots cover every drive", {str(Path(r).parent) for r in stores.common_roots() if r.endswith("Games")} >= {str(D1), str(D2)})

mkexe(D1 / "Games" / "Alpha" / "Alpha.exe")
mkexe(D2 / "Games" / "Beta" / "bin" / "Beta.exe")
mkexe(D2 / "XboxGames" / "Gamma" / "Content" / "Gamma.exe")
mkexe(D2 / "Epic Games" / "Delta" / "Delta.exe")
mkexe(D1 / "Program Files" / "EA Games" / "Echo" / "Echo.exe")
names = {g["name"] for g in stores.folders()}
check("games on both drives are found", {"Alpha", "Beta", "Delta", "Echo"} <= names)
check("Game Pass folders use the Content folder and the game's name", "Gamma" in names)

# ---- engine markers -------------------------------------------------------------------------------------
u = tmp / "mk" / "unity"
(u / "Game_Data" / "Managed").mkdir(parents=True)
(u / "UnityPlayer.dll").write_bytes(b"x")
ue = tmp / "mk" / "unreal"
mkexe(ue / "Proj" / "Binaries" / "Win64" / "Proj-Win64-Shipping.exe")
go = tmp / "mk" / "godot"
go.mkdir(parents=True)
(go / "game.pck").write_bytes(b"x")
mkexe(go / "game.exe")
chrome = tmp / "mk" / "chrome"
mkexe(chrome / "chrome.exe", 5)
check("Unity is recognised", stores.has_engine_marker(u))
check("Unreal is recognised", stores.has_engine_marker(ue))
check("Godot is recognised", stores.has_engine_marker(go))
check("ordinary software is not a game", not stores.has_engine_marker(chrome))
check("a .pck without a program is not a game", not stores.has_engine_marker(tmp / "mk" / "nothing"))
check("junk names are filtered from installed apps", all(stores.JUNK_NAME.search(n) for n in ["Microsoft Visual C++ 2019", "NVIDIA Graphics Driver", "Google Chrome", "Epic Games Launcher", "Python 3.13"]))
check("real game names are not filtered", not any(stores.JUNK_NAME.search(n) for n in ["Hades", "MXGP 2020", "Counter-Strike 2", "Hollow Knight"]))

# ---- deep scan ----------------------------------------------------------------------------------------------
dd = tmp / "deep"
dd.mkdir()
mkexe(dd / "Stuff" / "RacingGame" / "Racing" / "Binaries" / "Win64" / "Racing-Win64-Shipping.exe")
(dd / "Misc" / "UnityThing").mkdir(parents=True)
(dd / "Misc" / "UnityThing" / "UnityPlayer.dll").write_bytes(b"x")
mkexe(dd / "Misc" / "UnityThing" / "Thing.exe")
(dd / "Misc" / "LibOnly").mkdir(parents=True)
(dd / "Misc" / "LibOnly" / "UnityPlayer.dll").write_bytes(b"x")          # an engine DLL with no game program: not a game
(dd / "Windows" / "System32" / "Hidden").mkdir(parents=True)
(dd / "Windows" / "System32" / "Hidden" / "UnityPlayer.dll").write_bytes(b"x")
(dd / "a" / "b" / "c" / "d" / "e" / "f" / "TooDeep").mkdir(parents=True)
(dd / "a" / "b" / "c" / "d" / "e" / "f" / "TooDeep" / "UnityPlayer.dll").write_bytes(b"x")
r = stores.deep_scan(max_seconds=20, max_depth=5, drives=[str(dd)])
found = {Path(p).name for p in r["found"]}
check("deep scan finds an Unreal game and reports its folder, not the exe's", "RacingGame" in found)
check("deep scan finds a Unity game", "UnityThing" in found)
check("deep scan skips Windows folders", "Hidden" not in found and "System32" not in found)
check("deep scan ignores an engine DLL with no game program", "LibOnly" not in found)
check("deep scan respects the depth limit", "TooDeep" not in found)
check("deep scan reports time and no timeout", r["seconds"] >= 0 and r["timedOut"] is False)
r2 = stores.deep_scan(max_seconds=20, drives=[str(dd)])
check("a second deep scan doesn't list the same games again", r2["found"] == [])
check("deep scan results are remembered", len(settings.get("foundGames", [])) == 2)
r3 = stores.deep_scan(max_seconds=0.0, drives=[str(dd)])
check("deep scan stops at its time limit", r3["timedOut"] is True)
found_games = {g["name"] for g in stores.folders()}
check("remembered deep-scan games show up in the normal scan", {"RacingGame", "UnityThing"} <= found_games)

# ---- Steam library files ---------------------------------------------------------------------------------------
st = tmp / "steam"
(st / "steamapps").mkdir(parents=True)
lib2, lib3 = tmp / "SteamLibNew", tmp / "SteamLibOld"
(lib2 / "steamapps").mkdir(parents=True)
(lib3 / "steamapps").mkdir(parents=True)
vdf = '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\t\t"%s"\n}\n' % (str(lib2).replace("\\", "\\\\"), str(lib3).replace("\\", "\\\\"))
(st / "steamapps" / "libraryfolders.vdf").write_text(vdf)
libs = scanner.library_dirs(st)
check("new and old libraryfolders.vdf layouts are both read", {str(x.parent) for x in libs} >= {str(st), str(lib2), str(lib3)})

# ---- headset -----------------------------------------------------------------------------------------------------
check("no headset chosen at first", headset.get() is None)
check("runtime vendors map to a headset guess", headset.detect("meta") == "meta-link" and headset.detect("steamvr") == "steamvr"
      and headset.detect("virtualdesktop") == "virtual-desktop" and headset.detect("pico") == "pico" and headset.detect("none") is None)
headset.set_type("virtual-desktop")
check("the choice is remembered", headset.get() == "virtual-desktop" and settings.get("headset") == "virtual-desktop")
try:
    headset.set_type("hologram")
    check("an unknown headset is rejected", False)
except ValueError:
    check("an unknown headset is rejected", True)
check("every type has a readable label", all(len(v) > 8 for v in headset.TYPES.values()))
check("UEVR runtime advice follows the headset", headset.uevr_runtime("meta-link") == "OpenXR" and "OpenVR" in headset.uevr_runtime("steamvr"))
check("brief line names the headset and runtime", "Virtual Desktop" in headset.brief_line("virtual-desktop", "virtualdesktop") and "virtualdesktop" in headset.brief_line("virtual-desktop", "virtualdesktop"))
check("'no headset' tells the agent to use the null driver", "null driver" in headset.brief_line("none", "meta"))
check("not chosen is said plainly", "not chosen" in headset.brief_line(None, "meta"))
info = api.set_headset("meta-link")
check("api exposes the choice, a guess and all choices", info["type"] == "meta-link" and len(info["choices"]) == len(headset.TYPES) and "detected" in info)
game = {"name": "Foo", "appid": "1", "store": "Steam", "engine": "unity", "path": "C:/g", "exe": None, "anticheat": [], "buildId": "5"}
p = prompt.build(game, "plunge-cli tool", paths.PROFILES, "", None, "skip", headset.brief_line("meta-link", "meta"))
check("the AI brief carries the headset", "Meta Quest" in p and "- Headset:" in p)

# ---- anti-cheat rule ----------------------------------------------------------------------------------------------------
route = {"id": "agent-unity", "label": "x", "maturity": "m", "note": "n"}
vac = {"appid": "100", "name": "ProtectedVR", "path": str(tmp / "pv"), "exe": None, "engine": "unity", "anticheat": ["Easy Anti-Cheat"],
       "status": "blocked", "why": "Uses anti-cheat.", "route": route, "launch": {"kind": "steam", "appid": "100"}, "store": "Steam"}
novr = {**vac, "appid": "101", "name": "ProtectedNoVR"}
(tmp / "pv").mkdir()
vrinfo._save({"100": {"level": "supported", "vac": False, "t": time.time()}, "101": {"level": None, "vac": False, "t": time.time()}})
api._STATE.update(games=[vac, novr], demo=False)
launched = []
recipe.launch = lambda game, rc, *a, **k: launched.append((game["appid"], rc)) or {"mode": "solo", "started": True, "how": "steam"}
r = api.play("100", None, "solo", None, None)
check("an anti-cheat game with official VR can be launched as it ships", r["steps"][-1] == "Started the game" and launched[-1] == ("100", {}))
check("...and nothing was installed for it", not recipe.is_installed("100"))
try:
    api.play("100", "some-profile", "solo", None, None)
    check("a profile can never be installed into an anti-cheat game", False)
except ValueError as e:
    check("a profile can never be installed into an anti-cheat game", "anti-cheat" in str(e).lower())
try:
    api.play("101", None, "solo", None, None)
    check("an anti-cheat game without official VR is refused", False)
except ValueError:
    check("an anti-cheat game without official VR is refused", True)
try:
    api.install_profile("some-profile", "100")
    check("the agent tool cannot install into an anti-cheat game", False)
except ValueError as e:
    check("the agent tool cannot install into an anti-cheat game", "anti-cheat" in str(e).lower())      # refused for THAT reason, not a missing profile
try:
    api.launch_game("100")
    check("the agent launch tool refuses anti-cheat games (it is for testing builds)", False)
except ValueError:
    check("the agent launch tool refuses anti-cheat games (it is for testing builds)", True)
vacgame = {**vac, "appid": "102", "name": "VacVR", "anticheat": [], "status": "experimental", "launch": {"kind": "steam", "appid": "102"}}
vrinfo._save({"102": {"level": "supported", "vac": True, "t": time.time()}})
api._STATE.update(games=[vacgame], demo=False)
check("a VAC game with official VR is still launchable untouched", api.play("102", None, "solo", None, None)["steps"][-1] == "Started the game")

# ---- scan report ------------------------------------------------------------------------------------------------------------
rep = api.scan_report()
labels = [r_["label"] for r_ in rep["rows"]]
check("scan report lists Steam, other launchers, drives and added folders", {"Steam", "Drives scanned", "Epic manifests", "Folders you added", "Found by deep scan"} <= set(labels))

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
