"""Tests: finding AI agents, building their commands safely, and starting one on a brief. Fake agents on an isolated PATH;
nothing real is launched."""
import os
import sys
import tempfile
import time
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
bin_dir = tmp / "bin"
bin_dir.mkdir()
for name, ver in (("claude", "2.1.300 (Claude Code)"), ("codex", "codex-cli 0.9.0"), ("gemini", "0.7.1"), ("grok", "grok 1.0")):
    (bin_dir / (name + ".cmd")).write_text("@echo off\r\necho %s\r\n" % ver)
os.environ["PATH"] = str(bin_dir) + os.pathsep + r"C:\Windows\System32" + os.pathsep + r"C:\Windows"
os.environ["USERPROFILE"] = str(tmp / "home")
os.environ["HOME"] = str(tmp / "home")
os.environ["APPDATA"] = str(tmp / "roam")
os.environ["LOCALAPPDATA"] = str(tmp / "local")
sys.path.insert(0, str(Path(__file__).parent))
from core import agents, api, paths, settings, vrinfo  # noqa: E402

paths.ensure()
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


def raises(fn):
    try:
        fn()
        return False
    except agents.AgentError:
        return True
    except ValueError:
        return True


# ---- detection -------------------------------------------------------------------------------------------
d = {a["id"]: a for a in agents.detect()}
check("finds the agents that are installed", all(d[k]["found"] for k in ("claude", "codex", "gemini", "grok")))
check("doesn't invent agents that aren't", not d["aider"]["found"] and not d["opencode"]["found"] and d["aider"]["path"] is None)
check("reads each agent's version", "2.1.300" in d["claude"]["version"] and "0.9.0" in d["codex"]["version"])
check("claude, codex and gemini send the message for you", [d[k]["mode"] for k in ("claude", "codex", "gemini")] == ["auto"] * 3)
check("grok and the others are paste-only (their start flag isn't confirmed)", d["grok"]["mode"] == "paste" and d["aider"]["mode"] == "paste")
check("every agent offers an install page and a plans page", all(a["install"].startswith("https://") and a["plans"].startswith("https://") for a in d.values()))
check("claude lists model and effort choices", {"sonnet", "opus"} <= {m["id"] for m in d["claude"]["models"]} and {"low", "medium", "high"} <= {e["id"] for e in d["claude"]["efforts"]})
check("detect can skip running the programs", all(a["version"] == "" for a in agents.detect(with_versions=False)))
(tmp / "home" / ".local" / "bin").mkdir(parents=True)
(tmp / "home" / ".local" / "bin" / "aider.exe").write_bytes(b"MZ")
check("agents in the usual per-user folders are found even off PATH", agents.find_exe(["aider"]).endswith("aider.exe"))

# ---- command building --------------------------------------------------------------------------------------
work, gdir, pdir = tmp / "work", tmp / "game", tmp / "profile"
for x in (work, gdir, pdir):
    x.mkdir()
exe = r"C:\tools\claude.exe"
args, notes = agents.build_command("claude", exe, "opus", "high", [pdir, gdir], work)
check("claude: message first, then model, effort and folders", args == [exe, agents.FIRST_MESSAGE, "--model", "opus", "--effort", "high", "--add-dir", str(pdir), "--add-dir", str(gdir)])
args, _ = agents.build_command("claude", exe)
check("claude with defaults passes only the message", args == [exe, agents.FIRST_MESSAGE])
args, _ = agents.build_command("codex", r"C:\tools\codex.exe", "gpt-custom-1", "medium", [gdir], work)
check("codex: -C, --add-dir, -m, effort via -c, message last", args == [r"C:\tools\codex.exe", "-C", str(work), "--add-dir", str(gdir), "-m", "gpt-custom-1", "-c", 'model_reasoning_effort="medium"', agents.FIRST_MESSAGE])
args, _ = agents.build_command("gemini", r"C:\tools\gemini.exe", "flash", "default", [gdir], work)
check("gemini: -m, --include-directories, then -i with the message", args == [r"C:\tools\gemini.exe", "-m", "flash", "--include-directories", str(gdir), "-i", agents.FIRST_MESSAGE])
args, _ = agents.build_command("grok", r"C:\tools\grok.exe", "default", "default", [gdir], work)
check("paste-only agents are just opened", args == [r"C:\tools\grok.exe"])
check("the first message is fixed text that points at BRIEF.md", "BRIEF.md" in agents.FIRST_MESSAGE and len(agents.FIRST_MESSAGE) < 140)

