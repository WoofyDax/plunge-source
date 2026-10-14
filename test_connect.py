"""Tests: the MCP tool server and Connect button, emulator and program games, open games for the home page. Temp dirs only."""
import io
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(tmp / "local")
os.environ["APPDATA"] = str(tmp / "roam")
os.environ["USERPROFILE"] = str(tmp / "home")
os.environ["HOME"] = str(tmp / "home")
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from core import api, connect, lobby, lobby_server, mcp, paths, scanner, settings, stores  # noqa: E402

paths.ensure()
fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# ---- the MCP server ---------------------------------------------------------------------------------------
call = lambda m, i=1, p=None: mcp.handle({"jsonrpc": "2.0", "id": i, "method": m, "params": p or {}})
init = call("initialize", 1, {"protocolVersion": "2025-03-26"})
check("initialize answers with the client's protocol and the tools capability", init["result"]["protocolVersion"] == "2025-03-26" and "tools" in init["result"]["capabilities"] and init["result"]["serverInfo"]["name"] == "plunge")
check("a notification gets no answer", mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None)
tools = call("tools/list")["result"]["tools"]
names = {t["name"] for t in tools}
check("the same tools as the command line, plus the brief", {"list_games", "game_info", "get_brief", "install_profile", "uninstall_profile", "launch_game", "validate_profile", "environment"} <= names)
check("every tool has a schema and a description", all(t["inputSchema"]["type"] == "object" and len(t["description"]) > 20 for t in tools))
check("nothing can publish, sign in or touch accounts", not any(n for n in names if any(w in n for w in ("publish", "sign", "account", "password", "token", "delete", "like"))))
bad = call("tools/call", 2, {"name": "game_info", "arguments": {"appid": "nope"}})["result"]
check("a failing tool is an error result the agent can read, not a crash", bad["isError"] is True and "unknown game" in bad["content"][0]["text"])
check("an unknown tool and bad arguments are protocol errors", call("tools/call", 3, {"name": "rm_rf"})["error"]["code"] == -32602 and call("tools/call", 4, {"name": "environment", "arguments": "x"})["error"]["code"] == -32602)
check("an unknown method is refused", call("do/it")["error"]["code"] == -32601)
stdin = io.StringIO("\n".join([json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}), "not json", json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})]) + "\n")
stdout = io.StringIO()
real = sys.stdout
mcp.serve(stdin, stdout)
lines = [json.loads(l) for l in stdout.getvalue().splitlines()]
check("a whole stdio session: ping, garbage and tools/list, one JSON line each", [l.get("id") for l in lines] == [1, None, 2] and lines[1]["error"]["code"] == -32700 and sys.stdout is real)

