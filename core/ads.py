"""Sponsored cards: ads as plain data, never as third-party scripts.

An ad source is a URL that returns JSON:
    {"ad": {"id": "acme-1", "title": "...", "body": "...", "image": "https://...", "link": "https://...",
            "cta": "Learn more", "advertiser": "Acme VR", "viewUrl": "https://... (optional impression ping)"}}
Plunge draws it as a labelled "Sponsored" card. Nothing from the ad runs inside the app: text is rendered
as text, the image is an <img>, and clicking opens the link in the player's normal browser.

Dormant until you configure a source: %LOCALAPPDATA%\\Plunge\\ads.json  {"url": "https://..."}  or set PLUNGE_ADS_URL.
"""
import json
import os
import time
import urllib.parse
import urllib.request

from . import paths

TTL = 600      # a good ad is reused for 10 minutes
RETRY = 60     # a failed fetch is retried after 1 minute
_CACHE = {"ad": None, "t": 0}
_SEEN = set()


def _settings_file():
    return paths.DATA / "settings.json"


def _read(f):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def source_url():
    return os.environ.get("PLUNGE_ADS_URL") or _read(paths.DATA / "ads.json").get("url") or None


def enabled():
    return _read(_settings_file()).get("ads", True)


def set_enabled(on):
    s = _read(_settings_file())
    s["ads"] = bool(on)
    _settings_file().parent.mkdir(parents=True, exist_ok=True)
    paths.atomic_write(_settings_file(), json.dumps(s))
    if not on:
        _CACHE.update(ad=None, t=0)
    return {"enabled": bool(on)}


def _https(u):
    try:
        p = urllib.parse.urlparse(str(u))
    except ValueError:
        return False
    return p.scheme == "https" and bool(p.netloc)


def normalize(raw):
    """Turn untrusted ad JSON into a safe, bounded ad dict, or None if it is not acceptable."""
    a = raw.get("ad") if isinstance(raw, dict) and isinstance(raw.get("ad"), dict) else raw
    if not isinstance(a, dict):
        return None
    title, link = str(a.get("title", "")).strip()[:80], a.get("link")
    if not title or not _https(link):
        return None
    image = a.get("image") if _https(a.get("image")) else None
    view = a.get("viewUrl") if _https(a.get("viewUrl")) else None
    return {"id": str(a.get("id") or title)[:60], "title": title, "body": str(a.get("body", "")).strip()[:140],
            "image": image, "link": str(link), "cta": str(a.get("cta", "Learn more")).strip()[:24] or "Learn more",
            "advertiser": str(a.get("advertiser", "")).strip()[:40], "viewUrl": view}


def status():
    url = source_url()
    return {"enabled": enabled(), "configured": bool(url), "host": urllib.parse.urlparse(url).netloc if url else None}


def current():
    """The ad to show now (cached for 10 minutes), or None. Never raises: ads must not break the app."""
    if not enabled() or not source_url():
        return None
    age = time.time() - _CACHE["t"]
    if age < (TTL if _CACHE["ad"] is not None else RETRY):   # a failed fetch is retried sooner than a good ad is refreshed
        return _CACHE["ad"]
    try:
        req = urllib.request.Request(source_url(), headers={"User-Agent": "Plunge", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=6) as r:
            ad = normalize(json.loads(r.read(65536)))
    except (OSError, ValueError):
        ad = None
    _CACHE.update(ad=ad, t=time.time())
    return ad


def public(ad):
    """What the UI gets: no viewUrl, which only Python ever calls."""
    return {k: v for k, v in ad.items() if k != "viewUrl"} if ad else None


def seen(ad_id):
    """Fire the advertiser's impression ping once per ad per session, from Python (not from the web view)."""
    ad = _CACHE["ad"]
    if not ad or ad["id"] != ad_id or ad_id in _SEEN:
        return {"ok": False}
    _SEEN.add(ad_id)
    if ad["viewUrl"]:
        try:
            urllib.request.urlopen(urllib.request.Request(ad["viewUrl"], headers={"User-Agent": "Plunge"}), timeout=5).read(1)
        except OSError:
            pass
    return {"ok": True}


def click(ad_id):
    """Open the cached ad's own link in the default browser. The UI can never choose the URL."""
    ad = _CACHE["ad"]
    if not ad or ad["id"] != ad_id:
        raise ValueError("that ad is no longer available")
    os.startfile(ad["link"])
    return {"ok": True}
