"""Accounts: email-code sign-in, sessions, and what signing in changes about publishing, liking and removing. No real email is sent."""
import io
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
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


tmp = Path(tempfile.mkdtemp())
hub_server.STATE.update({"dir": tmp, "admin": "k" * 40, "require_auth": True})
accounts.init(tmp)
SENT = []
accounts.MAILER = lambda email, code: SENT.append((email, code))
accounts.RESEND_GAP = 0
db = accounts.STATE["db"]


def disk():
    out = b""
    for f in ("accounts.db", "accounts.db-wal"):
        if (tmp / f).exists():
            with open(tmp / f, "rb") as fh:
                out += fh.read()
    return out


def signup(email, name, code_override=None):
    accounts.start_login(email)
    code = SENT[-1][1]
    return accounts.verify_login(email, code_override or code, name)


# ---- the rules ------------------------------------------------------------------------------------------------------------------------
check("an email address is normalised", accounts.normalize_email("  Ann@Example.COM ") == "ann@example.com")
check("nonsense emails are refused", all(raises(lambda e=e: accounts.normalize_email(e), "email") for e in ("", "a", "a@b", "a b@c.com", "a@@b.com", "x" * 300 + "@a.com", None)))
check("usernames follow the rules", accounts.clean_username("Zed_1-2") == "Zed_1-2" and all(raises(lambda n=n: accounts.clean_username(n)) for n in ("ab", "_ab", "a b", "a" * 25, "emoji😀name", "admin", "Plunge", "SUPPORT")))

accounts.start_login("ann@example.com")
check("a 6-digit code is emailed", len(SENT) == 1 and SENT[0][0] == "ann@example.com" and len(SENT[0][1]) == 6 and SENT[0][1].isdigit())
code = SENT[0][1]
raw = disk()
check("the code is stored only as a keyed hash", code.encode() not in raw)
check("a wrong code is refused", raises(lambda: accounts.verify_login("ann@example.com", "000000" if code != "000000" else "111111", "ann"), "isn't right"))
check("a new address is asked for a username first", accounts.verify_login("ann@example.com", code) == {"needUsername": True})
check("the code still works after that", accounts.verify_login("ann@example.com", code, "ann")["new"] is True)
check("the code can't be used twice", raises(lambda: accounts.verify_login("ann@example.com", code, "ann2"), "expired"))
sess = accounts.start_login("ann@example.com") or SENT[-1][1]
r = accounts.verify_login("ann@example.com", SENT[-1][1])
check("signing in again needs no username and gives the same account", r["new"] is False and r["user"]["username"] == "ann")
tok = r["token"]
raw = disk()
check("session tokens are stored only as keyed hashes", tok.encode() not in raw)
check("a session token identifies the account", accounts.session_user(tok)["username"] == "ann")
check("garbage tokens identify nobody", accounts.session_user("x") is None and accounts.session_user("a" * 500) is None and accounts.session_user(None) is None)
accounts.logout(tok)
check("signing out ends the session", accounts.session_user(tok) is None)

bob = signup("bob@example.com", "Bob")
check("usernames are unique, ignoring case", raises(lambda: signup("cat@example.com", "bOb"), "taken"))
accounts.start_login("lock@example.com"); good = SENT[-1][1]
for _ in range(5):
    raises(lambda: accounts.verify_login("lock@example.com", "999999" if good != "999999" else "888888", "lock"))
check("five wrong guesses lock the code, even the right one", raises(lambda: accounts.verify_login("lock@example.com", good, "lock")))
accounts.start_login("late@example.com"); late = SENT[-1][1]
db.execute("UPDATE logins SET expires=? WHERE email=?", (time.time() - 1, "late@example.com"))
check("an expired code is refused", raises(lambda: accounts.verify_login("late@example.com", late, "late"), "expired"))
check("verifying an address that never asked for a code fails the same way", raises(lambda: accounts.verify_login("nobody@example.com", "123456", "x"), "expired"))

accounts.RESEND_GAP = 45
accounts.start_login("gap@example.com")
check("asking again straight away is refused", raises(lambda: accounts.start_login("gap@example.com"), "just sent"))
accounts.RESEND_GAP = 0
old_cap, accounts.DAILY_EMAIL_CAP = accounts.DAILY_EMAIL_CAP, 0
check("a daily cap on emails stops the hub being used to spam", raises(lambda: accounts.start_login("cap@example.com"), "paused"))
accounts.DAILY_EMAIL_CAP = old_cap


def boom(email, code):
    raise RuntimeError("no mail")


good_mailer, accounts.MAILER = accounts.MAILER, boom
try:
    accounts.start_login("fail@example.com")
    sent_ok = True
except RuntimeError:
    sent_ok = False
check("a failing mailer is reported", sent_ok is False and db.execute("SELECT COUNT(*) FROM logins WHERE email='fail@example.com'").fetchone()[0] == 0)
accounts.MAILER = good_mailer