# ---- validation ---------------------------------------------------------------------------------------------------
for bad in ["opus; calc", "a b", "--dangerously-skip-permissions", "-x", "m" * 200, "mod&el", "m\nodel", "mod|el", "$(x)", "", "../x"[:0] + "x/../"]:
    if bad in ("", "x/../"):
        continue
    if not raises(lambda b=bad: agents.build_command("claude", exe, b)):
        check("rejects model name %r" % bad, False)
        break
else:
    check("rejects model names with spaces, shell characters, a leading dash or too long", True)
check("rejects an effort the agent doesn't have", raises(lambda: agents.build_command("codex", exe, "default", "max")) and raises(lambda: agents.build_command("claude", exe, "default", "turbo")))
check("rejects an unknown agent", raises(lambda: agents.build_command("skynet", exe)))
flag_args = []
for pid, p in agents.PROVIDERS.items():
    for m in [m for m, _ in p["models"]] + ["custom-model.1"]:
        for e in [e for e, _ in p["efforts"]]:
            a, _ = agents.build_command(pid, r"C:\t\%s.exe" % pid, m, e, [gdir], work)
            flag_args += [x for x in a[1:] if x.startswith("-")]
bad_flags = [f for f in flag_args if any(w in f.lower() for w in ("dangerously", "yolo", "bypass", "skip-permissions", "danger-full-access", "approval", "sandbox"))]
check("no combination ever passes a flag that turns off the agent's safety prompts (%d flags checked)" % len(flag_args), not bad_flags and len(flag_args) > 50)
check("the safety net itself refuses such a flag", raises(lambda: agents._assert_safe([exe, "--dangerously-skip-permissions"])))

# ---- batch files can't safely take some characters -----------------------------------------------------------------------
risky = tmp / "A & B"
risky.mkdir()
a, n = agents.build_command("claude", r"C:\npm\claude.cmd", "default", "default", [risky, gdir], work)
check("a folder with & is left out of a .cmd launcher, with a note", str(risky) not in a and str(gdir) in a and any("unsafe" in x for x in n))
a, n = agents.build_command("claude", r"C:\tools\claude.exe", "default", "default", [risky], work)
check("the same folder is fine for a real .exe", str(risky) in a)
check("a .cmd path with a risky character is refused", raises(lambda: agents.build_command("claude", r"C:\a&b\claude.cmd")))
a, n = agents.build_command("claude", exe, "default", "default", [tmp / "missing"], work)
check("a folder that doesn't exist is left out, with a note", "--add-dir" not in a and any("doesn't exist" in x for x in n))
check("display() quotes paths with spaces", '"' in agents.display([exe, "a b"]))

# ---- API: preview and start (launch and clipboard stubbed) ----------------------------------------------------------------------
route = {"id": "agent-unity", "label": "x", "maturity": "m", "note": "n"}
GAME_DIR = tmp / "steam" / "Cool Game"
GAME_DIR.mkdir(parents=True)
GAME = {"appid": "4242", "name": "Cool Game", "path": str(GAME_DIR), "exe": None, "engine": "unity", "anticheat": [], "status": "experimental",
        "why": "", "route": route, "launch": {"kind": "steam", "appid": "4242"}, "store": "Steam", "buildId": "7"}
