"""Passwords and Google sign-in on the hub. Google itself is replaced by a stand-in: no real Google or email traffic."""
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import accounts, hub_server

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


def raises(fn, text=None):
    try:
        fn()
    except accounts.AuthError as e:
        return text is None or text in str(e)
    except Exception:
        return False
    return False


# ---- an old database (made before passwords and Google existed) is upgraded in place ------------------------------------------------
old = Path(tempfile.mkdtemp())
con = sqlite3.connect(str(old / "accounts.db"))
con.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, username TEXT UNIQUE NOT NULL COLLATE NOCASE, created REAL NOT NULL);"
                  "INSERT INTO users(email, username, created) VALUES('old@example.com','OldUser',1);")
con.commit()
con.close()
accounts.init(old)
cols = {r[1] for r in accounts.STATE["db"].execute("PRAGMA table_info(users)")}
check("an older account database gains the new columns and keeps its users", {"password", "google_sub"} <= cols and accounts.STATE["db"].execute("SELECT username FROM users").fetchone()[0] == "OldUser")
accounts.STATE["db"].close()

tmp = Path(tempfile.mkdtemp())
hub_server.STATE.update({"dir": tmp, "admin": "k" * 40, "require_auth": True})
accounts.init(tmp)
SENT = []
accounts.MAILER = lambda e, c: SENT.append((e, c))
accounts.RESEND_GAP = 0
db = accounts.STATE["db"]

# ---- password rules and hashing ---------------------------------------------------------------------------------------------------------
check("short passwords are refused", raises(lambda: accounts.check_password("short"), "at least 10"))
check("obvious passwords are refused", raises(lambda: accounts.check_password("password123"), "easy to guess") and raises(lambda: accounts.check_password("aaaaaaaaaaaa"), "easy to guess"))
check("a password can't be the email or username", raises(lambda: accounts.check_password("someone@example.com", "someone@example.com", "x1"), "email or username")
      and raises(lambda: accounts.check_password("MyUsername99", "a@b.com", "MyUsername99"), "email or username"))
check("very long passwords are refused (no hashing a megabyte)", raises(lambda: accounts.check_password("x" * 201 + "ab1"), "too long"))
check("a normal passphrase is fine, with no symbol rules", accounts.check_password("correct horse battery staple") == "correct horse battery staple")
h = accounts.hash_password("correct horse battery staple", "a@b.com", "ab1")
check("passwords are stored as salted scrypt hashes", h.startswith("scrypt$") and "correct" not in h and h != accounts.hash_password("correct horse battery staple", "a@b.com", "ab1"))
check("the right password verifies and a wrong one does not", accounts.verify_password(h, "correct horse battery staple") and not accounts.verify_password(h, "correct horse battery stapl") and not accounts.verify_password(h, ""))
check("a missing or damaged hash never verifies", not accounts.verify_password(None, "x" * 12) and not accounts.verify_password("garbage", "x" * 12) and not accounts.verify_password("scrypt$a$b$c$d$e", "x"))

# ---- sign up with a password ------------------------------------------------------------------------------------------------------------------
accounts.start_login("pw@example.com")
code = SENT[-1][1]
check("a weak password is rejected without using up the code", raises(lambda: accounts.verify_login("pw@example.com", code, "pwuser", "short"), "at least 10")
      and accounts.STATE["db"].execute("SELECT COUNT(*) FROM logins WHERE email='pw@example.com'").fetchone()[0] == 1)
r = accounts.verify_login("pw@example.com", code, "pwuser", "a long enough passphrase")
check("signing up with a password works and the account knows it has one", r["new"] and r["user"]["hasPassword"] is True)
raw = b""
for f in ("accounts.db", "accounts.db-wal"):
    if (tmp / f).exists():
        with open(tmp / f, "rb") as fh:
            raw += fh.read()
check("the password is not in the database in any readable form", b"a long enough passphrase" not in raw)
l = accounts.login_password("PW@example.com", "a long enough passphrase")
check("signing in with email and password works (email is case-insensitive)", l["user"]["username"] == "pwuser" and accounts.session_user(l["token"])["username"] == "pwuser")
check("a wrong password and an unknown email give the same message", raises(lambda: accounts.login_password("pw@example.com", "not the password"), "wrong email or password")
      and raises(lambda: accounts.login_password("nobody@example.com", "not the password"), "wrong email or password"))
