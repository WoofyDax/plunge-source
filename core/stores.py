"""Find installed games beyond Steam's own records. Read-only: nothing is changed.

Sources, from cheap to expensive:
  1. Steam game folders that have no Steam record (moved or leftover installs)
  2. Epic (launcher manifests), GOG, Ubisoft Connect, EA (registry)
  3. Xbox/Game Pass and other common game folders on EVERY fixed or removable drive
  4. Programs listed in Windows' installed-apps registry that contain a game engine (catches setup.exe installs,
     Battle.net games, and most others)
  5. Folders the player added by hand, and the results of a drive-wide "deep scan"

Each game carries a `launch` spec: {"kind": "steam"|"uri"|"exe", ...}. Ids look like 'epic-<AppName>', 'gog-<id>',
'ubi-<id>', 'ea-<hash>', 'dir-<hash>' so they never collide with numeric Steam app ids.
"""
import ctypes
import hashlib
import json
import os
import re
import time
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from . import settings

SKIP_EXE = re.compile(r"(unins|uninst|crash|redist|vc_?redist|dxsetup|dotnet|setup|installer|updater|launcher_helper|"
                      r"easyanticheat|battleye|beservice|werfault|cefprocess|notification_helper|UnityCrashHandler)", re.I)
NOT_GAME_DIRS = {"launcher", "directxredist", "gamesave", "common", "redist", "_commonredist", "steamworks shared"}
SKIP_DIRS = {"_commonredist", "redist", "vcredist", "directx", "dotnet", "__installer", "support", "engine"}
# apps that show up in "installed apps" but are never games
JUNK_NAME = re.compile(r"(microsoft|windows|visual c\+\+|\.net |nvidia|\bamd\b|intel|realtek|java|python|node\.?js|\bgit\b|visual studio|"
                       r"redistributable|runtime|driver|^steam$|epic games launcher|ubisoft connect|ea app|battle\.net|gog galaxy|discord|"
                       r"chrome|firefox|edge|adobe|office|7-zip|winrar|obs studio|unity hub|unreal engine|blender|plunge)", re.I)
ROOT_TEMPLATES = ["Games", "XboxGames", "Epic Games", r"Program Files\Epic Games", "GOG Games", r"Games\GOG Games",
                  r"Program Files (x86)\GOG Galaxy\Games", r"Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games",
                  r"Program Files\Ubisoft\Ubisoft Game Launcher\games", "Origin Games", r"Program Files\EA Games",
                  r"Program Files (x86)\EA Games", r"Program Files (x86)\Origin Games", "Riot Games", r"Program Files\Rockstar Games",
                  r"Program Files (x86)\Rockstar Games", "itch", r"Games\itch"]
DEEP_SKIP = {"windows", "winsxs", "installer", "temp", "tmp", "cache", "logs", "$sysreset", "onedrivetemp", "dropbox", "node-gyp", "$recycle.bin", "system volume information", "windowsapps", "appdata", "node_modules", ".git", "programdata",
             "perflogs", "recovery", "common files", "steamapps", "$windows.~bt", "msocache", "drivers"}


def gid(prefix, text):
    return "%s-%s" % (prefix, hashlib.sha1(str(text).lower().encode()).hexdigest()[:8])


# ---- helpers ------------------------------------------------------------------------------------
def fixed_drives():
    """Drive roots like 'C:\\' that are local disks (internal or USB), so games on D:, E: ... are found too."""
    out = []
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if mask & (1 << i):
                root = "%s:\\" % chr(65 + i)
                if ctypes.windll.kernel32.GetDriveTypeW(root) in (2, 3):     # removable (USB) or fixed
                    out.append(root)
    except (AttributeError, OSError):
        pass
    return out or [os.environ.get("SystemDrive", "C:") + "\\"]


def common_roots():
    return [os.path.join(d, t) for d in fixed_drives() for t in ROOT_TEMPLATES]


def find_main_exe(folder, max_depth=4):
    """The most likely game executable: an Unreal '*-Win64-Shipping.exe' if there is one (they sit up to four levels
    down, in <Game>\\Binaries\\Win64), otherwise the biggest sensible .exe within `max_depth` levels."""
    best, best_size, shipping, shipping_size = None, 0, None, 0
    base = Path(folder)
    if not base.exists():
        return None
    seen = 0
    for cur, dirs, files in os.walk(base):
        depth = len(Path(cur).relative_to(base).parts)
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS] if depth < max_depth else []
        for f in files:
            seen += 1
            if seen > 8000:
                break
            if f.lower().endswith(".exe") and not SKIP_EXE.search(f):
                try:
                    size = (Path(cur) / f).stat().st_size
                except OSError:
                    continue
                if f.lower().endswith("-win64-shipping.exe") and size > shipping_size:
                    shipping, shipping_size = str(Path(cur) / f), size
                if size > best_size:
                    best, best_size = str(Path(cur) / f), size
    pick, size = (shipping, shipping_size) if shipping else (best, best_size)
    return pick if size > 1_000_000 else None


