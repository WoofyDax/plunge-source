"""Plunge as an MCP server (stdio): an AI agent that connects to it gets Plunge's tools natively instead of running commands.

Started by the agent itself (`plunge-cli mcp`). It speaks newline-delimited JSON-RPC on stdin/stdout, and exposes exactly the tools the
command line already has, with the same checks (no anti-cheat games, tracked installs, trust for third-party programs). It opens no port.
"""
import json
import sys

from . import api, paths, version

PROTOCOL = "2025-06-18"
APPID = {"type": "string", "description": "The game's id from list_games (a Steam app id, or an id like epic-1a2b3c4d)"}
SLUG = {"type": "string", "description": "The build's folder name inside Plunge's profiles folder"}


def _tool(name, desc, props=None, required=None):
    return {"name": name, "description": desc, "inputSchema": {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}}


TOOLS = {
    "list_games": (_tool("list_games", "List the games Plunge found on this PC (Steam, Epic, GOG, emulators and added programs), with engine, anti-cheat status and whether VR is built in."),
                   lambda a: api.games()),
    "game_info": (_tool("game_info", "Everything about one game: folder, engine, build id, the player's preferences, installed state, and the builds made for it.", {"appid": APPID}, ["appid"]),
                  lambda a: api.game_info(a["appid"])),
    "get_brief": (_tool("get_brief", "The full instructions for building a VR version of this game, written for you, including the player's preferences. Read this first.", {"appid": APPID}, ["appid"]),
                  lambda a: api.make_prompt(a["appid"])),
    "preferences": (_tool("preferences", "How the player wants the VR build to behave: camera, movement, comfort, controls, multiplayer.", {"appid": APPID}, ["appid"]),
                    lambda a: api.preferences(a["appid"])),
    "environment": (_tool("environment", "What is installed for testing in VR: the active OpenXR runtime, headset software that is running, Steam, and build tools."),
                    lambda a: api.environment()),
    "search_profiles": (_tool("search_profiles", "List the VR builds saved on this PC, optionally for one game.", {"appid": APPID}),
                        lambda a: api.search_profiles(a.get("appid"))),
    "profile_dir": (_tool("profile_dir", "The folder where a build must be saved.", {"slug": SLUG}, ["slug"]),
                    lambda a: api.profile_dir(a["slug"])),
    "validate_profile": (_tool("validate_profile", "Check a saved build (plunge.json and its files). Fix every error before telling the player it is done.", {"slug": SLUG, "appid": APPID}, ["slug"]),
                         lambda a: api.validate_profile(a["slug"], a.get("appid"))),
    "install_profile": (_tool("install_profile", "Install a build into the game the way the Play button does. Tracked, so uninstall_profile restores the game exactly. Never for games with anti-cheat.", {"slug": SLUG, "appid": APPID}, ["slug", "appid"]),
                        lambda a: api.install_profile(a["slug"], a["appid"])),
    "uninstall_profile": (_tool("uninstall_profile", "Remove everything Plunge installed into the game and restore the original files.", {"appid": APPID}, ["appid"]),
                          lambda a: api.uninstall_profile(a["appid"])),
    "launch_game": (_tool("launch_game", "Start the game (Steam games through Steam, programs and emulators directly) and report whether it really started.", {"appid": APPID}, ["appid"]),
                    lambda a: api.launch_game(a["appid"])),
}


def handle(msg):
    """One JSON-RPC message in, the reply (a dict) or None for notifications."""
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:                                           # notifications (initialized, cancelled...) get no answer
        return None
    ok = lambda result: {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or PROTOCOL, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "plunge", "version": version.VERSION},
                   "instructions": "Plunge makes games you own playable in VR. Start with get_brief for the game, build the VR layer, save it with validate_profile clean, test with install_profile and launch_game, then uninstall_profile."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [t for t, _ in TOOLS.values()]})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool: %s" % name}}
        if not isinstance(args, dict):
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "arguments must be an object"}}
        try:
            out = TOOLS[name][1](args)
            return ok({"content": [{"type": "text", "text": json.dumps(out, indent=1)}], "isError": False})
        except (ValueError, TypeError, KeyError, RuntimeError, OSError) as e:      # a tool failing is the tool's answer, not a protocol error
            return ok({"content": [{"type": "text", "text": json.dumps({"error": str(e)})}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}


def serve(stdin=None, stdout=None):
    """Run until the agent closes the pipe. Anything the tools print goes to stderr so it can never corrupt the protocol."""
    paths.ensure()
    rin, rout = stdin or sys.stdin, stdout or sys.stdout
    real_out, saved = rout, sys.stdout
    sys.stdout = sys.stderr
    try:
        for line in rin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if not isinstance(msg, dict):
                    raise ValueError("not an object")
            except ValueError:
                real_out.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
                real_out.flush()
                continue
            reply = handle(msg)
            if reply is not None:
                real_out.write(json.dumps(reply) + "\n")
                real_out.flush()
    finally:
        sys.stdout = saved