# accounts made with only a code have no password
accounts.start_login("nopw@example.com")
accounts.verify_login("nopw@example.com", SENT[-1][1], "nopw", None)
check("an account without a password can't be entered with one", raises(lambda: accounts.login_password("nopw@example.com", "anything at all here"), "wrong email or password"))
# lockout
for _ in range(accounts.LOCKOUT_TRIES):
    raises(lambda: accounts.login_password("pw@example.com", "wrong wrong wrong"))
check("repeated wrong passwords lock password sign-in for that email", raises(lambda: accounts.login_password("pw@example.com", "a long enough passphrase"), "too many wrong passwords"))
check("the emailed-code sign-in still works while locked", (lambda: (accounts.start_login("pw@example.com"), accounts.verify_login("pw@example.com", SENT[-1][1])["user"]["username"] == "pwuser")[1])())
db.execute("UPDATE fails SET first=? WHERE email='pw@example.com'", (time.time() - accounts.LOCKOUT_WINDOW - 5,))
check("the lock ends after the window", accounts.login_password("pw@example.com", "a long enough passphrase")["user"]["username"] == "pwuser")
uid = db.execute("SELECT id FROM users WHERE email='pw@example.com'").fetchone()[0]
check("changing a password needs the current one", raises(lambda: accounts.set_password(uid, "another long passphrase", "wrong current"), "current password"))
accounts.set_password(uid, "another long passphrase", "a long enough passphrase")
check("the new password works and the old one stops", accounts.login_password("pw@example.com", "another long passphrase") and raises(lambda: accounts.login_password("pw@example.com", "a long enough passphrase")))
nid = db.execute("SELECT id FROM users WHERE email='nopw@example.com'").fetchone()[0]
accounts.set_password(nid, "brand new passphrase!")
check("an account with no password can set one when signed in", accounts.login_password("nopw@example.com", "brand new passphrase!")["user"]["hasPassword"] is True)
check("renaming works, and taken or invalid names are refused", accounts.rename(uid, "Renamed_1") == "Renamed_1" and raises(lambda: accounts.rename(uid, "nopw"), "taken") and raises(lambda: accounts.rename(uid, "x"), "usernames"))

# ---- Google (stand-in) ---------------------------------------------------------------------------------------------------------------------------
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("GOOGLE_CLIENT_SECRET", None)
check("Google is off until it is configured", accounts.google_config() is None and raises(lambda: accounts.google_auth_url("web"), "isn't set up"))
os.environ["GOOGLE_CLIENT_ID"] = "client-id-123.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "client-secret"
os.environ["PLUNGE_PUBLIC_URL"] = "https://hub.plungevr.com"
url, nonce = accounts.google_auth_url("web")
q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
check("the Google link has the right client, redirect, scopes and a signed state", url.startswith("https://accounts.google.com/o/oauth2/v2/auth?") and q["client_id"] == ["client-id-123.apps.googleusercontent.com"]
      and q["redirect_uri"] == ["https://hub.plungevr.com/auth/google/callback"] and "openid" in q["scope"][0] and accounts.read_state(q["state"][0])["nonce"] == nonce)
st = accounts.sign_state({"mode": "web", "challenge": "", "nonce": "n"})
check("a tampered state is refused", raises(lambda: accounts.read_state(st[:-3] + "AAA"), "expired") and raises(lambda: accounts.read_state("junk"), "expired") and raises(lambda: accounts.read_state(None), "expired"))
old_ttl, accounts.GOOGLE_STATE_TTL = accounts.GOOGLE_STATE_TTL, -5
expired = accounts.sign_state({"mode": "web", "nonce": "n"})
accounts.GOOGLE_STATE_TTL = old_ttl
check("an expired state is refused", raises(lambda: accounts.read_state(expired), "expired"))
check("an app sign-in needs a proper challenge", raises(lambda: accounts.google_auth_url("app", "short"), "bad request") and raises(lambda: accounts.google_auth_url("other"), "bad request"))

