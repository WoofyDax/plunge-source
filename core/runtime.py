"""Headset / runtime detection, one-click runtime install, and launching."""
import json
import urllib.request
import zipfile
from pathlib import Path

from . import paths

try:
    import winreg
except ImportError:
    winreg = None

UEVR_RELEASES = "https://api.github.com/repos/praydog/UEVR/releases/latest"


def openxr_runtime():
    if not winreg:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Khronos\OpenXR\1") as k:
            p, _ = winreg.QueryValueEx(k, "ActiveRuntime")
            return p
    except OSError:
        return None


def find_injector():
    root = paths.RUNTIMES / "uevr"
    if root.exists():
        for p in root.rglob("UEVRInjector.exe"):
            return p
    return None


def system_status():
    xr = openxr_runtime()
    inj = find_injector()
    return {
        "openxr": xr,
        "headsetReady": bool(xr),
        "uevrInstalled": bool(inj),
        "uevrPath": str(inj) if inj else None,
    }


def _safe_extract(zf, dest):
    dest = dest.resolve()
    for m in zf.namelist():
        if not (dest / m).resolve().is_relative_to(dest):
            raise ValueError("unsafe path in archive: %s" % m)
    zf.extractall(dest)


def install_uevr():
    """Download the latest official UEVR release from GitHub. Only called when the user clicks."""
    paths.ensure()
    req = urllib.request.Request(UEVR_RELEASES, headers={"User-Agent": "Plunge"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rel = json.load(r)
    assets = [a for a in rel.get("assets", []) if a["name"].lower().endswith(".zip")]
    if not assets:
        raise RuntimeError("no .zip asset on the latest UEVR release")
    asset = assets[0]
    dest = paths.RUNTIMES / "uevr"
    dest.mkdir(parents=True, exist_ok=True)
    zpath = dest / asset["name"]
    urllib.request.urlretrieve(asset["browser_download_url"], zpath)
    with zipfile.ZipFile(zpath) as zf:
        _safe_extract(zf, dest)
    zpath.unlink()
    return {"version": rel.get("tag_name"), "asset": asset["name"], "injector": str(find_injector())}
