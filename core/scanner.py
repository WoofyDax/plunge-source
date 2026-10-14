"""Find installed Steam games and work out how (and whether) Plunge can VR-ify them."""
import os
import re
from pathlib import Path

try:
    import winreg
except ImportError:  # non-Windows: scanner just finds nothing
    winreg = None

from . import stores

ANTICHEAT_MARKERS = {
    "easyanticheat": "Easy Anti-Cheat",
    "eac_launcher": "Easy Anti-Cheat",
    "battleye": "BattlEye",
    "beclient": "BattlEye",
    "vgk": "Riot Vanguard",
    "xigncode": "XIGNCODE3",
    "equ8": "EQU8",
}

# Steam tools and apps that are not games (or already are VR runtimes).
NOT_GAMES = ("Steamworks", "SteamVR", "Wallpaper Engine", "Soundpad", "Steam Linux Runtime", "Blender")

ROUTES = {
    "unreal": {
        "id": "uevr",
        "label": "Unreal (UEVR + AI refinements)",
        "maturity": "proven",
        "note": "Try it instantly with UEVR (Unreal 4.8 - 5.4), then let an AI agent redesign what UEVR can't fix.",
    },
    "unity": {
        "id": "agent-unity",
        "label": "Unity (AI-built VR plugin)",
        "maturity": "experimental",
        "note": "An AI agent reads the game and writes a BepInEx/MelonLoader plugin for camera, controllers and HUD.",
    },
    "godot": {
        "id": "agent-godot",
        "label": "Godot (AI-built OpenXR patch)",
        "maturity": "experimental",
        "note": "An AI agent adds OpenXR through the engine's own XR support.",
    },
    "emulator": {
        "id": "agent-emulator",
        "label": "Emulated game (AI-built VR layer)",
        "maturity": "research",
        "note": "An AI agent works on the emulator that runs your game file: its renderer, camera and input. Results vary a lot by system. Your own game file only.",
    },
    "other": {
        "id": "agent-custom",
        "label": "Custom engine (AI reverse engineering)",
        "maturity": "research",
        "note": "An AI agent reverse-engineers the camera and render path. May end as a virtual-screen (theater) version.",
    },
}


