"""Start a game and, for Steam games, confirm it really started (or say why it didn't).

Steam games are always started through Steam (steam.exe -applaunch), never by running the exe directly: many
Steamworks games quit at once without Steam. Steam answers in %STEAM%\\logs\\console_log.txt, so we read that.
"""
import os
import re
import subprocess
import time
from pathlib import Path

from . import scanner

REASONS = {
    "FamilySharing": "This game is borrowed through Steam Family Sharing, and Steam won't start it while its owner's library is in use.",
    "NoLicense": "Your Steam account doesn't own this game.",
    "Offline": "Steam is offline. Go online once so it can check the game's licence.",
    "UpdateRequired": "Steam says this game needs an update first.",
    "Running": "The game is already running.",
}


class LaunchError(Exception):
    pass


def steam_exe():
    root = scanner.steam_root()
    exe = Path(root) / "steam.exe" if root else None
    return str(exe) if exe and exe.exists() else None


def _log_path():
    root = scanner.steam_root()
    return Path(root) / "logs" / "console_log.txt" if root else None


def _log_size(p):
    try:
        return p.stat().st_size if p else 0
    except OSError:
        return 0


def _read_from(p, offset):
    try:
        with open(p, "rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", errors="ignore")
    except OSError:
        return ""


def confirm_steam_launch(appid, offset, timeout=30, log=None):
    """Poll Steam's log after a launch request. Returns True (started), None (no answer yet) or raises LaunchError."""
    p = log or _log_path()
    ok = re.compile(r"Game process (?:updated|added)\s*:\s*AppID %s\b" % re.escape(str(appid)))
    bad = re.compile(r"AppID %s, ActionID \d+\] : LaunchApp failed with (\w+) with \"([^\"]*)\"" % re.escape(str(appid)))
    end = time.time() + timeout
    while time.time() < end:
        text = _read_from(p, offset)
        m = bad.search(text)
        if m:
            code, reason = m.group(1), m.group(2)
            raise LaunchError(REASONS.get(reason) or REASONS.get(code) or "Steam refused to start it (%s: %s)." % (code, reason or "no reason given"))
        if ok.search(text):
            return True
        time.sleep(0.5)
    return None


def start(game, args=(), env=None, forced_exe=None, verify=True):
    """Launch `game` and return {"started": True|None, "how": ...}. Raises LaunchError with a plain reason."""
    spec = game.get("launch") or {"kind": "steam", "appid": game["appid"]}
    args = [str(a) for a in args]
    env = dict(env or {})
    kind = spec["kind"]
    if kind == "steam":
        exe = steam_exe()
        log, off = _log_path(), _log_size(_log_path())
        if exe:
            subprocess.Popen([exe, "-applaunch", str(spec["appid"])] + args)
        else:
            os.startfile("steam://rungameid/%s" % spec["appid"])
        started = confirm_steam_launch(spec["appid"], off, log=log) if verify else None
        return {"started": started, "how": "steam"}
    if kind == "uri":
        os.startfile(spec["uri"])
        return {"started": None, "how": "launcher"}
    args = [str(a) for a in spec.get("args", [])] + args          # a program's own arguments first (the game file for an emulator)
    exe = forced_exe or spec.get("exe")
    if not exe:
        raise LaunchError("Plunge couldn't find this game's program. Add the game folder again, or start it yourself.")
    exe = str(exe).strip().strip('"')
    if not os.path.isabs(exe):
        exe = str(Path(game["path"]) / exe)
    if not Path(exe).exists():
        raise LaunchError("The game's program is missing: %s" % exe)
    subprocess.Popen([exe] + args, cwd=str(Path(exe).parent), env={**os.environ, **env})
    return {"started": None, "how": "exe"}
