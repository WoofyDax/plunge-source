"""DEV: replay Plunge's Play flow for a REAL profile against a fake game folder and a temp data dir.
Touches nothing real: no game is started, no real settings or game files change.
usage: python tools/sandbox_play.py <path-to-profile-folder> <appid>"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

src, appid = Path(sys.argv[1]), sys.argv[2]
tmp = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(tmp / "local")
os.environ["APPDATA"] = str(tmp / "roam")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import api, paths, profiles, recipe, trust  # noqa: E402

paths.ensure()
shutil.copytree(src, paths.PROFILES / src.name)
game_dir = tmp / "FakeGame"
(game_dir / "GameData").mkdir(parents=True)
(game_dir / "doorstop_config.ini").write_text("original-ini")            # a file the profile will replace
GAME = {"appid": appid, "name": "FakeGame", "path": str(game_dir), "exe": None, "engine": "unity", "anticheat": [], "buildId": "1",
        "status": "experimental", "why": "", "route": {"id": "agent-unity", "label": "x", "maturity": "m", "note": "n"}}
api._STATE.update(games=[GAME], demo=False)
launched = []
recipe.launch = lambda *a, **k: launched.append(a) or {"mode": "stub"}

slug = src.name
meta = profiles.load(slug)
t0 = time.time()
v = api.validate_profile(slug, appid)
print("validate:", v["ok"], "(%.1fs)" % (time.time() - t0), v["findings"][:3])
info = api.game_info(appid)
p = next(x for x in info["profiles"] if x["slug"] == slug)
print("binaries declared:", len(p["binaries"]), "| trusted:", p["trusted"], "| stale:", p["stale"])
authors = {}
for b in p["binaries"]:
    authors.setdefault((b["author"], b["license"]), 0)
    authors[(b["author"], b["license"])] += 1
print("distinct (author, licence) groups:", len(authors))
try:
    api.play(appid, slug, "solo", None, None)
    print("play without trust: NOT REFUSED (unexpected)")
except ValueError as e:
    print("play without trust ->", str(e)[:80])
api.trust_profile(slug)
t0 = time.time()
r = api.play(appid, slug, "solo", None, None)
print("play after trust:", r["steps"], "(%.1fs)" % (time.time() - t0), "| launched:", len(launched))
files = [f for f in game_dir.rglob("*") if f.is_file()]
print("files now in the fake game:", len(files), "| installed:", recipe.is_installed(appid))
print("prefs file written:", (game_dir / "BepInEx" / "plunge-prefs.json").exists())
u = api.uninstall(appid)
left = sorted(f.relative_to(game_dir).as_posix() for f in game_dir.rglob("*") if f.is_file())
print("uninstall:", u, "| files left:", left)
print("original restored:", (game_dir / "doorstop_config.ini").read_text() == "original-ini")
shutil.rmtree(tmp, ignore_errors=True)