def has_engine_marker(folder, max_depth=4, max_entries=3000):
    """True if the folder looks like a Unity, Unreal or Godot game (cheap bounded walk)."""
    base, seen = Path(folder), 0
    if not base.is_dir():
        return False
    for cur, dirs, files in os.walk(base):
        if len(Path(cur).relative_to(base).parts) >= max_depth:
            dirs[:] = []
        low = [f.lower() for f in files]
        if "unityplayer.dll" in low or "gameassembly.dll" in low or any(f.endswith("-win64-shipping.exe") for f in low):
            return True
        if any(f.endswith(".pck") for f in low) and any(f.endswith(".exe") for f in low):
            return True
        if Path(cur).name.lower().endswith("_data") and (Path(cur) / "Managed").exists():
            return True
        seen += len(files) + len(dirs)
        if seen > max_entries:
            return False
    return False


def _game(prefix, key, name, path, launch, store=None):
    gid_ = gid(prefix, key) if prefix in ("dir", "ea") else "%s-%s" % (prefix, key)
    labels = {"epic": "Epic", "gog": "GOG", "ubi": "Ubisoft", "ea": "EA", "dir": "Local folder"}
    return {"appid": gid_, "name": name, "path": str(path), "launch": launch, "store": store or labels.get(prefix, prefix)}


def _reg_subkeys(hive, path, view=0):
    if not winreg:
        return
    try:
        base = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view)
    except OSError:
        return
    with base:
        for i in range(winreg.QueryInfoKey(base)[0]):
            try:
                name = winreg.EnumKey(base, i)
                with winreg.OpenKey(base, name, 0, winreg.KEY_READ | view) as k:
                    vals = {}
                    for j in range(winreg.QueryInfoKey(k)[1]):
                        vn, vv, _ = winreg.EnumValue(k, j)
                        vals[vn] = vv
                yield name, vals
            except OSError:
                continue


def _reg_both_views(hive, path):
    """Read a registry path in both the 64-bit and 32-bit views (older launchers write to the 32-bit one)."""
    seen = set()
    for view in (getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)) if winreg else ():
        for name, vals in _reg_subkeys(hive, path, view):
            if name not in seen:
                seen.add(name)
                yield name, vals


# ---- launchers -----------------------------------------------------------------------------------
def epic():
    out = []
    root = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    for f in root.glob("*.item") if root.exists() else []:
        try:
            m = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        loc = m.get("InstallLocation")
        if not loc or not Path(loc).exists() or m.get("bIsIncompleteInstall") or str(m.get("AppName", "")).startswith("UE_"):
            continue
        uri = "com.epicgames.launcher://apps/%s%%3A%s%%3A%s?action=launch&silent=true" % (
            m.get("CatalogNamespace"), m.get("CatalogItemId"), m.get("AppName"))
        exe = Path(loc) / m["LaunchExecutable"] if m.get("LaunchExecutable") else None
        g = _game("epic", m.get("AppName"), m.get("DisplayName") or Path(loc).name, loc, {"kind": "uri", "uri": uri})
        g["exeHint"] = str(exe) if exe and exe.exists() else None
        out.append(g)
    return out


