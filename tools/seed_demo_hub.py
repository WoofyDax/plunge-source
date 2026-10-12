"""DEV ONLY: publish clearly-labelled [DEMO] profiles to a LOCAL hub so Discover can be previewed.
These are not real builds and make no testing claims a player should trust. Never point this at a real hub."""
import io
import json
import sys
import urllib.request
import zipfile

HUB = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8788"
ADMIN = sys.argv[2] if len(sys.argv) > 2 else "devadmin"

DEMOS = [
    ("[DEMO] ACC Cockpit Plus", 805550, "unreal", "native", "Demo entry: shows how a featured build looks", 1, "gentle"),
    ("[DEMO] BeamNG Chase Cam", 284160, "other", "injected", "Demo entry: third-person chase camera in VR", 0, "moderate"),
    ("[DEMO] Assetto Corsa Theater", 244210, "other", "theater", "Demo entry: the flat game on a huge screen", 0, "gentle"),
    ("[DEMO] Hollow Knight Table", 367520, "unity", "theater", "Demo entry: a tabletop diorama view", 0, "gentle"),
    ("[DEMO] Stray Cat Cam", 1332010, "unreal", "native", "Demo entry: you are the cat", 0, "moderate"),
]


def make_zip(title, appid, engine, tier, tagline, comfort):
    meta = {"schema": 2, "title": title, "tagline": tagline, "steamAppId": appid, "engine": engine, "tier": tier,
            "author": "demo-seed", "license": "CC0", "comfort": comfort, "controls": "both", "version": "0.1.0",
            "tested": {"gameVersion": "demo", "minutesPlayed": 1, "headset": "none (demo data)"},
            "recipe": {"runtime": None, "install": [{"from": "files/readme.txt", "to": "{game}/plunge-demo.txt"}], "launch": {"mode": "steam"}}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("plunge.json", json.dumps(meta))
        z.writestr("files/readme.txt", "demo data, not a real build\n")
    return buf.getvalue()


def call(path, data=None, headers=None):
    req = urllib.request.Request(HUB + path, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


ids = []
for d in DEMOS:
    ids.append(call("/profiles", make_zip(*[d[0], d[1], d[2], d[3], d[4], d[6]]), {"Content-Type": "application/zip"})["id"])
call("/profiles/%s/feature" % ids[0], b"{}", {"X-Admin": ADMIN})
call("/profiles/%s/feature" % ids[4], b"{}", {"X-Admin": ADMIN})
for pid, likes in zip(ids, (7, 12, 3, 9, 2)):
    for _ in range(likes):
        call("/profiles/%s/like" % pid, b"{}")
print("seeded", ids)