GOOGLE = {"sub": "g-111", "email": "gal@example.com", "email_verified": True, "name": "Gal", "iss": "https://accounts.google.com", "aud": "client-id-123.apps.googleusercontent.com", "exp": time.time() + 600}
accounts.EXCHANGE = lambda code: dict(GOOGLE) if code == "good-code" else (_ for _ in ()).throw(accounts.AuthError("Google didn't accept that sign-in: please try again"))
u, new = accounts.google_login(GOOGLE)
check("a new Google user gets an account with a made-up username", new and u[2] == "gal" and u[5] == 1 and u[4] == 0)
u2, new2 = accounts.google_login(GOOGLE)
check("signing in with Google again finds the same account", not new2 and u2[0] == u[0])
check("a Google user whose email isn't verified is refused", raises(lambda: accounts.google_login({**GOOGLE, "sub": "g-2", "email": "x@example.com", "email_verified": False}), "isn't verified"))
# link by verified email
r = accounts.verify_login("link@example.com", (accounts.start_login("link@example.com"), SENT[-1][1])[1], "linkuser", "a long enough passphrase")
ul, nl = accounts.google_login({**GOOGLE, "sub": "g-222", "email": "link@example.com"})
check("Google with the same verified email joins the existing account instead of making a second", not nl and ul[0] == r["user"]["id"] and ul[2] == "linkuser")
check("the linked account can still use its password", accounts.login_password("link@example.com", "a long enough passphrase")["user"]["hasGoogle"] is True)
db.execute("INSERT INTO users(email, username, created) VALUES('taken@example.com','gal2',1)")
u3, _ = accounts.google_login({**GOOGLE, "sub": "g-333", "email": "gal2@example.com"})
u4, _ = accounts.google_login({**GOOGLE, "sub": "g-444", "email": "gal2@other.com"})
check("made-up usernames never clash with existing ones", u3[2] != "gal2" and u4[2] not in ("gal2", u3[2]))

# ---- over HTTP ---------------------------------------------------------------------------------------------------------------------------------------------
srv = ThreadingHTTPServer(("127.0.0.1", 0), hub_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_address[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


opener = urllib.request.build_opener(NoRedirect)


def call(path, body=None, headers=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    h = dict(headers or {})
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data if (data is not None or method == "POST") else None, headers=h, method=method or ("POST" if data is not None else "GET"))
    if method == "POST" and data is None:
        req.data = b"{}"
    try:
        r = opener.open(req, timeout=10)
        b = r.read()
        return r.status, (json.loads(b) if b and r.headers.get_content_type() == "application/json" else b), r.headers
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b), e.headers
        except ValueError:
            return e.code, b, e.headers


hub_server.LIMITER.hits.clear()
st, cfg, _ = call("/auth/config")
check("the apps can ask whether Google is on", st == 200 and cfg["google"] is True and cfg["passwordMin"] == 10)
st, body, hd = call("/auth/login", {"email": "pw@example.com", "password": "another long passphrase"})
check("password sign-in works over HTTP and gives the app a token", st == 200 and body["token"] and body["user"]["hasPassword"] is True)
tok = body["token"]
st, body, _ = call("/auth/login", {"email": "pw@example.com", "password": "nope nope nope"})
check("a wrong password over HTTP is a clear 400", st == 400 and body["error"] == "wrong email or password")
web = {"Origin": "https://plungevr.com", "X-Plunge-Client": "web"}
st, body, hd = call("/auth/login", {"email": "pw@example.com", "password": "another long passphrase"}, web)
check("a browser's password sign-in gets a cookie and no token", "plunge_session=" in hd.get("Set-Cookie", "") and "token" not in body and "HttpOnly" in hd.get("Set-Cookie", ""))
bearer = {"Authorization": "Bearer " + tok}
check("/me tells the app whether the account has a password or Google", call("/me", headers=bearer)[1]["user"]["hasPassword"] is True)
check("changing the password over HTTP needs the current one", call("/me/password", {"new": "yet another passphrase", "current": "wrong"}, bearer)[0] == 400
      and call("/me/password", {"new": "yet another passphrase", "current": "another long passphrase"}, bearer)[0] == 200
      and call("/auth/login", {"email": "pw@example.com", "password": "yet another passphrase"})[0] == 200)
check("changing the password needs a sign-in", call("/me/password", {"new": "whatever long passphrase"})[0] == 401)
check("renaming over HTTP works", call("/me/username", {"username": "Renamed_Two"}, bearer)[1]["username"] == "Renamed_Two" and call("/me", headers=bearer)[1]["user"]["username"] == "Renamed_Two")
check("signing up with a password over HTTP", (lambda: (call("/auth/start", {"email": "httpnew@example.com"}), call("/auth/verify", {"email": "httpnew@example.com", "code": SENT[-1][1], "username": "httpnew", "password": "short"})[0] == 400,
      call("/auth/verify", {"email": "httpnew@example.com", "code": SENT[-1][1], "username": "httpnew", "password": "a decent passphrase here"})[1]["user"]["hasPassword"])[1:])()[1])

# Google round trip, web
st, _, hd = call("/auth/google/start?mode=web")
loc = hd.get("Location", "")
cookie = hd.get("Set-Cookie", "").split(";")[0]
state = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)["state"][0]
check("starting Google redirects to Google and sets a browser-binding cookie", st == 302 and loc.startswith("https://accounts.google.com/") and cookie.startswith("plunge_oauth=") and "HttpOnly" in hd.get("Set-Cookie", ""))
st, _, hd = call("/auth/google/callback?code=good-code&state=" + urllib.parse.quote(state), headers={"Cookie": cookie})
check("the web callback signs in, sets the session cookie and returns to the website", st == 302 and hd.get("Location", "").endswith("/account") and "plunge_session=" in "".join(hd.get_all("Set-Cookie")))
st, body, _ = call("/auth/google/callback?code=good-code&state=" + urllib.parse.quote(state))
check("a callback without the matching cookie is refused (login CSRF)", st == 400)
st, body, _ = call("/auth/google/callback?code=good-code&state=" + urllib.parse.quote(state), headers={"Cookie": "plunge_oauth=someoneelsescookie123"})
check("a callback with someone else's cookie is refused", st == 400)
st, _, _ = call("/auth/google/callback?code=good-code&state=forged.state", headers={"Cookie": cookie})
check("a forged state is refused", st == 400)
st, body, _ = call("/auth/google/callback?code=bad-code&state=" + urllib.parse.quote(state), headers={"Cookie": cookie})
check("a code Google rejects is refused", st == 400)
st, body, _ = call("/auth/google/callback?error=access_denied&state=x")
check("cancelling at Google shows a friendly page", st == 400 and b"cancelled" in body)

