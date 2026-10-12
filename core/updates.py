"""Update check. Plunge only TELLS the player a newer version exists and opens its download page: it never downloads or
runs an update by itself (an installer should be signed and checked by Windows first).

Turn it on by pointing PLUNGE_UPDATE_URL (or the updateUrl setting) at an HTTPS JSON file:
    {"version": "1.0.1", "url": "https://yourdomain/download", "notes": "what changed"}
"""
import json
import os
import re
import urllib.request
from urllib.parse import urlparse

from . import safety, settings
from .version import VERSION

MAX_BYTES = 64 * 1024
DEFAULT_UPDATE_URL = "https://plungevr.com/latest.json"


def _vkey(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def update_url():
    return os.environ.get("PLUNGE_UPDATE_URL") or settings.get("updateUrl") or DEFAULT_UPDATE_URL


def _same_site(url, base):
    """The download page must be on the same site as the update file (or a subdomain), so a tampered file can't send you elsewhere."""
    a, b = (urlparse(url).hostname or "").lower(), (urlparse(base).hostname or "").lower()
    return bool(a and b and (a == b or a.endswith("." + b) or b.endswith("." + a)))


def check(current=VERSION):
    """{'enabled': False} when no update URL is set, else {'enabled', 'available', 'version', 'url', 'notes'}. Never raises."""
    base = update_url()
    if not base:
        return {"enabled": False, "available": False}
    try:
        safety.require_secure_url(base)
        req = urllib.request.Request(base, headers={"User-Agent": "Plunge/" + current, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read(MAX_BYTES + 1)[:MAX_BYTES])
        ver, url = safety.clean_text(data.get("version"), 20), str(data.get("url", ""))
        if not re.fullmatch(r"\d+(\.\d+){1,3}", ver) or not url.startswith("https://") or not _same_site(url, base):
            return {"enabled": True, "available": False, "error": "the update file isn't valid"}
        return {"enabled": True, "available": _vkey(ver) > _vkey(current), "version": ver, "url": url,
                "notes": safety.clean_text(data.get("notes"), 300), "current": current}
    except (ValueError, OSError):
        return {"enabled": True, "available": False, "error": "couldn't check for updates"}


def open_download():
    """Open the download page from the last good check (never a URL chosen by the web page)."""
    r = check()
    if not r.get("available"):
        raise ValueError("there's no update to open")
    os.startfile(r["url"])
    return {"ok": True}