PROT = {**GAME, "appid": "5", "name": "Locked", "anticheat": ["Easy Anti-Cheat"], "status": "blocked", "why": "Uses anti-cheat (Easy Anti-Cheat). Plunge never touches games with anti-cheat."}
api._STATE.update(games=[GAME, PROT], demo=False)
vrinfo._save({"4242": {"level": None, "vac": False, "t": time.time()}, "5": {"level": None, "vac": False, "t": time.time()}})
launched, copied = [], []
agents.launch = lambda args, workdir: launched.append((list(args), str(workdir)))
api.copy_text = lambda t: copied.append(t) or {"ok": True}

pv = api.agent_preview("4242", "claude", "sonnet", "high", True)
check("preview shows the exact command and doesn't launch or write anything", "--model sonnet" in pv["command"] and "--effort high" in pv["command"] and not launched and not (paths.DATA / "agent").exists() or not any((paths.DATA / "agent").rglob("BRIEF.md")))
check("preview includes the game's folder when allowed", str(GAME_DIR) in pv["command"])
check("preview leaves the game's folder out when not allowed", str(GAME_DIR) not in api.agent_preview("4242", "claude", "default", "default", False)["command"])
r = api.agent_start("4242", "claude", "opus", "medium", True)
args, wd = launched[-1]
check("start launches the agent in the agent folder", wd == str(paths.DATA / "agent" / "cool-game-vr") and args[0].lower().endswith("claude.cmd"))
brief = (paths.DATA / "agent" / "cool-game-vr" / "BRIEF.md").read_bytes()
check("BRIEF.md is written as UTF-8 without a BOM", not brief.startswith(b"\xef\xbb\xbf") and b"Cool Game" in brief and len(brief) > 5000)
check("BRIEF.md is NOT inside the profile folder (so it can't be published)", not (paths.PROFILES / "cool-game-vr" / "BRIEF.md").exists())
check("the brief on disk contains no tokens or secrets", b"llc_" not in brief and b"Bearer" not in brief)
check("the agent gets the profile folder and the game folder", str(paths.PROFILES / "cool-game-vr") in args and str(GAME_DIR) in args)
check("start remembers the choice", settings.get("agent") == {"provider": "claude", "model": "opus", "effort": "medium", "gameAccess": True})
check("auto agents don't touch the clipboard", r["mode"] == "auto" and r["pasted"] is False and not copied)
r = api.agent_start("4242", "grok", "default", "default", False)
check("paste-only agents get one line on the clipboard", r["pasted"] is True and copied == [agents.FIRST_MESSAGE])
check("paste-only agents are opened with no message argument", launched[-1][0][1:] == [])
try:
    api.agent_start("5", "claude")
    check("a game with anti-cheat can't be sent to an agent", False)
except ValueError as e:
    check("a game with anti-cheat can't be sent to an agent", "anti-cheat" in str(e).lower())
try:
    api.agent_start("4242", "opencode")
    check("an agent that isn't installed gives a clear error", False)
except ValueError:
    check("an agent that isn't installed gives a clear error", True)
try:
    api.agent_start("4242", "claude", "bad;model")
    check("a bad model name is refused before anything runs", False)
except ValueError:
    check("a bad model name is refused before anything runs", len(launched) == 2)
check("detect via the API returns the saved choice", api.agents_detect()["saved"]["provider"] == "grok")

# ---- open_url only opens the official pages Plunge lists ----------------------------------------------------------------------------------
opened = []
os.startfile = lambda u: opened.append(u)
api.open_url(agents.PROVIDERS["claude"]["install"])
check("open_url opens an official install page", opened == [agents.PROVIDERS["claude"]["install"]])
for bad in ["https://evil.example/", "file:///C:/Windows/system32/calc.exe", "javascript:alert(1)", "http://claude.com/pricing", ""]:
    try:
        api.open_url(bad)
        check("open_url refuses %r" % bad, False)
        break
    except ValueError:
        pass
else:
    check("open_url refuses any other address", True)

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