many = [signup("many@example.com" if i == 0 else "many@example.com", "Many") if i == 0 else None for i in range(1)]
uid = db.execute("SELECT id FROM users WHERE email='many@example.com'").fetchone()[0]
toks = [accounts._new_session(uid) for _ in range(14)]
check("an account keeps at most 10 sessions", db.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (uid,)).fetchone()[0] == 10 and accounts.session_user(toks[-1]) is not None)

# ---- over HTTP --------------------------------------------------------------------------------------------------------------------------
srv = ThreadingHTTPServer(("127.0.0.1", 0), hub_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_address[1]
SITE = "https://plungevr.com"


class Resp:
    def __init__(self, code, body, headers):
        self.code, self.body, self.headers = code, body, headers


def call(path, body=None, headers=None, method=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = dict(headers or {})
    if raw is None and body is not None:
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(base + path, data=data if (data is not None or method == "POST") else None, headers=h, method=method or ("POST" if data is not None else "GET"))
    if method == "POST" and data is None:
        req.data = b"{}"
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            b = r.read()
            return Resp(r.status, json.loads(b) if b and r.headers.get_content_type() == "application/json" else b, r.headers)
    except urllib.error.HTTPError as e:
        b = e.read()
        return Resp(e.code, json.loads(b) if b else None, e.headers)


def sign_in_http(email, username=None, extra=None):
    call("/auth/start", {"email": email}, extra)
    code = SENT[-1][1]
    return call("/auth/verify", {"email": email, "code": code, "username": username}, extra)


def zipped(author="someone else"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("plunge.json", json.dumps({"schema": 2, "title": "Acct VR", "tagline": "t", "steamAppId": 111, "engine": "unity", "tier": "native", "author": author,
                                              "license": "MIT", "comfort": "gentle", "controls": "motion", "version": "1.0.0",
                                              "tested": {"gameVersion": "1", "minutesPlayed": 9, "headset": "q"},
                                              "recipe": {"runtime": None, "install": [{"from": "files/a.cfg", "to": "{game}/a.cfg"}]}}))
        z.writestr("files/a.cfg", "x=1\n")
    return buf.getvalue()


accounts.RESEND_GAP = 0
check("starting a sign-in gives the same answer for any address", call("/auth/start", {"email": "known@example.com"}).body == {"ok": True} and call("/auth/start", {"email": "ann@example.com"}).body == {"ok": True})
check("a bad email gets a clear error", call("/auth/start", {"email": "nope"}).code == 400)
check("a body that isn't JSON is refused", call("/auth/start", raw=b"not json", headers={"Content-Type": "application/json"}, method="POST").code == 400)
check("an oversized body is refused", call("/auth/start", raw=b"{" + b" " * 5000 + b"}", method="POST").code == 400)
s1 = sign_in_http("carol@example.com", "carol")
tokC = s1.body.get("token")
check("the app gets a token and no cookie", s1.code == 200 and tokC and not s1.headers.get("Set-Cookie") and s1.body["user"]["username"] == "carol")
check("a new address first gets needUsername over HTTP", (lambda: (call("/auth/start", {"email": "dave@example.com"}), call("/auth/verify", {"email": "dave@example.com", "code": SENT[-1][1]}).body == {"needUsername": True})[1])())
bearer = {"Authorization": "Bearer " + tokC}
check("GET /me with the token returns the account", call("/me", headers=bearer).body["user"]["username"] == "carol")
check("GET /me without a token is 401", call("/me").code == 401 and call("/me", headers={"Authorization": "Bearer nope"}).code == 401)

# publishing
check("publishing without signing in is refused", call("/profiles", raw=zipped(), headers={"Content-Type": "application/zip"}, method="POST").code == 401)
up = call("/profiles", raw=zipped("Totally Someone Else"), headers={**bearer, "Content-Type": "application/zip"}, method="POST")
pid = up.body.get("id")
check("publishing while signed in works", up.code == 200 and pid)
row = [p for p in call("/profiles").body["profiles"] if p["id"] == pid][0]
check("the author is the account, not what the uploader typed", row["author"] == "carol")
dl = call("/profiles/%s/download" % pid).body
stored = json.loads(zipfile.ZipFile(io.BytesIO(dl)).read("plunge.json"))
check("the downloaded zip carries the same author", stored["author"] == "carol")
check("my profiles lists it", [p["id"] for p in call("/me/profiles", headers=bearer).body["profiles"]] == [pid])

# liking
check("liking without signing in is refused", call("/profiles/%s/like" % pid, method="POST").code == 401)
l1 = call("/profiles/%s/like" % pid, method="POST", headers=bearer)
l2 = call("/profiles/%s/like" % pid, method="POST", headers=bearer)
check("a signed-in like counts once per account", l1.body["likes"] == 1 and l2.body["likes"] == 1 and l2.body.get("already") is True)

# removing
tokB = bob["token"]
check("another account can't remove my profile", call("/profiles/%s/remove" % pid, method="POST", headers={"Authorization": "Bearer " + tokB}).code == 403)
check("a stranger with no sign-in can't either", call("/profiles/%s/remove" % pid, method="POST").code == 403)

# browser (cookie) sign-in
web = {"Origin": SITE, "X-Plunge-Client": "web"}
call("/auth/start", {"email": "erin@example.com"}, web)
w = call("/auth/verify", {"email": "erin@example.com", "code": SENT[-1][1], "username": "erin"}, web)
ck = w.headers.get("Set-Cookie", "")
check("a browser gets an HttpOnly, Secure, SameSite cookie", "plunge_session=" in ck and "HttpOnly" in ck and "Secure" in ck and "SameSite=Lax" in ck)
check("a browser never sees the token in the page", "token" not in w.body)
cookie = {"Cookie": ck.split(";")[0]}
check("the cookie signs in a read from the website", call("/me", headers={**cookie, **web}).body["user"]["username"] == "erin")
check("the right origin is allowed to read the answer", call("/me", headers={**cookie, **web}).headers.get("Access-Control-Allow-Origin") == SITE and call("/me", headers={**cookie, **web}).headers.get("Access-Control-Allow-Credentials") == "true")
evil = {"Origin": "https://evil.example", "X-Plunge-Client": "web"}
check("another website gets no permission to read answers", call("/me", headers={**cookie, **evil}).headers.get("Access-Control-Allow-Origin") is None)
check("CSRF: a cookie alone can't publish", call("/profiles", raw=zipped(), headers={**cookie, "Content-Type": "application/zip"}, method="POST").code == 401)
check("CSRF: a cookie from another website can't publish", call("/profiles", raw=zipped(), headers={**cookie, **evil, "Content-Type": "application/zip"}, method="POST").code == 401)
check("CSRF: a cookie with the origin but not our header can't publish", call("/profiles", raw=zipped(), headers={**cookie, "Origin": SITE, "Content-Type": "application/zip"}, method="POST").code == 401)
check("the website itself can publish with its cookie", call("/profiles", raw=zipped(), headers={**cookie, **web, "Content-Type": "application/zip"}, method="POST").code == 200)
pre = call("/auth/start", method="OPTIONS", headers={"Origin": SITE, "Access-Control-Request-Method": "POST"})
check("the website's pre-flight is answered", pre.code == 204 and pre.headers.get("Access-Control-Allow-Origin") == SITE and "X-Plunge-Client" in pre.headers.get("Access-Control-Allow-Headers", ""))
check("another website's pre-flight is refused", call("/auth/start", method="OPTIONS", headers={"Origin": "https://evil.example"}).code == 403)

# removing, deleting
hub_server.LIMITER.hits.clear()          # (failed attempts also count against the upload limit, which is the point)
check("the author can remove their own profile", call("/profiles/%s/remove" % pid, method="POST", headers=bearer).code == 200 and not any(p["id"] == pid for p in call("/profiles").body["profiles"]))
mine = call("/profiles", raw=zipped(), headers={**bearer, "Content-Type": "application/zip"}, method="POST").body["id"]
check("the operator's admin key still removes anything", call("/profiles/%s/remove" % mine, method="POST", headers={"X-Admin": "k" * 40}).code == 200)
mine2 = call("/profiles", raw=zipped(), headers={**bearer, "Content-Type": "application/zip"}, method="POST").body["id"]
check("deleting an account needs the exact confirmation", call("/me/delete", {"confirm": "yes"}, bearer).code == 400 and call("/me/delete", {"confirm": "delete my account"}).code == 401)
check("deleting my account works", call("/me/delete", {"confirm": "delete my account"}, bearer).code == 200)
check("the account's profiles are deleted with it", not any(p["id"] == mine2 for p in call("/profiles").body["profiles"]) and not (tmp / "zips" / (mine2 + ".zip")).exists())
check("the old session no longer works", call("/me", headers=bearer).code == 401)
check("the username is free again", accounts.clean_username("carol") == "carol" and db.execute("SELECT COUNT(*) FROM users WHERE username='carol'").fetchone()[0] == 0)
lo = call("/auth/logout", {}, {"Authorization": "Bearer " + tokB})
check("signing out over HTTP ends the session", lo.code == 200 and call("/me", headers={"Authorization": "Bearer " + tokB}).code == 401)

# rate limits
hub_server.LIMITER.hits.clear()
codes = [call("/auth/start", {"email": "flood%d@example.com" % i}).code for i in range(8)]
check("signing-in requests are rate limited per address", codes[:6] == [200] * 6 and 429 in codes[6:])
check("with require_auth off, anonymous publishing still works (for private hubs)", (lambda: (hub_server.STATE.update(require_auth=False), hub_server.LIMITER.hits.clear(),
      call("/profiles", raw=zipped(), headers={"Content-Type": "application/zip"}, method="POST").code == 200)[2])())

srv.shutdown()
srv.server_close()
accounts.STATE["db"].close()
sys.exit(1 if fails else 0)
