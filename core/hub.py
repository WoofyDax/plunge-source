"""Client for the Plunge hub: browse Discover, get a profile, publish your own."""
import hashlib
import io
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import paths, profiles, safety, settings

HUB_URL = os.environ.get("PLUNGE_HUB", "https://hub.plungevr.com").rstrip("/")
MAX_JSON = 2 * 1024 * 1024
MAX_DOWNLOAD = 41 * 1024 * 1024        # the hub itself refuses uploads over 40 MB


class HubError(ValueError):               # a ValueError, so the app shows its message like any other expected problem
    pass


def _req(path, data=None, ctype="application/json", raw=False, timeout=15):
    try:
        safety.require_secure_url(HUB_URL)                     # plain http is only allowed for a hub on this same PC
    except ValueError as e:
        raise HubError(str(e))
    headers = {"Content-Type": ctype} if data is not None else {}
    tok = _token()
    if tok:                                                    # the hub address was checked above: https, or this same PC
        headers["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(HUB_URL + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            limit = MAX_DOWNLOAD if raw else MAX_JSON
            body = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", "hub error")
        except ValueError:
            msg = "hub error %d" % e.code
        if e.code == 401 and tok:                              # the hub no longer knows this sign-in
            settings.set("account", None)
            msg = "your sign-in has ended: please sign in again"
        raise HubError(msg)
    except (urllib.error.URLError, OSError) as e:
        if isinstance(getattr(e, "reason", e), TimeoutError):
            raise HubError("the connection to the Plunge hub was too slow and timed out. Try again; a build can be 20 MB or more")
        raise HubError("can't reach the Plunge hub at %s" % HUB_URL)
    if len(body) > limit:                                      # a hostile or broken hub can't make us read forever
        raise HubError("the hub sent more data than expected")
    if raw:
        return body
    try:
        return json.loads(body)
    except ValueError:
        raise HubError("the hub sent something that isn't valid")


# ---- accounts: sign in with an email code ---------------------------------------------------------------------------------------
def _token():
    a = settings.get("account")
    t = a.get("token") if isinstance(a, dict) else None
    return t if isinstance(t, str) and 20 <= len(t) <= 100 else None


def account():
    """Who is signed in on this PC, without the secret token: {"username", "email"} or None."""
    a = settings.get("account")
    if isinstance(a, dict) and _token():
        return {"username": safety.clean_text(a.get("username"), 24), "email": safety.clean_text(a.get("email"), 120),
                "hasPassword": bool(a.get("hasPassword")), "hasGoogle": bool(a.get("hasGoogle"))}
    return None


def _json(obj):
    return json.dumps(obj).encode()


def sign_in_start(email):
    """Ask the hub to email a sign-in code."""
    _req("/auth/start", _json({"email": str(email or "")[:254]}))
    return {"sent": True}


def _keep_sign_in(r):
    """Save a sign-in answer from the hub (token + account) on this PC."""
    tok, u = r.get("token"), r.get("user") or {}
    if not (isinstance(tok, str) and 20 <= len(tok) <= 100 and isinstance(u.get("username"), str)):
        raise HubError("the hub's answer wasn't valid")
    settings.set("account", {"token": tok, "username": u["username"], "email": u.get("email", ""),
                             "hasPassword": bool(u.get("hasPassword")), "hasGoogle": bool(u.get("hasGoogle"))})
    return {"user": account(), "new": bool(r.get("new"))}


def sign_in_verify(email, code, username=None, password=None):
    """Finish an emailed-code sign-in. Returns {"needUsername": True} for a new address, else {"user": {...}} and the session is kept on this PC."""
    r = _req("/auth/verify", _json({"email": str(email or "")[:254], "code": str(code or "")[:12], "username": (str(username)[:40] if username else None),
                                    "password": (str(password)[:300] if password else None)}))
    if r.get("needUsername"):
        return {"needUsername": True}
    return _keep_sign_in(r)


def password_sign_in(email, password):
    return _keep_sign_in(_req("/auth/login", _json({"email": str(email or "")[:254], "password": str(password or "")[:300]})))


def config():
    """What the hub offers: {"google": bool, "passwordMin": n}. An unreachable hub just means "nothing extra"."""
    try:
        c = _req("/auth/config")
        return {"google": bool(c.get("google")), "passwordMin": int(c.get("passwordMin", 10))}
    except (HubError, ValueError, TypeError):
        return {"google": False, "passwordMin": 10}


_GOOGLE = {"verifier": None, "started": 0.0}


def google_start():
    """Open the browser at Google's sign-in (through the hub). The app keeps a secret that only it knows and collects the result with google_poll()."""
    if not config()["google"]:
        raise HubError("Google sign-in isn't set up yet")
    safety.require_secure_url(HUB_URL)
    verifier = secrets.token_urlsafe(32)
    _GOOGLE.update(verifier=verifier, started=time.time())
    url = "%s/auth/google/start?mode=app&challenge=%s" % (HUB_URL, hashlib.sha256(verifier.encode()).hexdigest())
    os.startfile(url)                                          # the address is the hub's own (https, or this same PC), never one the page chose
    return {"opened": True}


def google_poll():
    """Ask the hub whether the Google sign-in finished. {"pending": True} until it does, then the usual {"user": ...}."""
    v = _GOOGLE["verifier"]
    if not v:
        raise HubError("start the Google sign-in first")
    if time.time() - _GOOGLE["started"] > 600:
        _GOOGLE["verifier"] = None
        raise HubError("that Google sign-in timed out: please try again")
    r = _req("/auth/google/poll", _json({"verifier": v}))
    if r.get("pending"):
        return {"pending": True}
    _GOOGLE["verifier"] = None
    return _keep_sign_in(r)


def set_password(new, current=None):
    _req("/me/password", _json({"new": str(new or "")[:300], "current": (str(current)[:300] if current else None)}))
    a = settings.get("account")
    if isinstance(a, dict):
        settings.set("account", {**a, "hasPassword": True})
    return {"ok": True}


def rename(username):
    r = _req("/me/username", _json({"username": str(username or "")[:40]}))
    a = settings.get("account")
    if isinstance(a, dict):
        settings.set("account", {**a, "username": r["username"]})
    return {"username": r["username"]}


def sign_out():
    if _token():
        try:
            _req("/auth/logout", b"{}")
        except HubError:
            pass                                               # being offline must never stop you signing out on this PC
    settings.set("account", None)
    return {"signedOut": True}


def me():
    """Check the saved sign-in is still good. Returns the account or None (and forgets it if the hub no longer knows it)."""
    if not _token():
        return None
    try:
        r = _req("/me")
    except HubError as e:
        if "sign in" in str(e):
            return None
        raise
    u = r["user"]
    a = settings.get("account")
    if isinstance(a, dict):                                    # keep the saved copy in step with the hub (a rename or password set on another device)
        settings.set("account", {**a, "username": u["username"], "hasPassword": bool(u.get("hasPassword")), "hasGoogle": bool(u.get("hasGoogle"))})
    return {"username": safety.clean_text(u["username"], 24), "email": safety.clean_text(u.get("email"), 120),
            "hasPassword": bool(u.get("hasPassword")), "hasGoogle": bool(u.get("hasGoogle"))}


def my_profiles():
    return _req("/me/profiles")["profiles"]


def remove(pid):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,60}", str(pid)):
        raise HubError("bad profile id")
    return _req("/profiles/%s/remove" % pid, b"{}")


