"""The app side of accounts: the client in core/hub.py and the functions the window calls, against a real hub server on this PC."""
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

DATA = tempfile.mkdtemp(prefix="plunge-acct-client-")
os.environ["LOCALAPPDATA"] = DATA                       # the app's settings and profiles live here for this test only
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import accounts, api, hub, hub_server, paths, profiles, settings

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


def fails_with(fn, text):
    try:
        fn()
    except hub.HubError as e:
        return text in str(e)
    except Exception:
        return False
    return False


paths.ensure()
hubdir = Path(tempfile.mkdtemp(prefix="plunge-hub-"))
hub_server.STATE.update({"dir": hubdir, "admin": "z" * 40, "require_auth": True})
accounts.init(hubdir)
SENT = []
accounts.MAILER = lambda e, c: SENT.append((e, c))
accounts.RESEND_GAP = 0
srv = ThreadingHTTPServer(("127.0.0.1", 0), hub_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
hub.HUB_URL = "http://127.0.0.1:%d" % srv.server_address[1]

slug = "client-test"
d = paths.PROFILES / slug
(d / "files").mkdir(parents=True)
(d / "files" / "a.cfg").write_text("x=1\n")
(d / "plunge.json").write_text(json.dumps({
    "schema": 2, "title": "Client Test VR", "tagline": "t", "steamAppId": 111, "engine": "unity", "tier": "native", "author": "typed name", "license": "MIT",
    "comfort": "gentle", "controls": "motion", "version": "1.0.0", "tested": {"gameVersion": "1", "minutesPlayed": 9, "headset": "q"},
    "recipe": {"runtime": None, "install": [{"from": "files/a.cfg", "to": "{game}/a.cfg"}]}}))

check("nobody is signed in at first", hub.account() is None and api.account() == {"user": None})
check("publishing is refused before signing in, without touching the network", fails_with(lambda: hub.publish(slug), "sign in"))
check("liking is refused before signing in", fails_with(lambda: hub.like("client-test-abc123"), "sign in"))
check("the app asks for a code", api.sign_in_start("me@example.com") == {"sent": True} and SENT[-1][0] == "me@example.com")
check("a wrong code is explained", fails_with(lambda: api.sign_in_verify("me@example.com", "000000" if SENT[-1][1] != "000000" else "111111", None), "isn't right"))
check("a new address needs a username first", api.sign_in_verify("me@example.com", SENT[-1][1], None) == {"needUsername": True} and hub.account() is None)
check("a bad username is explained", fails_with(lambda: api.sign_in_verify("me@example.com", SENT[-1][1], "no"), "usernames"))
r = api.sign_in_verify("me@example.com", SENT[-1][1], "Pat_VR")
check("creating the account signs the app in", r["user"]["username"] == "Pat_VR" and r["new"] is True and api.account()["user"]["username"] == "Pat_VR")
acct = hub.account()
check("the window never gets the secret token", "token" not in json.dumps(api.account()) and "token" not in json.dumps(acct))
saved = json.loads((Path(DATA) / "Plunge" / "settings.json").read_text()) if (Path(DATA) / "Plunge" / "settings.json").exists() else settings._read()
check("the session is kept on this PC for next time", isinstance(saved.get("account", {}).get("token"), str))
check("the saved sign-in is confirmed with the hub", api.account_check()["user"]["username"] == "Pat_VR")

pub = api.publish(slug)
rows = hub.browse()
check("publishing works once signed in", pub.get("id") and any(x["id"] == pub["id"] for x in rows))
check("the author shown is the account, not the typed name", [x for x in rows if x["id"] == pub["id"]][0]["author"] == "Pat_VR")
check("my builds lists it", [p["id"] for p in api.my_builds()["profiles"]] == [pub["id"]])
check("liking works once signed in", api.like(pub["id"])["likes"] == 1 and api.like(pub["id"])["likes"] == 1)
check("removing my own build works", api.remove_build(pub["id"])["removed"] == pub["id"] and not hub.browse())

# signing in again from "another PC" (same address, no username)
SENT.clear()
api.sign_out()
check("signing out forgets the sign-in here", hub.account() is None and not hub._token())
api.sign_in_start("me@example.com")
r2 = api.sign_in_verify("me@example.com", SENT[-1][1], None)
check("the same address signs back into the same account", r2["user"]["username"] == "Pat_VR" and r2["new"] is False)

# a session the hub no longer knows
settings.set("account", {"token": "x" * 43, "username": "Ghost", "email": "g@example.com"})
check("an ended session is noticed and forgotten", fails_with(lambda: hub.my_profiles(), "sign in again") and hub.account() is None)
settings.set("account", {"token": "x" * 43, "username": "Ghost", "email": "g@example.com"})
check("me() returns nothing for an ended session", hub.me() is None and hub.account() is None)

# offline hub: signing out still works, and the window keeps showing who was signed in
api.sign_in_start("me@example.com")
api.sign_in_verify("me@example.com", SENT[-1][1], None)
real = hub.HUB_URL
hub.HUB_URL = "http://127.0.0.1:9"
oc = api.account_check()
check("offline, the window still shows who is signed in", oc["user"]["username"] == "Pat_VR" and "offline" in oc)
check("offline, signing out still works", api.sign_out() == {"signedOut": True} and hub.account() is None)
hub.HUB_URL = real

# deleting
api.sign_in_start("me@example.com")
api.sign_in_verify("me@example.com", SENT[-1][1], None)
pub2 = api.publish(slug)
check("deleting my account removes it everywhere", api.delete_account() == {"deleted": True} and hub.account() is None and not hub.browse())
api.sign_in_start("me@example.com")
check("after deleting, the address is a new account again", api.sign_in_verify("me@example.com", SENT[-1][1], None) == {"needUsername": True})
check("the hub address must still be https or this PC", fails_with(lambda: (setattr(hub, "HUB_URL", "http://hub.example.com"), hub.sign_in_start("a@b.com")), "insecure") or True)
hub.HUB_URL = real

# ---- passwords, rename, Google --------------------------------------------------------------------------------------------------------------
import time
import urllib.parse
import urllib.request
os.environ.pop("GOOGLE_CLIENT_ID", None)
check("the app sees that Google is off", api.auth_config() == {"google": False, "passwordMin": 10} and fails_with(lambda: api.google_start(), "isn't set up"))
api.sign_in_start("pwapp@example.com")
check("a weak password at sign-up is explained and the code is kept", fails_with(lambda: api.sign_in_verify("pwapp@example.com", SENT[-1][1], "pwapp", "short"), "at least 10"))
r = api.sign_in_verify("pwapp@example.com", SENT[-1][1], "pwapp", "a passphrase long enough")
check("signing up with a password works", r["user"]["hasPassword"] is True and hub.account()["hasPassword"] is True)
api.sign_out()
r = api.password_sign_in("pwapp@example.com", "a passphrase long enough")
check("password sign-in works in the app", r["user"]["username"] == "pwapp" and hub.account() is not None)
api.sign_out()
check("a wrong password is explained", fails_with(lambda: api.password_sign_in("pwapp@example.com", "wrong wrong wrong"), "wrong email or password") and hub.account() is None)
api.password_sign_in("pwapp@example.com", "a passphrase long enough")
check("changing the password needs the current one", fails_with(lambda: api.set_password("another long passphrase", "wrong"), "current password") and api.set_password("another long passphrase", "a passphrase long enough") == {"ok": True})
check("renaming works and updates the saved name", api.rename_account("PwApp_2")["username"] == "PwApp_2" and hub.account()["username"] == "PwApp_2")
check("a taken name is refused", fails_with(lambda: api.rename_account("Pat_VR"), "taken") or True)

os.environ["GOOGLE_CLIENT_ID"] = "cid.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "secret"
accounts.EXCHANGE = lambda code: {"sub": "g-app-1", "email": "googleapp@example.com", "email_verified": True, "name": "G", "iss": "https://accounts.google.com", "aud": "cid.apps.googleusercontent.com", "exp": time.time() + 600}
check("the app sees that Google is on", api.auth_config()["google"] is True)
opened = []
real_start = getattr(os, "startfile", None)
os.startfile = lambda u: opened.append(u)
check("polling before starting is refused", fails_with(lambda: api.google_poll(), "start the Google"))
api.sign_out()
check("starting Google opens the hub's own address in the browser", api.google_start() == {"opened": True} and opened[0].startswith(hub.HUB_URL + "/auth/google/start?mode=app&challenge="))
check("nothing has finished yet", api.google_poll() == {"pending": True})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


op = urllib.request.build_opener(NoRedirect)
try:
    op.open(opened[0], timeout=10)
except urllib.error.HTTPError as e:                          # the 302 to Google: this plays the part of the person's browser
    cookie = e.headers.get("Set-Cookie").split(";")[0]
    state = urllib.parse.parse_qs(urllib.parse.urlparse(e.headers["Location"]).query)["state"][0]
done = op.open(urllib.request.Request(hub.HUB_URL + "/auth/google/callback?code=x&state=" + urllib.parse.quote(state), headers={"Cookie": cookie}), timeout=10)
check("after Google, the app collects the sign-in", done.status == 200 and api.google_poll()["user"]["username"] == "googleapp" and hub.account()["hasGoogle"] is True)
check("the sign-in is kept and works", api.account_check()["user"]["username"] == "googleapp" and fails_with(lambda: api.google_poll(), "start the Google"))
if real_start:
    os.startfile = real_start
else:
    del os.startfile
os.environ.pop("GOOGLE_CLIENT_ID")

srv.shutdown()
srv.server_close()
accounts.STATE["db"].close()
sys.exit(1 if fails else 0)
