"""Plunge accounts: three ways in, all ending in the same account.

  * email + password (the address is proven with an emailed code when you sign up; passwords are stored only as scrypt hashes)
  * an emailed 6-digit code (no password needed; also how you recover a forgotten password)
  * Google (the account is matched by Google's verified email, so one person has one account)

Codes, session tokens and passwords are never stored in a usable form, so a copy of the database cannot be used to sign in as anyone.
Everything lives in one small SQLite file in the hub's data folder.

This module has the rules and the storage. hub_server.py wires it to HTTP.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CODE_TTL = 10 * 60               # a code works for 10 minutes
CODE_TRIES = 5                   # and for 5 wrong guesses
RESEND_GAP = 45                  # seconds before another code can be requested for the same email
SESSION_TTL = 90 * 24 * 3600
MAX_SESSIONS = 10                # per account; the oldest are dropped
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,23}$")
RESERVED = {"admin", "administrator", "plunge", "plungevr", "support", "security", "copyright", "staff", "moderator", "mod", "official",
            "system", "root", "null", "undefined", "anonymous", "me", "hub", "lobby", "melty"}
LOCK = threading.RLock()
STATE = {"db": None, "secret": b"", "sent_today": (0, 0)}
PW_MIN, PW_MAX = 10, 200
LOCKOUT_TRIES, LOCKOUT_WINDOW = 8, 15 * 60          # 8 wrong passwords for one email in 15 minutes locks password sign-in for that email for 15 minutes
GOOGLE_STATE_TTL = 10 * 60
COMMON_PASSWORDS = {"password", "password1", "1234567890", "12345678910", "qwertyuiop", "iloveyou12", "letmein123", "welcome123", "plungevr123", "passw0rd123",
                    "1q2w3e4r5t", "abcdefghij", "0123456789", "password123", "qwerty12345", "admin12345", "changeme123"}
DAILY_EMAIL_CAP = int(os.environ.get("PLUNGE_EMAIL_DAILY_CAP", "90"))      # Resend's free plan allows 100 a day


class AuthError(ValueError):
    """A problem the person can fix (wrong code, taken username...). The message is safe to show them."""


def init(data_dir):
    """Open (and create) the account database and the secret used to key the hashes."""
    d = Path(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    sec = d / ".secret"
    if not sec.exists():
        sec.write_bytes(secrets.token_bytes(32))
        try:
            os.chmod(sec, 0o600)
        except OSError:
            pass
    STATE["secret"] = bytes.fromhex(os.environ["PLUNGE_HUB_SECRET"]) if os.environ.get("PLUNGE_HUB_SECRET") else sec.read_bytes()
    db = sqlite3.connect(str(d / "accounts.db"), check_same_thread=False, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, username TEXT UNIQUE NOT NULL COLLATE NOCASE, created REAL NOT NULL, password TEXT, google_sub TEXT);
        CREATE TABLE IF NOT EXISTS fails(email TEXT PRIMARY KEY, n INTEGER NOT NULL, first REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS pickups(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, challenge TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS logins(email TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires REAL NOT NULL, tries INTEGER NOT NULL DEFAULT 0, sent REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created REAL NOT NULL, expires REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
    """)
    cols = {r[1] for r in db.execute("PRAGMA table_info(users)")}          # accounts made before passwords and Google existed
    for col in ("password", "google_sub"):
        if col not in cols:
            db.execute("ALTER TABLE users ADD COLUMN %s TEXT" % col)
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_google ON users(google_sub) WHERE google_sub IS NOT NULL")
    STATE["db"] = db


def _h(kind, value):
    return hmac.new(STATE["secret"], ("%s:%s" % (kind, value)).encode(), hashlib.sha256).hexdigest()


def normalize_email(text):
    e = str(text or "").strip().lower()
    if len(e) > 254 or not EMAIL_RE.fullmatch(e):
        raise AuthError("that doesn't look like an email address")
    return e


def clean_username(text):
    u = str(text or "").strip()
    if not NAME_RE.fullmatch(u):
        raise AuthError("usernames are 3 to 24 letters, numbers, - or _, and start with a letter or number")
    if u.lower() in RESERVED:
        raise AuthError("that username is reserved")
    return u


