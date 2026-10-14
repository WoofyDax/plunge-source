"""Tests: binary trust, game-update warning, plunge:// links, legal documents, first-run flag. Temp dirs only."""
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(tmp / "local")
os.environ["APPDATA"] = str(tmp / "roam")
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from core import api, legal, links, paths, profiles, recipe, settings, trust  # noqa: E402

paths.ensure()
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# ---- fake game + profiles ------------------------------------------------------------------
gdir = tmp / "steam" / "Foo"
gdir.mkdir(parents=True)
GAME = {"appid": "4242", "name": "Foo", "path": str(gdir), "exe": None, "engine": "unity", "anticheat": [], "buildId": "1000",
        "status": "experimental", "why": "", "route": {"id": "agent-unity", "label": "x", "maturity": "m", "note": "n"}}
api._STATE.update(games=[GAME], demo=False)
launched = []
recipe.launch = lambda *a, **k: launched.append(a) or {"mode": "stub", "started": True, "how": "steam"}   # tests never start a game

sha = hashlib.sha256(b"MZ").hexdigest()
BUNDLE = {"path": "files/winhttp.dll", "name": "BepInEx", "author": "BepInEx team", "license": "LGPL-2.1", "url": "https://github.com/BepInEx/BepInEx", "sha256": sha}
BASE = {"schema": 2, "title": "Foo VR", "tagline": "t", "steamAppId": 4242, "engine": "unity", "tier": "native", "author": "me",
        "license": "MIT", "comfort": "gentle", "controls": "motion", "version": "1.0.0",
        "tested": {"gameVersion": "1", "buildId": "1000", "minutesPlayed": 9, "headset": "q"},
        "recipe": {"runtime": None, "install": [{"from": "files/a.cfg", "to": "{game}/a.cfg"}], "launch": {"mode": "steam"}}}


def mk(slug, meta, files):
    d = paths.PROFILES / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "plunge.json").write_text(json.dumps(meta))
    for n, data in files.items():
        (d / n).parent.mkdir(parents=True, exist_ok=True)
        (d / n).write_bytes(data)


mk("plain-vr", BASE, {"files/a.cfg": b"x"})
mk("loader-vr", {**BASE, "title": "Foo Loader", "bundled": [BUNDLE]}, {"files/a.cfg": b"x", "files/winhttp.dll": b"MZ"})

# ---- trust ---------------------------------------------------------------------------------
pm, lm = profiles.load("plain-vr"), profiles.load("loader-vr")
check("profile without binaries needs no trust", trust.is_trusted("plain-vr", pm))
check("profile with binaries is untrusted at first", not trust.is_trusted("loader-vr", lm))
check("binaries are listed with author and licence", trust.binaries(lm)[0]["author"] == "BepInEx team" and trust.binaries(lm)[0]["license"] == "LGPL-2.1")
try:
    api.play("4242", "loader-vr", "solo", None, None)
    check("play refuses an untrusted binary profile", False)
except ValueError as e:
    check("play refuses an untrusted binary profile", str(e).startswith("TRUST_REQUIRED"))
check("nothing was installed or launched while untrusted", not launched and not recipe.is_installed("4242"))
api.trust_profile("loader-vr")
check("trust is remembered", trust.is_trusted("loader-vr", profiles.load("loader-vr")))
r = api.play("4242", "loader-vr", "solo", None, None)
check("trusted profile installs and launches", "Started the game" in r["steps"] and len(launched) == 1 and (gdir / "a.cfg").exists())
api.uninstall("4242")
swapped = {**lm, "bundled": [{**BUNDLE, "sha256": "f" * 64}]}
check("a swapped binary asks for trust again", not trust.is_trusted("loader-vr", swapped))
r = api.play("4242", "plain-vr", "solo", None, None)
check("plain profile plays without any prompt", "Started the game" in r["steps"])
api.uninstall("4242")

