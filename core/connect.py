"""The "Connect Plunge to my AI tools" button: register Plunge's MCP server with Claude Code, Codex, VS Code, Claude Desktop and Cursor.

Only ever done when the player presses Connect for that tool. The command CLIs (claude, codex, code) do the registration themselves; the two
tools that keep a JSON file (Claude Desktop, Cursor) get that file backed up first and only Plunge's own entry added.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

NAME = "plunge"


def server_command():
    """[command, args...] an agent runs to start Plunge's tool server."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("plunge-cli.exe")), "mcp"]
    return [sys.executable, str(Path(__file__).resolve().parent.parent / "app.py"), "mcp"]


def _json_file(tool):
    home = Path(os.path.expanduser("~"))
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    if tool == "claude-desktop":                               # the Store version of the app keeps its settings inside its package folder
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        for pkg in sorted((local / "Packages").glob("Claude_*")) if (local / "Packages").is_dir() else []:
            cand = pkg / "LocalCache" / "Roaming" / "Claude"
            if cand.is_dir():
                return cand / "claude_desktop_config.json"
    return {"claude-desktop": appdata / "Claude" / "claude_desktop_config.json", "cursor": home / ".cursor" / "mcp.json"}.get(tool)


TOOLS = [
    {"id": "claude-code", "name": "Claude Code", "how": "cli", "exe": "claude"},
    {"id": "codex", "name": "Codex", "how": "cli", "exe": "codex"},
    {"id": "vscode", "name": "VS Code", "how": "cli", "exe": "code"},
    {"id": "claude-desktop", "name": "Claude desktop app", "how": "json"},
    {"id": "cursor", "name": "Cursor", "how": "json"},
]


def _run(args, timeout=30):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def _cli_connected(t):
    exe = shutil.which(t["exe"])
    try:
        if t["id"] == "claude-code":
            return NAME in _run([exe, "mcp", "list"])[1].lower()
        if t["id"] == "codex":
            return NAME in _run([exe, "mcp", "list"])[1].lower()
    except (OSError, subprocess.SubprocessError):
        return False
    return False                                              # VS Code can't be asked from outside: it is "connect again" safe


def _json_connected(t):
    f = _json_file(t["id"])
    try:
        return NAME in (json.loads(f.read_text(encoding="utf-8-sig")).get("mcpServers") or {})
    except (OSError, ValueError, AttributeError):
        return False


def status():
    out = []
    for t in TOOLS:
        if t["how"] == "cli":
            present = bool(shutil.which(t["exe"]))
            connected = _cli_connected(t) if present else False
        else:
            f = _json_file(t["id"])
            present = bool(f and f.parent.exists())
            connected = _json_connected(t) if present else False
        out.append({"id": t["id"], "name": t["name"], "found": present, "connected": connected})
    cmd = server_command()
    return {"tools": out, "snippet": json.dumps({"mcpServers": {NAME: {"command": cmd[0], "args": cmd[1:]}}}, indent=2)}


def _merge_json(tool):
    f = _json_file(tool)
    f.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig") or "{}")
        except ValueError:
            raise ValueError("%s isn't valid JSON, so Plunge didn't touch it. Fix or remove it, then try again." % f)
        if not isinstance(data, dict):
            raise ValueError("%s has an unexpected shape, so Plunge didn't touch it" % f)
        shutil.copy2(f, f.with_name(f.name + ".plunge-backup-%d" % int(time.time())))
    servers = data.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        raise ValueError("%s has an unexpected mcpServers section, so Plunge didn't touch it" % f)
    cmd = server_command()
    data.setdefault("mcpServers", {})[NAME] = {"command": cmd[0], "args": cmd[1:]}
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")


def connect(tool):
    t = next((x for x in TOOLS if x["id"] == tool), None)
    if not t:
        raise ValueError("unknown tool")
    cmd = server_command()
    if t["how"] == "json":
        _merge_json(tool)
        return {"connected": True, "note": "Restart %s to pick it up." % t["name"]}
    exe = shutil.which(t["exe"])
    if not exe:
        raise ValueError("%s isn't installed (its command isn't on this PC's PATH)" % t["name"])
    if t["id"] == "claude-code":
        args = [exe, "mcp", "add", "--scope", "user", NAME, "--"] + cmd
    elif t["id"] == "codex":
        args = [exe, "mcp", "add", NAME, "--"] + cmd
    else:
        args = [exe, "--add-mcp", json.dumps({"name": NAME, "command": cmd[0], "args": cmd[1:]})]
    try:
        rc, out = _run(args)
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError("couldn't run %s: %s" % (t["name"], e))
    if rc != 0 and "already exists" not in out.lower():
        raise ValueError("%s said: %s" % (t["name"], out[:300] or "it didn't connect"))
    return {"connected": True, "note": "Restart %s (or start a new chat) to pick it up." % t["name"]}


def disconnect(tool):
    t = next((x for x in TOOLS if x["id"] == tool), None)
    if not t:
        raise ValueError("unknown tool")
    if t["how"] == "json":
        f = _json_file(tool)
        if f and f.exists():
            data = json.loads(f.read_text(encoding="utf-8-sig") or "{}")
            if isinstance(data.get("mcpServers"), dict) and NAME in data["mcpServers"]:
                shutil.copy2(f, f.with_name(f.name + ".plunge-backup-%d" % int(time.time())))
                del data["mcpServers"][NAME]
                f.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return {"connected": False}
    exe = shutil.which(t["exe"])
    if exe and t["id"] in ("claude-code", "codex"):
        _run([exe, "mcp", "remove"] + (["--scope", "user"] if t["id"] == "claude-code" else []) + [NAME])
    return {"connected": False, "note": "For VS Code, remove “plunge” from its MCP servers list."}
