"""Does the game already support VR? Steam's own store tags (cached), plus VR runtime files in the install."""
import json
import threading
import time
import urllib.request
from pathlib import Path

from . import paths

CACHE_TTL = 7 * 24 * 3600
STEAM_API = "https://store.steampowered.com/api/appdetails?appids=%s&filters=categories"
VR_FILES = {"openvr_api.dll": "OpenVR", "openxr_loader.dll": "OpenXR", "ovrplugin.dll": "Oculus",
            "oculusxr": "Oculus", "libopenvr_api": "OpenVR"}
_lock = threading.Lock()
_worker = {"running": False}


def _cache_file():
    return paths.DATA / "cache" / "steam_vr.json"


def _load():
    try:
        return json.loads(_cache_file().read_text())
    except (OSError, ValueError):
        return {}


def _save(cache):
    f = _cache_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    paths.atomic_write(f, json.dumps(cache))


def vac_from_categories(cats):
    """Steam category 8 is 'Valve Anti-Cheat enabled'."""
    return any(c.get("id") == 8 or "anti-cheat" in str(c.get("description", "")).lower() for c in (cats or []))


def level_from_categories(cats):
    """Steam category 54 is 'VR Only', 53 is 'VR Supported' (descriptions checked too)."""
    for c in cats or []:
        if c.get("id") == 54 or "vr only" in str(c.get("description", "")).lower():
            return "only"
    for c in cats or []:
        if c.get("id") == 53 or "vr support" in str(c.get("description", "")).lower():
            return "supported"
    return None


def from_files(install_path, max_entries=4000):
    """Cheap local hint: VR runtime libraries sitting in the game folder."""
    seen, found = 0, None
    base = Path(install_path)
    if not base.exists():
        return None
    for p in base.rglob("*"):
        seen += 1
        if seen > max_entries:
            break
        n = p.name.lower()
        for key, label in VR_FILES.items():
            if key in n:
                found = label
                break
        if found:
            break
    return found


def lookup(appid):
    """Cached Steam answer: {'level': 'only'|'supported'|None} or None if not fetched yet."""
    c = _load().get(str(appid))
    # entries from older versions have no 'vac' answer yet: treat them as missing so they get fetched again
    return c if c and "vac" in c and time.time() - c["t"] < CACHE_TTL else None


def refresh_async(appids):
    """Fetch missing/stale Steam answers in the background (polite: one request at a time)."""
    todo = [a for a in appids if str(a).isdigit() and lookup(a) is None]     # non-Steam ids have no Steam page
    with _lock:
        if _worker["running"] or not todo:
            return

        _worker["running"] = True

    def run():
        try:
            cache = _load()
            for a in todo:
                try:
                    req = urllib.request.Request(STEAM_API % a, headers={"User-Agent": "Plunge"})
                    with urllib.request.urlopen(req, timeout=12) as r:
                        data = json.load(r).get(str(a), {})
                    cats = (data.get("data") or {}).get("categories", []) if data.get("success") else []
                    cache[str(a)] = {"level": level_from_categories(cats), "vac": vac_from_categories(cats), "t": time.time()}
                    _save(cache)
                except (OSError, ValueError):
                    pass
                time.sleep(1.2)
        finally:
            _worker["running"] = False

    threading.Thread(target=run, daemon=True).start()


def describe(appid, install_path):
    """Combine Steam's tag and local files into one answer for the UI."""
    c = lookup(appid)
    if c:  # Steam has answered: trust it over file hints, which can be false positives
        return {"level": c["level"], "via": "Steam", "vac": bool(c["vac"])}
    hint = from_files(install_path) if install_path and install_path != "(demo)" else None
    if hint:
        return {"level": "supported", "via": "game files (%s), unconfirmed" % hint, "vac": False}
    if not str(appid).isdigit():                      # not a Steam game: nothing to wait for
        return {"level": None, "via": "not on Steam", "vac": False}
    return {"level": None, "via": "checking", "vac": False}