# ---- email ------------------------------------------------------------------------------------------------------------------------
def send_code_email(email, code):
    """Mail the code through Resend. The key is the RESEND_API_KEY setting on the server."""
    key = os.environ.get("RESEND_API_KEY", "")
    if not key:
        raise RuntimeError("email is not set up on this server")
    sender = os.environ.get("PLUNGE_MAIL_FROM", "Plunge <no-reply@plungevr.com>")
    body = {"from": sender, "to": [email], "subject": "Your Plunge sign-in code: %s" % code,
            "text": "Your Plunge sign-in code is %s.\n\nIt works for 10 minutes. If you didn't ask for it, you can ignore this email: nobody can sign in without the code." % code,
            "html": ('<div style="font-family:Arial,sans-serif;font-size:16px;color:#111"><p>Your Plunge sign-in code is</p>'
                     '<p style="font-size:32px;font-weight:700;letter-spacing:6px;margin:8px 0">%s</p>'
                     '<p style="color:#555">It works for 10 minutes. If you didn\'t ask for it, you can ignore this email: nobody can sign in without the code.</p></div>') % code}
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "plunge-hub/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            r.read(2048)
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError("couldn't send the email") from e


MAILER = send_code_email           # tests swap this for a stand-in so no real email is sent


def _budget():
    """A hard daily cap on emails, so nobody can use the hub to spam strangers or burn the mail quota."""
    day = int(time.time() // 86400)
    d, n = STATE["sent_today"]
    if d != day:
        d, n = day, 0
    if n >= DAILY_EMAIL_CAP:
        raise AuthError("sign-in emails are paused for today, please try again tomorrow")
    STATE["sent_today"] = (d, n + 1)


# ---- sign in ------------------------------------------------------------------------------------------------------------------------
def start_login(email):
    """Create a code for `email` and mail it. Returns nothing: the answer never reveals whether the address already has an account."""
    email = normalize_email(email)
    with LOCK:
        db = STATE["db"]
        row = db.execute("SELECT sent FROM logins WHERE email=?", (email,)).fetchone()
        if row and time.time() - row[0] < RESEND_GAP:
            raise AuthError("a code was just sent: check your inbox, or wait a moment to ask for another")
        _budget()
        code = "%06d" % secrets.randbelow(1000000)
        now = time.time()
        db.execute("INSERT OR REPLACE INTO logins(email, code_hash, expires, tries, sent) VALUES(?,?,?,?,?)", (email, _h("code:" + email, code), now + CODE_TTL, 0, now))
    try:
        MAILER(email, code)
    except Exception:
        with LOCK:
            STATE["db"].execute("DELETE FROM logins WHERE email=?", (email,))
        raise


def _new_session(uid):
    token = secrets.token_urlsafe(32)
    now = time.time()
    db = STATE["db"]
    db.execute("INSERT INTO sessions(hash, user_id, created, expires) VALUES(?,?,?,?)", (_h("session", token), uid, now, now + SESSION_TTL))
    db.execute("DELETE FROM sessions WHERE user_id=? AND hash NOT IN (SELECT hash FROM sessions WHERE user_id=? ORDER BY created DESC LIMIT ?)", (uid, uid, MAX_SESSIONS))
    return token


USER_COLS = "id, email, username, created, password IS NOT NULL, google_sub IS NOT NULL"


def _user(row):
    return {"id": row[0], "email": row[1], "username": row[2], "created": row[3], "hasPassword": bool(row[4]), "hasGoogle": bool(row[5])}


def verify_login(email, code, username=None, password=None):
    """Check the code. Returns {"token", "user", "new"}, or {"needUsername": True} when this is a new address and no username was given yet.
    A new account may also set a password right away (optional). The password is checked before the code is used up."""
    email = normalize_email(email)
    code = re.sub(r"\s+", "", str(code or ""))
    with LOCK:
        db = STATE["db"]
        row = db.execute("SELECT code_hash, expires, tries FROM logins WHERE email=?", (email,)).fetchone()
        if not row or row[1] < time.time():
            raise AuthError("that code has expired: ask for a new one")
        if row[2] >= CODE_TRIES:
            db.execute("DELETE FROM logins WHERE email=?", (email,))
            raise AuthError("too many wrong codes: ask for a new one")
        if not re.fullmatch(r"\d{6}", code) or not hmac.compare_digest(row[0], _h("code:" + email, code)):
            db.execute("UPDATE logins SET tries=tries+1 WHERE email=?", (email,))
            raise AuthError("that code isn't right")
        u = db.execute("SELECT %s FROM users WHERE email=?" % USER_COLS, (email,)).fetchone()
        new = False
        if not u:
            if not username:
                return {"needUsername": True}
            name = clean_username(username)
            if password:
                check_password(password, email, name)
            if db.execute("SELECT 1 FROM users WHERE username=?", (name,)).fetchone():
                raise AuthError("that username is taken")
            pw = hash_password(password, email, name) if password else None
            db.execute("INSERT INTO users(email, username, created, password) VALUES(?,?,?,?)", (email, name, time.time(), pw))
            u = db.execute("SELECT %s FROM users WHERE email=?" % USER_COLS, (email,)).fetchone()
            new = True
        db.execute("DELETE FROM logins WHERE email=?", (email,))
        return {"token": _new_session(u[0]), "user": _user(u), "new": new}


def session_user(token):
    """The account for a session token, or None. Valid sessions are kept alive while they are used."""
    if not token or not isinstance(token, str) or len(token) > 100:
        return None
    with LOCK:
        db = STATE["db"]
        h = _h("session", token)
        row = db.execute("SELECT s.expires, s.created, u.id, u.email, u.username, u.created, u.password IS NOT NULL, u.google_sub IS NOT NULL FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.hash=?", (h,)).fetchone()
        if not row:
            return None
        if row[0] < time.time():
            db.execute("DELETE FROM sessions WHERE hash=?", (h,))
            return None
        if row[0] - time.time() < SESSION_TTL - 24 * 3600:
            db.execute("UPDATE sessions SET expires=? WHERE hash=?", (time.time() + SESSION_TTL, h))
        return _user(row[2:])


def logout(token):
    if token:
        with LOCK:
            STATE["db"].execute("DELETE FROM sessions WHERE hash=?", (_h("session", token),))


def delete_user(uid):
    """Remove the account and every session. (The hub removes the person's uploads separately.)"""
    with LOCK:
        db = STATE["db"]
        db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        db.execute("DELETE FROM users WHERE id=?", (uid,))


def purge_expired():
    with LOCK:
        now = time.time()
        STATE["db"].execute("DELETE FROM logins WHERE expires<?", (now,))
        STATE["db"].execute("DELETE FROM sessions WHERE expires<?", (now,))


# ---- passwords ------------------------------------------------------------------------------------------------------------------------
def check_password(pw, email="", username=""):
    """The rules: 10 to 200 characters, not an obvious password, not your email or username. No 'must contain a symbol' rules."""
    pw = str(pw or "")
    if len(pw) < PW_MIN:
        raise AuthError("use at least %d characters" % PW_MIN)
    if len(pw) > PW_MAX:
        raise AuthError("that password is too long (the limit is %d characters)" % PW_MAX)
    low = pw.lower()
    if low in COMMON_PASSWORDS or len(set(low)) < 4:
        raise AuthError("that password is too easy to guess")
    if email and low in (email.lower(), email.lower().split("@")[0]) or (username and low == username.lower()):
        raise AuthError("your password can't be your email or username")
    return pw


def hash_password(pw, email="", username=""):
    check_password(pw, email, username)
    n, r, p = 2 ** 14, 8, 1
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (n, r, p, salt.hex(), dk.hex())


_DUMMY = None


def verify_password(stored, pw):
    """Constant-time check. A missing stored hash is checked against a dummy one so timing doesn't reveal which emails have passwords."""
    global _DUMMY
    pw = str(pw or "")[:PW_MAX + 1]
    if not stored:
        if _DUMMY is None:
            _DUMMY = hash_password("not-a-real-password-0")
        stored, ok_if = _DUMMY, False
    else:
        ok_if = True
    try:
        _, n, r, p, salt, want = stored.split("$")
        dk = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(dk.hex(), want) and ok_if
    except (ValueError, TypeError):
        return False


def _locked(db, email):
    row = db.execute("SELECT n, first FROM fails WHERE email=?", (email,)).fetchone()
    if row and time.time() - row[1] > LOCKOUT_WINDOW:
        db.execute("DELETE FROM fails WHERE email=?", (email,))
        return False
    return bool(row and row[0] >= LOCKOUT_TRIES)


def login_password(email, password):
    """Sign in with email + password. Every failure gives the same message; too many failures lock password sign-in for that email for a while."""
    email = normalize_email(email)
    with LOCK:
        db = STATE["db"]
        if _locked(db, email):
            raise AuthError("too many wrong passwords: try again in a few minutes, or sign in with an emailed code")
        u = db.execute("SELECT %s, password FROM users WHERE email=?" % USER_COLS, (email,)).fetchone()
        ok = verify_password(u[6] if u else None, password) and u is not None
        if not ok:
            row = db.execute("SELECT n FROM fails WHERE email=?", (email,)).fetchone()
            if row:
                db.execute("UPDATE fails SET n=n+1 WHERE email=?", (email,))
            else:
                db.execute("INSERT INTO fails(email, n, first) VALUES(?,?,?)", (email, 1, time.time()))
            raise AuthError("wrong email or password")
        db.execute("DELETE FROM fails WHERE email=?", (email,))
        return {"token": _new_session(u[0]), "user": _user(u[:6]), "new": False}


def set_password(uid, new, current=None):
    """Set or change the password for a signed-in account. Changing an existing one needs the current one."""
    with LOCK:
        db = STATE["db"]
        row = db.execute("SELECT email, username, password FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            raise AuthError("account not found")
        if row[2] and not verify_password(row[2], current):
            raise AuthError("your current password isn't right")
        db.execute("UPDATE users SET password=? WHERE id=?", (hash_password(new, row[0], row[1]), uid))


def rename(uid, username):
    name = clean_username(username)
    with LOCK:
        db = STATE["db"]
        if db.execute("SELECT 1 FROM users WHERE username=? AND id<>?", (name, uid)).fetchone():
            raise AuthError("that username is taken")
        db.execute("UPDATE users SET username=? WHERE id=?", (name, uid))
    return name


# ---- Google ---------------------------------------------------------------------------------------------------------------------------
def google_config():
    cid, sec = os.environ.get("GOOGLE_CLIENT_ID", ""), os.environ.get("GOOGLE_CLIENT_SECRET", "")
    return (cid, sec) if cid and sec else None


def public_url():
    return os.environ.get("PLUNGE_PUBLIC_URL", "https://hub.plungevr.com").rstrip("/")


def sign_state(payload):
    """A tamper-proof, expiring token for the OAuth round trip: {mode, challenge, nonce}."""
    body = dict(payload, exp=int(time.time()) + GOOGLE_STATE_TTL)
    raw = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode().rstrip("=")
    return raw + "." + _h("oauth-state", raw)


def read_state(token):
    try:
        raw, sig = str(token).split(".")
        if not hmac.compare_digest(sig, _h("oauth-state", raw)):
            raise ValueError
        body = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if not isinstance(body, dict) or body.get("exp", 0) < time.time():
            raise ValueError
        return body
    except (ValueError, TypeError):
        raise AuthError("that Google sign-in link expired: please try again")


def google_auth_url(mode, challenge=""):
    """Where to send the person to sign in with Google, plus the cookie value that binds the round trip to this browser."""
    cfg = google_config()
    if not cfg:
        raise AuthError("Google sign-in isn't set up on this hub")
    if mode not in ("web", "app"):
        raise AuthError("bad request")
    if mode == "app" and not re.fullmatch(r"[0-9a-f]{64}", challenge or ""):
        raise AuthError("bad request")
    nonce = secrets.token_urlsafe(16)
    state = sign_state({"mode": mode, "challenge": challenge, "nonce": nonce})
    q = urllib.parse.urlencode({"client_id": cfg[0], "redirect_uri": public_url() + "/auth/google/callback", "response_type": "code", "scope": "openid email profile",
                                "state": state, "prompt": "select_account", "access_type": "online"})
    return "https://accounts.google.com/o/oauth2/v2/auth?" + q, nonce


def google_exchange(code):
    """Trade Google's one-time code for the person's verified identity. The answer comes straight from Google over TLS."""
    cfg = google_config()
    body = urllib.parse.urlencode({"code": code, "client_id": cfg[0], "client_secret": cfg[1], "redirect_uri": public_url() + "/auth/google/callback", "grant_type": "authorization_code"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "plunge-hub/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            tok = json.loads(r.read(100000))
        payload = tok["id_token"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError):
        raise AuthError("Google didn't accept that sign-in: please try again")
    if claims.get("iss") not in ("https://accounts.google.com", "accounts.google.com") or claims.get("aud") != cfg[0] or claims.get("exp", 0) < time.time():
        raise AuthError("Google's answer wasn't valid")
    return claims


EXCHANGE = google_exchange          # tests swap this for a stand-in so no real Google call is made


def _auto_username(db, email, name=""):
    base = re.sub(r"[^A-Za-z0-9_-]", "", (email.split("@")[0] or name or "player"))[:16].lstrip("_-") or "player"
    while len(base) < 3:
        base += "x"
    if base.lower() in RESERVED:
        base += "-vr"
    cand = base
    while db.execute("SELECT 1 FROM users WHERE username=?", (cand,)).fetchone():
        cand = "%s%d" % (base[:19], secrets.randbelow(9000) + 1000)
    return cand


def google_login(claims):
    """Match Google's verified identity to an account: by Google id, else by the verified email (so the same person never gets two accounts), else make one."""
    if not claims.get("email_verified") in (True, "true"):
        raise AuthError("your Google email isn't verified, so Plunge can't use it")
    sub = str(claims.get("sub") or "")
    email = normalize_email(claims.get("email"))
    if not sub:
        raise AuthError("Google's answer wasn't valid")
    with LOCK:
        db = STATE["db"]
        u = db.execute("SELECT %s FROM users WHERE google_sub=?" % USER_COLS, (sub,)).fetchone()
        new = False
        if not u:
            u = db.execute("SELECT %s FROM users WHERE email=?" % USER_COLS, (email,)).fetchone()
            if u:
                db.execute("UPDATE users SET google_sub=? WHERE id=?", (sub, u[0]))
            else:
                db.execute("INSERT INTO users(email, username, created, google_sub) VALUES(?,?,?,?)", (email, _auto_username(db, email, claims.get("name", "")), time.time(), sub))
                new = True
            u = db.execute("SELECT %s FROM users WHERE email=?" % USER_COLS, (email,)).fetchone()
        return u, new


def stash_pickup(user_id, challenge):
    """The app can't receive Google's redirect, so the hub holds the result for a few minutes until the app asks for it with its secret."""
    pid = secrets.token_urlsafe(18)
    with LOCK:
        STATE["db"].execute("INSERT INTO pickups(id, user_id, challenge, expires) VALUES(?,?,?,?)", (pid, user_id, challenge, time.time() + 300))


def take_pickup(verifier):
    """The app proves it started the sign-in by presenting the secret whose hash it gave us. One use only; then a session is created."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,100}", str(verifier or "")):
        raise AuthError("bad request")
    ch = hashlib.sha256(verifier.encode()).hexdigest()
    with LOCK:
        db = STATE["db"]
        db.execute("DELETE FROM pickups WHERE expires<?", (time.time(),))
        row = db.execute("SELECT id, user_id FROM pickups WHERE challenge=?", (ch,)).fetchone()
        if not row:
            return None
        db.execute("DELETE FROM pickups WHERE id=?", (row[0],))
        u = db.execute("SELECT %s FROM users WHERE id=?" % USER_COLS, (row[1],)).fetchone()
        return {"token": _new_session(u[0]), "user": _user(u)} if u else None