def gog():
    out = []
    if not winreg:
        return out
    for key in (r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"):
        for name, v in _reg_both_views(winreg.HKEY_LOCAL_MACHINE, key):
            path = v.get("path")
            if path and Path(path).exists():
                exe = v.get("launchCommand") or v.get("exe")
                out.append(_game("gog", v.get("gameID", name), v.get("gameName") or Path(path).name, path, {"kind": "exe", "exe": exe}))
    return out


def ubisoft():
    out = []
    for name, v in _reg_both_views(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Ubisoft\Launcher\Installs") if winreg else ():
        d = v.get("InstallDir")
        if d and Path(d).exists():
            out.append(_game("ubi", name, Path(str(d).rstrip("\\/")).name, d, {"kind": "uri", "uri": "uplay://launch/%s/0" % name}))
    return out


def ea():
    out = []
    for key in (r"SOFTWARE\WOW6432Node\EA Games", r"SOFTWARE\EA Games", r"SOFTWARE\WOW6432Node\Origin Games"):
        for name, v in _reg_both_views(winreg.HKEY_LOCAL_MACHINE, key) if winreg else ():
            d = v.get("Install Dir") or v.get("InstallDir")
            if d and Path(d).exists():
                out.append(_game("ea", d, name, d, {"kind": "exe", "exe": None}))
    return out


def installed_apps():
    """Windows' list of installed programs, kept only when the folder holds a game engine (so Chrome, drivers and
    other software are never listed). This is how Battle.net, setup.exe and many store installs get found."""
    out = []
    if not winreg:
        return out
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                       (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                       (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")):
        for _, v in _reg_subkeys(hive, path):
            name, loc = v.get("DisplayName"), str(v.get("InstallLocation") or "").strip().strip('"')
            if not name or not loc or JUNK_NAME.search(name):
                continue
            p = Path(loc)
            if not p.is_dir() or str(p).lower().startswith(os.environ.get("windir", r"C:\Windows").lower()):
                continue
            if has_engine_marker(p):
                exe = find_main_exe(p)
                if exe:
                    out.append(_game("dir", p.resolve(), name, p, {"kind": "exe", "exe": exe}, store="Installed app"))
    return out


def _candidate_dirs(root):
    root = Path(root)
    if not root.exists() or not root.is_dir():
        return []
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if d.name.lower() in NOT_GAME_DIRS or d.name.startswith("."):
            continue
        content = d / "Content"                       # Xbox/Game Pass keeps the game in <Name>\Content
        out.append(content if content.is_dir() and any(content.glob("*.exe")) else d)
    return out


def folders(known=()):
    """Local folders: common game roots on every drive, plus anything the player added or a deep scan found."""
    known = {str(Path(p).resolve()).lower() for p in known}
    out = []
    added = settings.get("gameFolders", [])
    for root in common_roots() + added:
        p = Path(root)
        if not p.is_dir():
            continue
        # a folder the player added may itself be a game (a program right inside it), or a root that holds games
        own_exe = find_main_exe(p, max_depth=0) if root in added else None
        for d in ([p] if own_exe else _candidate_dirs(p)):
            if str(d.resolve()).lower() in known:
                continue
            exe = find_main_exe(d)
            if exe:
                out.append(_game("dir", d.resolve(), (d.parent.name if d.name == "Content" else d.name), d, {"kind": "exe", "exe": exe}))
    for d in settings.get("foundGames", []):          # exact game folders from a deep scan
        p = Path(d)
        exe = find_main_exe(p) if p.is_dir() else None
        if exe and str(p.resolve()).lower() not in known:
            out.append(_game("dir", p.resolve(), p.name, p, {"kind": "exe", "exe": exe}, store="Found by deep scan"))
    return out


def steam_orphans(libs, known_installdirs):
    """Folders inside Steam's `common` that have no appmanifest (Steam doesn't list them, but the files are there)."""
    out = []
    for lib in libs:
        common = Path(lib) / "common"
        if not common.exists():
            continue
        for d in common.iterdir():
            if not d.is_dir() or d.name.lower() in known_installdirs or d.name.lower() in NOT_GAME_DIRS:
                continue
            exe = find_main_exe(d)
            if exe:
                g = _game("dir", d.resolve(), d.name, d, {"kind": "exe", "exe": exe}, store="Steam folder (no Steam record)")
                out.append(g)
    return out


EMULATORS = {"dolphin": "GameCube / Wii", "pcsx2": "PlayStation 2", "rpcs3": "PlayStation 3", "duckstation": "PlayStation", "ppsspp": "PSP",
             "vita3k": "PS Vita", "cemu": "Wii U", "yuzu": "Switch", "ryujinx": "Switch", "suyu": "Switch", "citra": "3DS", "lime3ds": "3DS",
             "melonds": "DS", "desmume": "DS", "mgba": "Game Boy Advance", "retroarch": "many systems", "bizhawk": "many systems", "mesen": "NES / SNES",
             "snes9x": "SNES", "project64": "Nintendo 64", "mupen64": "Nintendo 64", "flycast": "Dreamcast", "redream": "Dreamcast", "xemu": "Xbox",
             "xenia": "Xbox 360", "ares": "many systems", "higan": "many systems", "mame": "arcade", "scummvm": "classic adventures", "dosbox": "DOS"}


def emulator_of(exe):
    """The console an emulator program is for ('GameCube / Wii'), or None when the program is not a known emulator."""
    stem = Path(str(exe)).stem.lower().replace(" ", "").replace("-", "").replace("_", "")
    for key, system in EMULATORS.items():
        if stem.startswith(key) or key in stem:
            return system
    return None


def programs():
    """Games the player added as a program: an emulator plus a game file, or any program that is a game. Never scanned for, only added by hand."""
    out = []
    for p in settings.get("programs", []):
        try:
            exe = Path(p["exe"])
            if not exe.is_file():
                continue
            rom = p.get("rom") or None
            if rom and not Path(rom).is_file():
                continue
            system = emulator_of(exe)
            args = ([rom] if rom else []) + list(p.get("args") or [])
            out.append({"appid": p["id"], "name": p["name"], "path": str(exe.parent), "store": "Emulator" if system else "Program",
                        "launch": {"kind": "exe", "exe": str(exe), "args": args}, "exeHint": str(exe), "rom": rom,
                        "emulator": system, "program": True})
        except (KeyError, TypeError, OSError):
            continue
    return out


def all_extra(steam_libs, steam_installdirs, steam_paths):
    games = programs()                               # added by hand, so they come first (two game files can share one emulator folder)
    games += steam_orphans(steam_libs, {d.lower() for d in steam_installdirs})
    games += epic() + gog() + ubisoft() + ea()
    known = list(steam_paths) + [g["path"] for g in games]
    games += installed_apps()
    known += [g["path"] for g in games]
    games += folders(known)
    seen, out = set(), []
    for g in games:                                  # one entry per real folder (and per game file, for programs)
        k = str(Path(g["path"]).resolve()).lower() + ("|" + str(g.get("rom") or g["appid"]) if g.get("program") else "")
        if k not in seen:
            seen.add(k)
            out.append(g)
    return out


# ---- deep scan --------------------------------------------------------------------------------------
def _game_root_from_exe(exe):
    """An Unreal exe sits in <Game>\\<Project>\\Binaries\\Win64; the game folder is three levels up."""
    exe = Path(exe)
    if len(exe.parents) > 3 and exe.parents[1].name.lower() == "binaries":
        return exe.parents[3]
    return exe.parent


def deep_scan(max_seconds=150, max_depth=4, drives=None, stop=None):
    """Walk the drives for game engines and remember what was found. Slower and broader than the normal scan, so the
    player starts it on purpose. Returns {"found": [paths], "seconds": s, "timedOut": bool}."""
    start, found, timed_out = time.time(), [], False
    known = {str(Path(g).resolve()).lower() for g in settings.get("foundGames", [])}
    for drive in (drives or fixed_drives()):
        for cur, dirs, files in os.walk(drive):
            if stop and stop():
                timed_out = True
                break
            if time.time() - start > max_seconds:
                timed_out = True
                break
            depth = len(Path(cur).relative_to(drive).parts)
            dirs[:] = [d for d in dirs if d.lower() not in DEEP_SKIP and not d.startswith(".")] if depth < max_depth else []
            low = {f.lower(): f for f in files}
            hit = None
            for lf, f in low.items():
                if lf.endswith("-win64-shipping.exe"):
                    hit = _game_root_from_exe(Path(cur) / f)
                    break
            if not hit and ("unityplayer.dll" in low or "gameassembly.dll" in low):
                hit = Path(cur)
            if not hit and any(f.endswith(".pck") for f in low) and any(f.endswith(".exe") for f in low):
                hit = Path(cur)
            if hit and not find_main_exe(hit):
                hit = None                                # an engine library with no game program next to it isn't a game
            if hit:
                key = str(hit.resolve()).lower()
                if key not in known:
                    known.add(key)
                    found.append(str(hit.resolve()))
                dirs[:] = []                              # don't descend into a game we just found
        if timed_out:
            break
    cur = list(settings.get("foundGames", []))
    settings.set("foundGames", cur + [f for f in found if f not in cur])
    return {"found": found, "seconds": round(time.time() - start, 1), "timedOut": timed_out}


def report():
    """What the scan looked at, so a player can see why a game is (not) listed."""
    roots = [r for r in common_roots() if os.path.isdir(r)]
    epic_dir = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    return [
        ("Drives scanned", ", ".join(fixed_drives())),
        ("Game folders found on those drives", ", ".join(roots) or "none"),
        ("Epic manifests", str(len(list(epic_dir.glob("*.item"))) if epic_dir.exists() else 0)),
        ("GOG games (registry)", str(len(gog()))),
        ("Ubisoft Connect games (registry)", str(len(ubisoft()))),
        ("EA games (registry)", str(len(ea()))),
        ("Installed programs that contain a game engine", str(len(installed_apps()))),
        ("Folders you added", ", ".join(settings.get("gameFolders", [])) or "none"),
        ("Found by deep scan", str(len(settings.get("foundGames", [])))),
    ]