# ---- connecting AI tools -----------------------------------------------------------------------------------
st = connect.status()
check("status lists the five tools and a copyable settings entry", [t["id"] for t in st["tools"]] == ["claude-code", "codex", "vscode", "claude-desktop", "cursor"] and '"mcpServers"' in st["snippet"] and '"plunge"' in st["snippet"])
cur = tmp / "home" / ".cursor"
cur.mkdir(parents=True)
(cur / "mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
r = connect.connect("cursor")
data = json.loads((cur / "mcp.json").read_text())
check("connecting a JSON-based tool adds only Plunge's entry and keeps the others", data["mcpServers"]["other"] == {"command": "x"} and data["mcpServers"]["plunge"]["args"][-1] == "mcp")
check("the file was backed up first", any(p.name.startswith("mcp.json.plunge-backup-") for p in cur.iterdir()))
check("status now shows it connected", next(t for t in connect.status()["tools"] if t["id"] == "cursor")["connected"])
connect.disconnect("cursor")
check("disconnecting removes only Plunge's entry", "plunge" not in json.loads((cur / "mcp.json").read_text())["mcpServers"] and "other" in json.loads((cur / "mcp.json").read_text())["mcpServers"])
(cur / "mcp.json").write_text("{ not json")
try:
    connect.connect("cursor")
    check("a settings file Plunge can't read is left alone", False)
except ValueError:
    check("a settings file Plunge can't read is left alone", (cur / "mcp.json").read_text() == "{ not json")
(cur / "mcp.json").write_text(json.dumps({"mcpServers": ["wrong"]}))
try:
    connect.connect("cursor")
    check("an unexpected mcpServers shape is left alone", False)
except ValueError:
    check("an unexpected mcpServers shape is left alone", True)
try:
    connect.connect("rm")
    check("an unknown tool is refused", False)
except ValueError:
    check("an unknown tool is refused", True)

# command-line tools: a fake `claude` and `codex` that record how they were called
bindir = tmp / "bin"
bindir.mkdir()
log = tmp / "calls.txt"
for exe in ("claude", "codex", "code"):
    (bindir / (exe + ".cmd")).write_text('@echo off\r\necho %~n0 %* >> "' + str(log) + '"\r\nexit /b 0\r\n')
os.environ["PATH"] = str(bindir) + os.pathsep + os.environ["PATH"]
check("tools found on PATH are reported as found", all(t["found"] for t in connect.status()["tools"] if t["id"] in ("claude-code", "codex", "vscode")))
connect.connect("claude-code")
connect.connect("codex")
connect.connect("vscode")
calls = log.read_text().splitlines()
check("Claude Code is registered with its own CLI, user scope, no shell", any(c.startswith("claude mcp add --scope user plunge --") and c.rstrip().endswith("mcp") for c in calls))
check("Codex is registered with its own CLI", any(c.startswith("codex mcp add plunge --") for c in calls))
check("VS Code gets a JSON server entry through --add-mcp", any(c.startswith("code --add-mcp") and '"name": "plunge"' in c.replace('\\"', '"') for c in calls))
(bindir / "claude.cmd").write_text('@echo off\r\necho boom 1>&2\r\nexit /b 1\r\n')
try:
    connect.connect("claude-code")
    check("a CLI that fails gives the player its own message", False)
except ValueError as e:
    check("a CLI that fails gives the player its own message", "boom" in str(e))

# ---- emulator and program games ---------------------------------------------------------------------------------
emu = tmp / "Emus" / "Dolphin"
emu.mkdir(parents=True)
(emu / "Dolphin.exe").write_bytes(b"MZ")
rom1, rom2 = tmp / "mario.iso", tmp / "zelda.iso"
rom1.write_bytes(b"x")
rom2.write_bytes(b"x")
a = api.add_program(str(emu / "Dolphin.exe"), str(rom1))
b = api.add_program(str(emu / "Dolphin.exe"), str(rom2), "Zelda", "--batch")
check("an emulator is recognised by name", a["emulator"] == "GameCube / Wii" and stores.emulator_of("C:/x/RPCS3/rpcs3.exe") == "PlayStation 3" and stores.emulator_of("C:/x/notepad.exe") is None)
progs = [g for g in api._load() if g.get("program")]
check("two game files in one emulator are two games", len(progs) == 2 and {g["name"] for g in progs} == {"mario", "Zelda"})
g1 = next(g for g in progs if g["name"] == "mario")
check("they are launched with the game file first, then the extra options", g1["launch"]["args"] == [str(rom1.resolve())] and next(g for g in progs if g["name"] == "Zelda")["launch"]["args"][-1] == "--batch")
check("the route is the emulator route and the brief tells the agent to work on the emulator", g1["engine"] == "emulator" and g1["route"]["id"] == "agent-emulator" and "EMULATOR" in api.make_prompt(g1["appid"])["prompt"])
check("the brief forbids downloading game files, BIOS images and keys", "Never download, share or bundle game files" in api.make_prompt(g1["appid"])["prompt"])
check("the program ids never collide with Steam's numbers", g1["appid"].startswith("prog-"))
(emu / "EasyAntiCheat").mkdir()
(emu / "EasyAntiCheat" / "EasyAntiCheat_x64.dll").write_bytes(b"x")
api._load(True)
check("a program that ships anti-cheat is blocked like any game", next(g for g in api._load() if g["appid"] == g1["appid"])["status"] == "blocked")
import shutil  # noqa: E402
shutil.rmtree(emu / "EasyAntiCheat")
for bad_exe, why in ((str(rom1), "a game file is not a program"), (str(tmp / "nope.exe"), "a missing program"), ("", "nothing")):
    try:
        api.add_program(bad_exe, None)
        check("refuses: " + why, False)
    except ValueError:
        check("refuses: " + why, True)
try:
    api.add_program(str(emu / "Dolphin.exe"), str(tmp / "missing.iso"))
    check("a missing game file is refused", False)
except ValueError:
    check("a missing game file is refused", True)
try:
    api.add_program(str(emu / "Dolphin.exe"), None, None, '"unclosed')
    check("unparseable extra options are refused", False)
except ValueError:
    check("unparseable extra options are refused", True)
rom1.unlink()
check("a program whose game file went missing quietly drops out of the library", not any(g["name"] == "mario" for g in api._load(True)))
api.remove_program(b["added"])
check("removing deletes only the entry, never a file", not any(g.get("program") for g in api._load(True)) and (emu / "Dolphin.exe").exists() and rom2.exists())

started = []
import subprocess  # noqa: E402
from core import launcher  # noqa: E402
real_popen = subprocess.Popen
subprocess.Popen = lambda cmd, **k: started.append((cmd, k.get("cwd"))) or type("P", (), {})()
try:
    api.add_program(str(emu / "Dolphin.exe"), str(rom2), "Zelda")
    gz = next(g for g in api._load(True) if g.get("program"))
    res = launcher.start(gz, [], {})
finally:
    subprocess.Popen = real_popen
check("launching runs the program directly (no shell) with the game file as an argument", started and started[0][0][0].endswith("Dolphin.exe") and started[0][0][1] == str(rom2.resolve()) and res["how"] == "exe")

# ---- open games on the home page ---------------------------------------------------------------------------------
lobby_server.LIMITS.update({k: (10000, 3600) for k in lobby_server.LIMITS})
srv = ThreadingHTTPServer(("127.0.0.1", 0), lobby_server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
lobby.LOBBY_URL = "http://127.0.0.1:%d" % srv.server_address[1]
lobby_server._LIST_CACHE.clear()
lobby.open_lobby("1", "p", "Alpha game", 4, "8.8.8.8:1", True)
lobby.open_lobby("2", "p", "Beta game", 4, "8.8.8.8:2", True)
lobby.open_lobby("2", "p", "Secret game", 4, "8.8.8.8:3", False)
o = api.open_games()
check("the home page gets every public game and a count of private ones", len(o["lobbies"]) == 2 and o["publicCount"] == 2 and o["privateCount"] == 1)
check("private games are counted but never listed or leaked", all(l["title"] != "Secret game" for l in o["lobbies"]) and "8.8.8.8" not in json.dumps(o))
check("filtering by game still works", lobby.counts("2")["publicCount"] == 1 and lobby.counts("2")["privateCount"] == 1)
lobby.open_lobby("3", "p", "Gamma game", 4, "8.8.8.8:4", True)
check("repeat polling is answered from a short cache (cheap on the server)", len(api.open_games()["lobbies"]) == 2)
lobby_server._LIST_CACHE.clear()
check("and fresh again once the cache is cleared", len(api.open_games()["lobbies"]) == 3)
for i in range(300):
    lobby_server._LIST_CACHE["k%d" % i] = (0, {})
api.lobbies("zzz")
check("the cache can't be grown without limit by odd game ids", len(lobby_server._LIST_CACHE) <= 202)

# ---- the screens ---------------------------------------------------------------------------------------------------
ui = (HERE / "ui" / "app.js").read_text(encoding="utf-8")
html = (HERE / "ui" / "index.html").read_text(encoding="utf-8")
check("the app has the connect screen, the add-a-game screen and open games on Discover", all(x in ui for x in ("async function openConnect", "function openAddProgram", "function openGamesSection")) and all(x in html for x in ('id="connectDlg"', 'id="progDlg"', 'id="addProgram"')))

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