# Google round trip, app (needs the secret that only the app knows)
verifier = secrets.token_urlsafe(32)
challenge = hashlib.sha256(verifier.encode()).hexdigest()
st, _, hd = call("/auth/google/start?mode=app&challenge=" + challenge)
cookie = hd.get("Set-Cookie", "").split(";")[0]
state = urllib.parse.parse_qs(urllib.parse.urlparse(hd["Location"]).query)["state"][0]
check("the app can't poll before the person has signed in", call("/auth/google/poll", {"verifier": verifier})[1] == {"pending": True})
st, body, _ = call("/auth/google/callback?code=good-code&state=" + urllib.parse.quote(state), headers={"Cookie": cookie})
check("the app flow shows a 'go back to the app' page and sets no cookie", st == 200 and b"signed in" in body.lower())
check("someone who didn't start it can't collect the sign-in", call("/auth/google/poll", {"verifier": secrets.token_urlsafe(32)})[1] == {"pending": True})
st, got, _ = call("/auth/google/poll", {"verifier": verifier})
check("the app collects the sign-in with its secret", st == 200 and got["token"] and got["user"]["hasGoogle"] is True and call("/me", headers={"Authorization": "Bearer " + got["token"]})[0] == 200)
check("and only once", call("/auth/google/poll", {"verifier": verifier})[1] == {"pending": True})
check("a badly formed secret is refused", call("/auth/google/poll", {"verifier": "short"})[0] == 400)
os.environ.pop("GOOGLE_CLIENT_ID")
check("with Google switched off the start link explains why", call("/auth/google/start?mode=web")[0] == 400 and call("/auth/config")[1]["google"] is False)

# rate limiting of password guessing per address
hub_server.LIMITER.hits.clear()
codes = [call("/auth/login", {"email": "g%d@example.com" % i, "password": "wrong password here"})[0] for i in range(33)]
check("password sign-in is rate limited per address", codes[:30] == [400] * 30 and 429 in codes[30:])

srv.shutdown()
srv.server_close()
accounts.STATE["db"].close()
sys.exit(1 if fails else 0)