def steam_root():
    """Where Steam is installed: the current user's setting, the machine-wide setting (64 and 32-bit views), then the
    usual folders on every drive."""
    cands = []
    if winreg:
        for hive, key, val in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                               (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                               (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    cands.append(winreg.QueryValueEx(k, val)[0])
            except OSError:
                pass
    for d in stores.fixed_drives():
        cands += [d + r"Program Files (x86)\Steam", d + r"Program Files\Steam", d + "Steam"]
    for p in cands:
        if p and Path(p).exists() and (Path(p) / "steamapps").exists():
            return Path(p)
    return None


def library_dirs(root):
    """Every Steam library folder (Steam can keep games on several drives). Reads both the current and the older
    libraryfolders.vdf layouts."""
    dirs = [root / "steamapps"]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        text = vdf.read_text(encoding="utf-8", errors="ignore")
        found = re.findall(r'"path"\s+"([^"]+)"', text) + re.findall(r'^\s*"\d+"\s+"([A-Za-z]:[^"]+)"', text, re.M)
        for raw in found:
            d = Path(raw.replace("\\\\", "\\")) / "steamapps"
            if d.exists() and d not in dirs:
                dirs.append(d)
    return dirs


def report():
    """For 'Why isn't my game listed?': what Steam and the other sources contributed."""
    root = steam_root()
    rows = [("Steam", str(root) if root else "not found")]
    seen = set()
    for lib in (library_dirs(root) if root else []):
        key = str(lib).lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(("Steam library", "%s (%d installed games)" % (lib.parent, len(list(lib.glob("appmanifest_*.acf"))))))
    return rows + stores.report()


def _manifest_field(text, key):
    m = re.search(r'"%s"\s+"([^"]*)"' % key, text)
    return m.group(1) if m else None


def _walk_limited(root, max_depth=3, max_entries=6000):
    root = str(root)
    base = root.rstrip("\\/").count(os.sep)
    seen = 0
    for cur, dirs, files in os.walk(root):
        if cur.count(os.sep) - base >= max_depth:
            dirs[:] = []
        yield cur, dirs, files
        seen += len(dirs) + len(files)
        if seen > max_entries:
            return


def inspect_install(path):
    """Return engine / exe / anti-cheat facts for an install folder."""
    path = Path(path)
    engine, exe = "other", None
    anticheat = set()
    shipping = []
    for cur, dirs, files in _walk_limited(path):
        names = [n.lower() for n in dirs + files]
        for n in names:
            for marker, label in ANTICHEAT_MARKERS.items():
                if marker in n:
                    anticheat.add(label)
        for f in files:
            lf = f.lower()
            if lf.endswith("-win64-shipping.exe"):
                shipping.append(Path(cur) / f)
            if lf == "unityplayer.dll" or lf == "gameassembly.dll":
                engine = engine if engine == "unreal" else "unity"
            if lf.endswith(".pck"):
                engine = engine if engine in ("unreal", "unity") else "godot"
        if any(d.lower().endswith("_data") and (Path(cur) / d / "Managed").exists() for d in dirs):
            engine = engine if engine == "unreal" else "unity"
    if shipping:
        engine = "unreal"
        exe = max(shipping, key=lambda p: p.stat().st_size)
    elif engine != "other":
        exes = [p for p in path.glob("*.exe") if "crash" not in p.name.lower() and "unins" not in p.name.lower()]
        exe = max(exes, key=lambda p: p.stat().st_size) if exes else None
    return {"engine": engine, "exe": str(exe) if exe else None, "anticheat": sorted(anticheat)}


def classify(info):
    route = ROUTES[info["engine"]]
    if info["anticheat"]:
        status, why = "blocked", "Uses anti-cheat (%s). Plunge never touches games with anti-cheat." % ", ".join(info["anticheat"])
    elif info["engine"] == "unreal":
        status, why = "supported", route["note"]
    else:
        status, why = "experimental", route["note"]
    return {"route": route, "status": status, "why": why}


def scan_games():
    """Steam games (from Steam's own records) plus games found elsewhere (see stores.py)."""
    root = steam_root()
    games, seen, libs, installdirs, paths_ = [], set(), [], [], []
    seen_libs = set()
    for lib in (library_dirs(root) if root else []):
        if str(lib.resolve()).lower() in seen_libs:       # the same library can be listed twice with different spelling
            continue
        seen_libs.add(str(lib.resolve()).lower())
        libs.append(lib)
        for mf in lib.glob("appmanifest_*.acf"):
            text = mf.read_text(encoding="utf-8", errors="ignore")
            appid, name, installdir = (_manifest_field(text, k) for k in ("appid", "name", "installdir"))
            if not (appid and name and installdir):
                continue
            installdirs.append(installdir)
            if appid in seen:
                continue
            if name.startswith(NOT_GAMES) or "Redistributable" in name or name.startswith("Proton"):
                continue
            seen.add(appid)
            path = lib / "common" / installdir
            if not path.exists():
                continue
            paths_.append(str(path))
            info = inspect_install(path)
            games.append({"appid": appid, "name": name, "path": str(path), "buildId": _manifest_field(text, "buildid"),
                          "store": "Steam", "launch": {"kind": "steam", "appid": appid}, **info, **classify(info)})
    seen_paths = {str(Path(p).resolve()).lower() for p in paths_}
    for g in stores.all_extra(libs, installdirs, paths_):
        if str(Path(g["path"]).resolve()).lower() in seen_paths:
            continue
        info = inspect_install(g["path"])
        if g.get("emulator"):
            info["engine"] = "emulator"
        exe = info["exe"] or (g["launch"].get("exe") if g["launch"]["kind"] == "exe" else None) or g.pop("exeHint", None)
        info["exe"] = exe if exe and Path(exe).exists() else info["exe"]
        games.append({**g, "buildId": None, **info, **classify(info)})
    games.sort(key=lambda g: g["name"].lower())
    return {"steam": str(root) if root else None, "games": games}


def demo_games():
    """Shown only when Steam isn't found, so the UI can be explored. Never launchable."""
    rows = [
        ("1332010", "Stray", "unreal", []),
        ("1817230", "Hi-Fi RUSH", "unreal", []),
        ("1627720", "Lies of P", "unreal", []),
        ("1562430", "DREDGE", "unity", []),
        ("367520", "Hollow Knight", "unity", []),
        ("1245620", "ELDEN RING", "other", ["Easy Anti-Cheat"]),
    ]
    out = []
    for appid, name, engine, ac in rows:
        info = {"engine": engine, "exe": None, "anticheat": ac}
        out.append({"appid": appid, "name": name, "path": "(demo)", **info, **classify(info), "demo": True})
    return out
