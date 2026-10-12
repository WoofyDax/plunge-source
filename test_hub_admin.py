"""Hub takedown: only the operator (admin key) can remove a profile, and removing deletes the file too."""
import io
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import hub_server

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


def profile_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("plunge.json", json.dumps({"schema": 2, "title": "Remove me test", "tagline": "t", "steamAppId": 111, "engine": "unity", "tier": "native", "author": "me",
                                              "license": "MIT", "comfort": "gentle", "controls": "motion", "version": "1.0.0",
                                              "tested": {"gameVersion": "1", "minutesPlayed": 9, "headset": "q"},
                                              "recipe": {"runtime": None, "install": [{"from": "files/a.cfg", "to": "{game}/a.cfg"}]}}))
        z.writestr("files/a.cfg", "x=1\n")
    return buf.getvalue()


tmp = tempfile.mkdtemp()
hub_server.STATE.update({"dir": Path(tmp), "admin": "k" * 40, "require_auth": False})
srv = ThreadingHTTPServer(("127.0.0.1", 0), hub_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_address[1]


def call(path, data=None, headers=None, method=None):
    req = urllib.request.Request(base + path, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


st, up = call("/profiles", profile_zip(), {"Content-Type": "application/zip"})
check("a valid profile uploads", st == 200 and "id" in up)
pid = up.get("id", "x")
zp = Path(tmp) / "zips" / (pid + ".zip")
check("the uploaded file is stored on disk", zp.is_file())
check("it shows up in the list", any(p["id"] == pid for p in call("/profiles")[1]["profiles"]))
check("removing without the admin key is refused", call("/profiles/%s/remove" % pid, b"{}")[0] == 403)
check("removing with a wrong key is refused", call("/profiles/%s/remove" % pid, b"{}", {"X-Admin": "wrong"})[0] == 403)
check("it is still there after the refused attempts", zp.is_file() and any(p["id"] == pid for p in call("/profiles")[1]["profiles"]))
st, r = call("/profiles/%s/remove" % pid, b"{}", {"X-Admin": "k" * 40})
check("removing with the admin key works", st == 200 and r.get("removed") == pid)
check("the file is deleted", not zp.exists())
check("it is gone from the list and the download", not any(p["id"] == pid for p in call("/profiles")[1]["profiles"]) and call("/profiles/%s/download" % pid)[0] == 404)
check("removing something that does not exist is a 404", call("/profiles/nope-123456/remove", b"{}", {"X-Admin": "k" * 40})[0] == 404)
hub_server.STATE["admin"] = ""
check("with no admin key configured, nobody can remove anything", call("/profiles/%s/remove" % pid, b"{}", {"X-Admin": ""})[0] in (403, 404))
srv.shutdown()
srv.server_close()
sys.exit(1 if fails else 0)