def delete_account():
    _req("/me/delete", _json({"confirm": "delete my account"}))
    settings.set("account", None)
    return {"deleted": True}


def browse(sort="new", appid=None, text=None, tier=None, mp=False):
    q = urllib.parse.urlencode({k: v for k, v in (("sort", sort), ("appid", appid), ("q", text), ("tier", tier), ("mp", "1" if mp else None)) if v})
    return _req("/profiles?" + q)["profiles"]


def get(pid):
    """Download a profile from the hub into the local profile folder and validate it."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,60}", pid):
        raise HubError("bad profile id")
    data = _req("/profiles/%s/download" % pid, raw=True, timeout=120)
    dest = paths.PROFILES / pid
    if dest.exists():
        raise HubError("you already have this profile")
    import shutil
    from . import hub_server
    dest.mkdir(parents=True)
    try:
        # the same checks the hub applies on upload (path escapes, links, zip bombs, sizes): a hub is never trusted blindly
        _, err = hub_server.unpack_checked(data, dest)
        if err:
            raise HubError("downloaded profile was rejected: " + err)
        bad = [f["msg"] for f in profiles.validate(pid) if f["level"] == "error"]
        if bad:
            raise HubError("downloaded profile failed validation: " + bad[0])
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)               # never leave a half-extracted profile behind
        raise
    return {"slug": pid}


def publish(slug):
    """Zip a local profile and upload it. The hub re-validates it, and puts your account name on it as the author."""
    if not _token():
        raise HubError("sign in to publish a profile")
    bad = [f["msg"] for f in profiles.validate(slug) if f["level"] == "error"]
    if bad:
        raise HubError("fix this first: " + bad[0])
    d = profiles.profile_dir(slug)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in d.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(d).as_posix())
    return _req("/profiles", buf.getvalue(), "application/zip", timeout=180)      # builds are tens of MB: a slow home upload must not time out


def like(pid):
    if not _token():
        raise HubError("sign in to like a profile")
    return _req("/profiles/%s/like" % pid, b"{}")
