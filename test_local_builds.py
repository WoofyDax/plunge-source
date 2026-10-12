"""The 'Publish a build' window's data: finished builds, builds with problems, and unfinished folders."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="plunge-lb-")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import api, paths

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


paths.ensure()
check("with nothing made yet the lists are empty", api.local_builds() == {"profiles": [], "incomplete": []})
good = paths.PROFILES / "good-vr"
(good / "files").mkdir(parents=True)
(good / "files" / "a.cfg").write_text("x=1\n")
(good / "plunge.json").write_text(json.dumps({"schema": 2, "title": "Good VR", "tagline": "t", "steamAppId": 111, "engine": "unity", "tier": "native", "author": "me", "license": "MIT",
                                              "comfort": "gentle", "controls": "motion", "version": "1.0.0", "tested": {"gameVersion": "1", "minutesPlayed": 9, "headset": "q"},
                                              "recipe": {"runtime": None, "install": [{"from": "files/a.cfg", "to": "{game}/a.cfg"}]}}))
bad = paths.PROFILES / "bad-vr"
bad.mkdir()
(bad / "plunge.json").write_text(json.dumps({"schema": 2, "title": "Bad VR"}))
empty = paths.PROFILES / "empty-vr"
empty.mkdir()
broken = paths.PROFILES / "broken-vr"
broken.mkdir()
(broken / "plunge.json").write_text("{ not json")
(paths.PROFILES / "stray-file.txt").write_text("x")
r = api.local_builds()
by = {p["slug"]: p for p in r["profiles"]}
check("a finished build is ready to publish", by["good-vr"]["ready"] is True and by["good-vr"]["errors"] == [] and by["good-vr"]["title"] == "Good VR")
check("a build with problems says what is wrong and can't be published", by["bad-vr"]["ready"] is False and len(by["bad-vr"]["errors"]) >= 1)
check("folders with no build file are reported as unfinished", "empty-vr" in r["incomplete"])
check("a damaged build file is reported as unfinished, not a crash", "broken-vr" in r["incomplete"])
check("stray files are ignored", all("stray" not in p["slug"] for p in r["profiles"]) and "stray-file.txt" not in r["incomplete"])
check("sizes are reported in MB", isinstance(by["good-vr"]["mb"], float))
sys.exit(1 if fails else 0)