# ---- game-update warning -------------------------------------------------------------------
info = api.game_info("4242")
p_plain = next(p for p in info["profiles"] if p["slug"] == "plain-vr")
check("same build -> not stale", p_plain["stale"] is False and p_plain["builtFor"] == "1000")
GAME["buildId"] = "2000"
info = api.game_info("4242")
p_plain = next(p for p in info["profiles"] if p["slug"] == "plain-vr")
check("game updated -> profile flagged stale", p_plain["stale"] is True and p_plain["currentBuild"] == "2000")
check("loader profile shows its binaries in game_info", next(p for p in info["profiles"] if p["slug"] == "loader-vr")["binaries"])
no_build = {**BASE, "title": "Old", "tested": {"gameVersion": "1", "minutesPlayed": 5, "headset": "q"}}
mk("nobuild-vr", no_build, {"files/a.cfg": b"x"})
check("profile without a recorded build is never flagged", next(p for p in api.game_info("4242")["profiles"] if p["slug"] == "nobuild-vr")["stale"] is False)

# ---- plunge:// links -----------------------------------------------------------------------
check("valid join link parsed", links.parse("plunge://join/abc123") == "ABC123" and links.parse("plunge://join/ABC123/") == "ABC123")
for bad in ["plunge://launch/805550", "plunge://join/", "plunge://join/../../x", "plunge://join/abc 123", "http://join/ABC123",
            "plunge://join/ABC123?x=1", "plunge://join/ABCDEFGHIJKLM", "plunge://join/AB", "", None, "plunge://join/%41BC123", "plunge://join/ABC123;calc"]:
    if links.parse(bad) is not None:
        check("rejects bad link: %r" % (bad,), False)
        break
else:
    check("rejects 12 malformed or dangerous links", True)
api.set_startup_link("plunge://join/xyz789")
check("startup link is stored once", api.startup_link()["code"] == "XYZ789" and api.startup_link()["code"] is None)
api.set_startup_link("plunge://evil/thing")
check("startup link of the wrong shape is dropped", api.startup_link()["code"] is None)

before = links.status()
if not before["registered"]:
    try:
        check("register writes the handler", links.register()["registered"] is True)
        check("handler command passes the link as an argument", "%1" in links._command())
    finally:
        links.unregister()
    check("unregister removes it again", links.status()["registered"] is False)
else:
    print("SKIP link registration (already registered on this PC)")

# ---- first run + settings ------------------------------------------------------------------
check("first run not done", api.onboarded(None)["done"] is False)
api.onboarded(True)
check("first run remembered", api.onboarded(None)["done"] is True)
settings.set("ads", False)
check("settings keep other keys", settings.get("onboarded") is True and settings.get("ads") is False)

# ---- legal documents -----------------------------------------------------------------------
LEGAL = HERE / "legal"
for name, (title, fname) in legal.DOCS.items():
    text = (LEGAL / fname).read_text(encoding="utf-8")
    check("legal doc exists and has content: " + fname, len(text) > 800)
check("drafts are marked as drafts", all("DRAFT" in (LEGAL / f).read_text(encoding="utf-8") for _, f in legal.DOCS.values()))
import re as _re_
check("no [PLACEHOLDER] blanks are left in the legal documents", not any(_re_.search(r"\[[A-Z][A-Z /,.\-]+[^\]]*\]", (LEGAL / f).read_text(encoding="utf-8")) for _, f in legal.DOCS.values()))
priv = (LEGAL / "PRIVACY.md").read_text(encoding="utf-8").lower()
for needle, what in [("steam", "Steam store"), ("github", "GitHub"), ("hub", "hub"), ("lobby", "lobby"), ("ip address", "IP address"),
                     ("sponsored", "ads"), ("localappdata", "local data")]:
    check("privacy policy mentions " + what, needle in priv)
check("privacy policy says no analytics", "no analytics" in priv)
terms = (LEGAL / "TERMS.md").read_text(encoding="utf-8").lower()
check("terms cover anti-cheat, official servers and third-party programs", "anti-cheat" in terms and "official servers" in terms and "third-party programs" in terms)
cp = (LEGAL / "COPYRIGHT.md").read_text(encoding="utf-8").lower()
check("copyright policy has notice, counter-notice and repeat infringers", "counter-notice" in cp and "repeat infringers" in cp and "penalty of perjury" in cp)

