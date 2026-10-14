"""Plunge hub: where players publish VR profiles and everyone else discovers them.

Uploads are zip files of a profile folder. The hub unpacks each one in a temp folder and runs the same
validator the app uses; anything that fails is rejected. Accounts do not exist yet: the author name is
whatever the profile says (unverified). Featuring needs the admin token (PLUNGE_HUB_ADMIN).

Run it behind an HTTPS reverse proxy (see deploy/). Set PLUNGE_TRUST_PROXY=1 only when such a proxy sets X-Forwarded-For,
so rate limits see real client addresses.

    plunge-cli.exe hub [--port 8788] [--bind 0.0.0.0] [--data DIR]
"""
import hashlib
import io
import json
import os
import re
import secrets
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import accounts, paths, safety

MAX_ZIP = 40 * 1024 * 1024
MAX_FILES = 1500
MAX_UNPACKED = 120 * 1024 * 1024
MAX_ONE_FILE = 60 * 1024 * 1024
MAX_RATIO = 200                       # a file that unpacks to 200x its size is a zip bomb
MAX_PROFILES = 5000
MAX_STORE = 4 * 1024 ** 3
LOCK = threading.Lock()
LIMITER = safety.RateLimiter()
STATE = {"dir": Path(os.environ.get("PLUNGE_HUB_DATA", "hub-data")), "admin": os.environ.get("PLUNGE_HUB_ADMIN", ""),
         "require_auth": os.environ.get("PLUNGE_HUB_REQUIRE_AUTH", "1") != "0"}       # publishing and liking need an account
# websites allowed to call the hub from a browser (the Plunge site's sign-in page). The desktop app is not a browser and needs none of this.
ORIGINS = {o.strip() for o in os.environ.get("PLUNGE_WEB_ORIGINS", "https://plungevr.com,https://www.plungevr.com").split(",") if o.strip()}
COOKIE = "plunge_session"
LISTED_KEYS = ("title", "tagline", "steamAppId", "engine", "tier", "author", "comfort", "controls", "version")
LIMITS = {"read": (240, 60), "upload": (6, 3600), "like": (30, 60), "likeone": (1, 86400), "admin": (10, 60),
          "beta": (40, 3600), "authstart": (6, 3600), "authverify": (20, 3600), "login": (30, 3600), "google": (40, 3600), "me": (120, 60)}   # (hits, seconds) per client address


def _index_file():
    return STATE["dir"] / "index.json"