html = legal.render('# T\n- <script>alert(1)</script>\n**b** [ok](https://example.com) [bad](javascript:alert(1))\n> note')
check("renderer escapes HTML", "<script>" not in html and "&lt;script&gt;" in html)
check("renderer links https only", 'href="https://example.com"' in html and "javascript:" not in html.replace("[bad](javascript:alert(1))", ""))
check("renderer handles headings, lists, bold", "<h1>" in html and "<li>" in html and "<b>b</b>" in html)
opened = []
legal.os.startfile = lambda p: opened.append(p)
legal.open_doc("terms")
check("open_doc writes a page and opens it", opened and Path(opened[0]).exists() and "Terms of Use" in Path(opened[0]).read_text(encoding="utf-8"))
try:
    legal.open_doc("../../Windows/system32/calc")
    check("open_doc rejects unknown names", False)
except ValueError:
    check("open_doc rejects unknown names", True)

print("\n%d failed" % len(fails) if fails else "\nall passed")
from core import prompt as _prompt_mod
_brief = api.make_prompt(GAME["appid"])["prompt"]
check("the brief tells the agent to make controllers act as a mouse on flat menus", all(s in _brief for s in ("Menus that are not translated to VR", "laser pointer", "Trigger = left click", "never leave me stuck", "controllers alone")) or all(s in _brief.lower() for s in ("laser pointer", "left click", "controllers alone")))
check('the brief points the agent to the REA reverse-engineering repo', 'github.com/morluto/rea' in _brief)
_ui = (HERE / "ui" / "app.js").read_text(encoding="utf-8")
check("guided setup asks one question at a time and is offered on the Create page", all(x in _ui for x in ("async function openWizard", "Question ${n + 1} of ${steps.length}", "Start guided setup")) and (HERE / "ui" / "index.html").read_text(encoding="utf-8").count('id="wizardDlg"') == 1)
from core import hub as _hub
import inspect as _insp
check("uploads and downloads get a long timeout (a 20 MB build on a slow link used to fail at 15 s)", "timeout=180" in _insp.getsource(_hub.publish) and "timeout=120" in _insp.getsource(_hub.get))
_iss = (HERE / "installer" / "plunge.iss").read_text(encoding="utf-8")
check("the installer has a real publisher name and no placeholder", "[" not in _iss.split("#define Publisher")[1].splitlines()[0] and "OPERATOR" not in _iss)
check("invite links work after a default install (the plunge:// handler is not opt-in)", 'Name: "protocol"' in _iss and "unchecked" not in [l for l in _iss.splitlines() if l.startswith('Name: "protocol"')][0])
_sec = (HERE / "SECURITY.md").read_text(encoding="utf-8")
_readme = (HERE / "README.md").read_text(encoding="utf-8")
check("SECURITY.md has a real contact and no blank to fill in", "security@plungevr.com" in _sec and not re.search(r"\[[A-Z][A-Z0-9 ]+\]", _sec) and "Fill the bracket" not in _sec)
check("the README says in plain words what the app reads, writes, starts and connects to", all(x in _readme for x in ("## What Plunge does on your PC", "**It reads**", "**It writes**", "**It starts programs**", "**It talks to the internet**", "**It never**")))
import ast as _ast
_bad = []
for _f in list((HERE / "core").glob("*.py")) + [HERE / "app.py"]:
    for _n in _ast.walk(_ast.parse(_f.read_text(encoding="utf-8"))):
        if isinstance(_n, _ast.Call):
            _name = getattr(_n.func, "id", None) or getattr(_n.func, "attr", "")
            if _name in ("eval", "exec", "system", "popen"):
                _bad.append((_f.name, _n.lineno, _name))
            if any(k.arg == "shell" and getattr(k.value, "value", False) is True for k in _n.keywords):
                _bad.append((_f.name, _n.lineno, "shell=True"))
check("the shipped code has no dynamic code execution, no os.system and no shell calls (the README promises it)", not _bad)
sys.exit(1 if fails else 0)