def _read():
    try:
        return json.loads(_index_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(idx):
    paths.atomic_write(_index_file(), json.dumps(idx))


def unpack_checked(data, dest):
    """Safely unpack an uploaded zip and return (meta, error)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None, "not a zip file"
    infos = zf.infolist()
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACKED:
        return None, "profile is too large"
    root = dest.resolve()
    for i in infos:
        if i.file_size > MAX_ONE_FILE:
            return None, "a file in the zip is too large: %s" % i.filename
        if i.file_size > 1024 * 1024 and i.compress_size and i.file_size / i.compress_size > MAX_RATIO:
            return None, "suspicious compression in %s" % i.filename
        if (i.external_attr >> 16) & 0o170000 == 0o120000:            # a symbolic link entry
            return None, "links are not allowed in a profile: %s" % i.filename
        t = (root / i.filename).resolve()
        if root != t and root not in t.parents:
            return None, "unsafe path in zip: %s" % i.filename
    zf.extractall(root)
    f = root / "plunge.json"
    if not f.exists():
        return None, "plunge.json is missing at the top of the zip"
    try:
        return json.loads(f.read_text(encoding="utf-8-sig")), None
    except ValueError:
        return None, "plunge.json is not valid JSON"


def accept(data):
    """Validate an upload with the app's own validator. Returns the profile's details or raises ValueError."""
    from . import profiles
    with tempfile.TemporaryDirectory() as tmp:
        slug = "upload-" + secrets.token_hex(4)       # run the validator against an isolated copy of the profile
        d = Path(tmp) / slug
        d.mkdir()
        meta, err = unpack_checked(data, d)
        if err:
            raise ValueError(err)
        bad = [f["msg"] for f in profiles.validate(slug, None, Path(tmp)) if f["level"] == "error"]
        if bad:
            raise ValueError("rejected: " + "; ".join(bad[:4]))
        return meta


def stamp_author(data, username):
    """Rewrite plunge.json inside an uploaded zip so its author is the signed-in account, not whatever the uploader typed."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            blob = src.read(info.filename)
            if info.filename == "plunge.json":
                meta = json.loads(blob.decode("utf-8-sig"))
                meta["author"] = username
                blob = json.dumps(meta, indent=1).encode("utf-8")
            dst.writestr(info.filename, blob)
    return out.getvalue()


def _drop_profile(idx, pid):
    idx.pop(pid, None)
    try:
        (STATE["dir"] / "zips" / (re.sub(r"[^a-z0-9-]", "", pid) + ".zip")).unlink()
    except OSError:
        pass


def _row(pid, e):
    m = e["meta"]
    return {"id": pid, "title": safety.clean_text(m.get("title"), 80), "tagline": safety.clean_text(m.get("tagline"), 140),
            "steamAppId": safety.clean_text(m.get("steamAppId"), 40), "engine": safety.clean_text(m.get("engine"), 20),
            "tier": safety.clean_text(m.get("tier"), 20), "author": safety.clean_text(m.get("author"), 60),
            "comfort": safety.clean_text(m.get("comfort"), 20), "controls": safety.clean_text(m.get("controls"), 20),
            "version": safety.clean_text(m.get("version"), 20), "downloads": e["downloads"], "likes": e["likes"],
            "created": e["created"], "featured": e["featured"], "multiplayer": bool((m.get("recipe") or {}).get("multiplayer")),
            "multiplayerKind": ("added" if ((m.get("recipe") or {}).get("multiplayer") or {}).get("kind") == "added" else "native") if (m.get("recipe") or {}).get("multiplayer") else None}


class Handler(BaseHTTPRequestHandler):
    timeout = 20                                      # drops slow or stalled connections

    def log_message(self, *a):
        pass

    def _ip(self):
        if os.environ.get("PLUNGE_TRUST_PROXY") == "1":
            # the LAST entry is the one our own proxy appended; earlier entries can be forged by the client to dodge rate limits
            return (self.headers.get("X-Forwarded-For", "").split(",")[-1].strip() or self.client_address[0])[:64]
        return self.client_address[0]

    def _limited(self, kind, extra=""):
        hits, secs = LIMITS[kind]
        if LIMITER.allow((kind, self._ip(), extra), hits, secs):
            return False
        self._send({"error": "slow down: too many requests"}, 429)
        return True

    def _send(self, obj, code=200, raw=None, ctype="application/json", filename=None, cookie=None):
        left = getattr(self, "_unread", 0)
        if left:                                                # answering before the upload was read would reset the connection and hide the message
            self._unread = 0
            try:
                self.rfile.read(min(left, 2 * 1024 * 1024))
            except OSError:
                pass
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin", "")
        if origin in ORIGINS:                                   # only the Plunge website may read answers from a browser
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        if filename:
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % filename)
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, url, cookies=()):
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()

    def _page(self, title, message, code=200, cookies=()):
        body = ("<!doctype html><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\"><title>%s</title>"
                "<body style=\"font:18px/1.5 system-ui,sans-serif;background:#050506;color:#f2f2f2;display:grid;place-items:center;min-height:100vh;margin:0;text-align:center\">"
                "<div style=\"max-width:26em;padding:24px\"><h1 style=\"font-size:28px;margin:0 0 8px\">%s</h1><p style=\"color:#aaa;margin:0\">%s</p></div></body>") % (title, title, message)
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):                                       # the browser's pre-flight check before a sign-in request
        origin = self.headers.get("Origin", "")
        self.send_response(204 if origin in ORIGINS else 403)
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Plunge-Client")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- who is asking ------------------------------------------------------------------------------------------------------------
    def _token(self):
        h = self.headers.get("Authorization", "")
        if h.startswith("Bearer "):
            return h[7:].strip(), "bearer"
        m = re.search(r"(?:^|;\s*)%s=([A-Za-z0-9_-]{20,100})" % COOKIE, self.headers.get("Cookie", ""))
        return (m.group(1), "cookie") if m else (None, None)

    def _is_web(self):
        return self.headers.get("X-Plunge-Client") == "web"

    def _auth(self, change=False):
        """The signed-in account for this request, or None. A browser's cookie is only honoured for changes when the request really
        comes from the Plunge website (allowed Origin plus our own header), which blocks cross-site request forgery."""
        tok, kind = self._token()
        if not tok:
            return None
        if accounts.STATE["db"] is None:
            accounts.init(STATE["dir"])
        if kind == "cookie" and change and not (self.headers.get("Origin", "") in ORIGINS and self._is_web()):
            return None
        return accounts.session_user(tok)

    def _json(self, n, limit=4096):
        if n > limit:
            raise ValueError("too big")
        try:
            raw = self.rfile.read(n)
            self._unread = 0
            obj = json.loads(raw or b"{}")
        except ValueError:
            raise ValueError("bad JSON")
        if not isinstance(obj, dict):
            raise ValueError("bad JSON")
        return obj

    def _cookie(self, token, max_age):
        return "%s=%s; Max-Age=%d; Path=/; HttpOnly; Secure; SameSite=Lax" % (COOKIE, token, max_age)

    @staticmethod
    def _public_user(u):
        return {"username": u["username"], "email": u["email"], "hasPassword": u.get("hasPassword", False), "hasGoogle": u.get("hasGoogle", False)}

    def _auth_get(self, parts, q):
        """/auth/config, and the Google round trip (start, callback)"""
        if accounts.STATE["db"] is None:
            accounts.init(STATE["dir"])
        if parts == ["auth", "config"]:
            return self._send({"google": bool(accounts.google_config()), "passwordMin": accounts.PW_MIN})
        if parts == ["auth", "google", "start"]:
            if self._limited("google"):
                return
            try:
                url, nonce = accounts.google_auth_url((q.get("mode") or [""])[0], (q.get("challenge") or [""])[0])
            except accounts.AuthError as e:
                return self._page("Can't sign in with Google", str(e), 400)
            return self._redirect(url, ["plunge_oauth=%s; Max-Age=600; Path=/auth/google; HttpOnly; Secure; SameSite=Lax" % nonce])
        if parts == ["auth", "google", "callback"]:
            if self._limited("google"):
                return
            clear = ["plunge_oauth=; Max-Age=0; Path=/auth/google; HttpOnly; Secure; SameSite=Lax"]
            if (q.get("error") or [""])[0]:
                return self._page("Google sign-in cancelled", "You can close this tab and try again from Plunge.", 400, clear)
            try:
                st = accounts.read_state((q.get("state") or [""])[0])
                m = re.search(r"(?:^|;\s*)plunge_oauth=([A-Za-z0-9_-]{10,40})", self.headers.get("Cookie", ""))
                if not m or not secrets.compare_digest(m.group(1), str(st.get("nonce", ""))):         # ties the answer to the browser that started it
                    raise accounts.AuthError("this sign-in didn't start in this browser: please try again")
                claims = accounts.EXCHANGE((q.get("code") or [""])[0])
                u, new = accounts.google_login(claims)
            except accounts.AuthError as e:
                return self._page("Couldn't sign in", str(e), 400, clear)
            if st.get("mode") == "web":
                token = accounts._new_session(u[0])
                return self._redirect(sorted(ORIGINS)[0] + "/account", clear + [self._cookie(token, accounts.SESSION_TTL)])
            accounts.stash_pickup(u[0], st.get("challenge", ""))
            return self._page("You're signed in", "Go back to the Plunge app: it will finish signing you in in a moment. You can close this tab.", 200, clear)
        self._send({"error": "not found"}, 404)

    def _account_post(self, parts, n):
        """sign in, sign out, delete my account"""
        if accounts.STATE["db"] is None:
            accounts.init(STATE["dir"])
        try:
            body = self._json(n)
        except ValueError as e:
            return self._send({"error": str(e)}, 400)
        if parts == ["auth", "start"]:
            if self._limited("authstart"):
                return
            try:
                accounts.start_login(body.get("email"))
            except accounts.AuthError as e:
                return self._send({"error": str(e)}, 400)
            except RuntimeError:
                return self._send({"error": "couldn't send the email right now: please try again in a minute"}, 503)
            accounts.purge_expired()
            return self._send({"ok": True})                    # the same answer whether or not the address has an account
        if parts == ["auth", "verify"]:
            if self._limited("authverify"):
                return
            try:
                r = accounts.verify_login(body.get("email"), body.get("code"), body.get("username"), body.get("password"))
            except accounts.AuthError as e:
                return self._send({"error": str(e)}, 400)
            if r.get("needUsername"):
                return self._send({"needUsername": True})
            web = self._is_web() and self.headers.get("Origin", "") in ORIGINS
            out = {"user": self._public_user(r["user"]), "new": r["new"]}
            if web:                                            # a browser gets an HttpOnly cookie, so scripts on the page never see the token
                return self._send(out, cookie=self._cookie(r["token"], accounts.SESSION_TTL))
            out["token"] = r["token"]
            return self._send(out)
        if parts == ["auth", "login"]:
            if self._limited("login"):
                return
            try:
                r = accounts.login_password(body.get("email"), body.get("password"))
            except accounts.AuthError as e:
                return self._send({"error": str(e)}, 400)
            web = self._is_web() and self.headers.get("Origin", "") in ORIGINS
            out = {"user": self._public_user(r["user"]), "new": False}
            if web:
                return self._send(out, cookie=self._cookie(r["token"], accounts.SESSION_TTL))
            out["token"] = r["token"]
            return self._send(out)
        if parts == ["auth", "google", "poll"]:
            if self._limited("google"):
                return
            try:
                r = accounts.take_pickup(body.get("verifier"))
            except accounts.AuthError as e:
                return self._send({"error": str(e)}, 400)
            if not r:
                return self._send({"pending": True})
            return self._send({"user": self._public_user(r["user"]), "token": r["token"]})
        if parts == ["me", "password"]:
            if self._limited("me"):
                return
            user = self._auth(change=True)
            if not user:
                return self._send({"error": "sign in first"}, 401)
            try:
                accounts.set_password(user["id"], body.get("new"), body.get("current"))
            except accounts.AuthError as e:
                return self._send({"error": str(e)}, 400)
            return self._send({"ok": True})
        if parts == ["me", "username"]:
            if self._limited("me"):
                return
            user = self._auth(change=True)
            if not user:
                return self._send({"error": "sign in first"}, 401)
            try:
                name = accounts.rename(user["id"], body.get("username"))
            except accounts.AuthError as e:
                return self._send({"error": str(e)}, 400)
            with LOCK:                                         # keep the author name on existing builds in step
                idx = _read()
                for pid, e in idx.items():
                    if e.get("owner") == user["id"]:
                        e["meta"]["author"] = name
                        zp = STATE["dir"] / "zips" / (re.sub(r"[^a-z0-9-]", "", pid) + ".zip")
                        try:
                            paths.atomic_write_bytes(zp, stamp_author(zp.read_bytes(), name))
                        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                            pass
                _write(idx)
            return self._send({"ok": True, "username": name})
        if parts == ["auth", "logout"]:
            tok, _ = self._token()
            if self._auth(change=True) is not None:
                accounts.logout(tok)
            return self._send({"ok": True}, cookie=self._cookie("", 0))
        if parts == ["me", "delete"]:
            if self._limited("me"):
                return
            user = self._auth(change=True)
            if not user:
                return self._send({"error": "sign in first"}, 401)
            if body.get("confirm") != "delete my account":
                return self._send({"error": 'type "delete my account" to confirm'}, 400)
            with LOCK:
                idx = _read()
                for pid in [p for p, e in idx.items() if e.get("owner") == user["id"]]:
                    _drop_profile(idx, pid)
                _write(idx)
            accounts.delete_user(user["id"])
            return self._send({"ok": True}, cookie=self._cookie("", 0))
        self._send({"error": "not found"}, 404)

    # ---- beta downloads: an installer for testers at an unguessable address, not listed anywhere --------------------------------
    _BETA_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
    _BETA_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,78}\.(exe|zip)$")

    def _beta_dir(self, token):
        return STATE["dir"] / "beta" / token

    def _beta_put(self, parts, n):
        """POST /admin/beta/<token>/<file>: the operator puts an installer on the hub (needs the admin key)."""
        if self._limited("admin"):
            return
        if not (STATE["admin"] and secrets.compare_digest(self.headers.get("X-Admin", ""), STATE["admin"])):
            return self._send({"error": "not allowed"}, 403)
        token, name = parts[2], parts[3]
        if not (self._BETA_TOKEN.fullmatch(token) and self._BETA_NAME.fullmatch(name)) or n < 1:
            return self._send({"error": "bad name or token"}, 400)
        data = self.rfile.read(n)
        self._unread = 0
        d = self._beta_dir(token)
        d.mkdir(parents=True, exist_ok=True)
        paths.atomic_write_bytes(d / name, data)
        return self._send({"ok": True, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    def _beta_get(self, parts):
        """GET /beta/<token>/ shows a small download page, GET /beta/<token>/<file> sends the file (resumable)."""
        token = parts[1] if len(parts) > 1 else ""
        if not self._BETA_TOKEN.fullmatch(token) or len(parts) > 3:
            return self._send({"error": "not found"}, 404)
        d = self._beta_dir(token)
        if len(parts) == 2:
            files = sorted(p for p in d.glob("*") if p.is_file() and self._BETA_NAME.fullmatch(p.name)) if d.is_dir() else []
            if not files:
                return self._send({"error": "not found"}, 404)
            rows = "".join('<p><a class="b" href="/beta/%s/%s">Download %s (%.1f MB)</a></p><p class="s">SHA-256:<br><code>%s</code></p>' % (
                token, f.name, f.name, f.stat().st_size / 1048576, hashlib.sha256(f.read_bytes()).hexdigest()) for f in files)
            body = ("<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\"><meta name=robots content=\"noindex,nofollow\"><title>Plunge beta</title>"
                    "<style>body{font:16px/1.5 system-ui,sans-serif;background:#141414;color:#eee;max-width:560px;margin:8vh auto;padding:0 20px}"
                    "a.b{display:inline-block;background:#168bff;color:#fff;padding:12px 20px;border-radius:99px;text-decoration:none;font-weight:700}code{word-break:break-all;font-size:13px}.s{color:#aaa;font-size:14px}</style>"
                    "<h1>Plunge beta</h1><p>Thanks for testing. This is an early, unsigned version, so Windows will warn you: choose <b>More info</b>, then <b>Run anyway</b>.</p>"
                    "%s<p>Send feedback to support@plungevr.com</p></html>") % rows
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        name = parts[2]
        f = d / name
        if not self._BETA_NAME.fullmatch(name) or not f.is_file():
            return self._send({"error": "not found"}, 404)
        if self._limited("beta"):
            return
        size = f.stat().st_size
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range", "")
        m = re.fullmatch(r"bytes=(\d+)-(\d*)", rng.strip())
        if m:                                                    # a browser resuming an interrupted download
            start = int(m.group(1))
            end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        if code == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            with open(f, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(1024 * 1024, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    def do_GET(self):
        if self.path == "/health":                              # for the uptime monitor and the container health check
            return self._send({"ok": True, "service": "hub"})
        if self._limited("read"):
            return
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = parse_qs(u.query)
        if parts and parts[0] == "beta":
            return self._beta_get(parts)
        if parts and parts[0] == "auth":
            return self._auth_get(parts, q)
        if parts and parts[0] == "me":
            user = self._auth()
            if not user:
                return self._send({"error": "not signed in"}, 401)
            if parts == ["me"]:
                return self._send({"user": self._public_user(user)})
            if parts == ["me", "profiles"]:
                with LOCK:
                    idx = _read()
                    return self._send({"profiles": sorted((_row(i, e) for i, e in idx.items() if e.get("owner") == user["id"]), key=lambda r: -r["created"])})
            return self._send({"error": "not found"}, 404)
        with LOCK:
            idx = _read()
            if parts == ["profiles"]:
                rows = [_row(i, e) for i, e in idx.items()]
                appid, text, sort, tier, mpq = (q.get(k, [""])[0][:80] for k in ("appid", "q", "sort", "tier", "mp"))
                if tier:
                    rows = [r for r in rows if r["tier"] == tier]
                if mpq == "1":
                    rows = [r for r in rows if r["multiplayer"]]
                if appid:
                    rows = [r for r in rows if r["steamAppId"] == appid]
                if text:
                    t = text.lower()
                    rows = [r for r in rows if t in r["title"].lower() or t in r["author"].lower() or t in r["tagline"].lower()]
                if sort == "featured":
                    rows = [r for r in rows if r["featured"]]
                elif sort == "liked":
                    rows.sort(key=lambda r: (-r["likes"], -r["downloads"]))
                elif sort == "popular":
                    rows.sort(key=lambda r: -(r["downloads"] + 3 * r["likes"]))
                else:
                    rows.sort(key=lambda r: -r["created"])
                return self._send({"profiles": rows[:60]})
            if len(parts) == 2 and parts[0] == "profiles":
                e = idx.get(parts[1])
                return self._send(_row(parts[1], e)) if e else self._send({"error": "not found"}, 404)
            if len(parts) == 3 and parts[0] == "profiles" and parts[2] == "download":
                e = idx.get(parts[1])
                zp = STATE["dir"] / "zips" / (re.sub(r"[^a-z0-9-]", "", parts[1]) + ".zip")
                if not e or not zp.exists():
                    return self._send({"error": "not found"}, 404)
                e["downloads"] += 1
                _write(idx)
                return self._send(None, raw=zp.read_bytes(), ctype="application/zip", filename=zp.name)
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send({"error": "bad Content-Length"}, 400)
        if n < 0 or n > MAX_ZIP:
            return self._send({"error": "upload too large"}, 413)
        self._unread = n
        if len(parts) == 4 and parts[:2] == ["admin", "beta"]:
            return self._beta_put(parts, n)
        if parts and parts[0] in ("auth", "me"):
            return self._account_post(parts, n)
        if parts == ["profiles"]:
            if self._limited("upload"):
                return
            user = self._auth(change=True)
            if STATE["require_auth"] and not user:
                return self._send({"error": "sign in to publish a profile"}, 401)
            body = self.rfile.read(n)
            self._unread = 0
            try:
                meta = accept(body)
                if user:                                       # the author is always the account, never what the uploader typed
                    body = stamp_author(body, user["username"])
                    meta["author"] = user["username"]
            except ValueError as e:
                return self._send({"error": str(e)}, 400)
            pid = re.sub(r"[^a-z0-9]+", "-", str(meta.get("title", "profile")).lower()).strip("-")[:40] + "-" + secrets.token_hex(3)
            with LOCK:
                idx = _read()
                zips = STATE["dir"] / "zips"
                used = sum(f.stat().st_size for f in zips.glob("*.zip")) if zips.exists() else 0
                if len(idx) >= MAX_PROFILES or used + len(body) > MAX_STORE:
                    return self._send({"error": "the hub is full right now"}, 507)
                zips.mkdir(parents=True, exist_ok=True)
                paths.atomic_write_bytes(zips / (pid + ".zip"), body)
                idx[pid] = {"meta": meta, "downloads": 0, "likes": 0, "created": time.time(), "featured": False, "owner": user["id"] if user else None, "likedBy": []}
                _write(idx)
            return self._send({"id": pid})
        self.rfile.read(min(n, 4096))
        self._unread = max(0, n - 4096)
        if len(parts) == 3 and parts[0] == "profiles":
            user = self._auth(change=True)
            if parts[2] == "like":
                if STATE["require_auth"] and not user:
                    return self._send({"error": "sign in to like a profile"}, 401)
                if user:                                                            # a signed-in like is limited per account (see below)
                    if self._limited("like"):
                        return
                elif self._limited("like") or self._limited("likeone", parts[1]):   # anonymous (private hubs): per address overall, one per profile a day
                    return
            if parts[2] in ("feature", "remove") and self._limited("admin"):
                return
            admin = bool(STATE["admin"]) and secrets.compare_digest(self.headers.get("X-Admin", ""), STATE["admin"])
            with LOCK:
                idx = _read()
                e = idx.get(parts[1])
                if not e:
                    return self._send({"error": "not found"}, 404)
                if parts[2] == "like":
                    lb = e.setdefault("likedBy", [])
                    if user and user["id"] in lb:              # one like per account per profile
                        return self._send({"ok": True, "likes": e["likes"], "featured": e["featured"], "already": True})
                    e["likes"] += 1
                    if user and len(lb) < 20000:
                        lb.append(user["id"])
                elif parts[2] == "feature":
                    if not admin:
                        return self._send({"error": "admin only"}, 403)
                    e["featured"] = not e["featured"]
                elif parts[2] == "remove":                 # the person who published it, or the operator (admin key), can take a profile down
                    if not (admin or (user and e.get("owner") is not None and e.get("owner") == user["id"])):
                        return self._send({"error": "only the author or the operator can remove this"}, 403)
                    _drop_profile(idx, parts[1])
                    _write(idx)
                    return self._send({"ok": True, "removed": parts[1]})
                else:
                    return self._send({"error": "not found"}, 404)
                _write(idx)
                return self._send({"ok": True, "likes": e["likes"], "featured": e["featured"]})
        self._send({"error": "not found"}, 404)


def serve(port=8788, bind="127.0.0.1", data=None):
    if data:
        STATE["dir"] = Path(data)
    accounts.init(STATE["dir"])
    srv = ThreadingHTTPServer((bind, port), Handler)
    print("Plunge hub on http://%s:%d (data: %s)" % (bind, port, STATE["dir"].resolve()))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
