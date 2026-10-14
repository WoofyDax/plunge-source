"""Client side of multiplayer: register a hosted game, keep it alive, resolve join codes."""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import safety

LOBBY_URL = os.environ.get("PLUNGE_LOBBY", "https://lobby.plungevr.com").rstrip("/")
_HOSTED = {}  # appid -> {"code", "key", "stop"}
CODE_RE = re.compile(r"^[A-Z2-9]{4,12}$")


class LobbyError(ValueError):             # a ValueError, so the app shows its message like any other expected problem
    pass


def _call(path, body=None):
    try:
        safety.require_secure_url(LOBBY_URL)
    except ValueError as e:
        raise LobbyError(str(e))
    req = urllib.request.Request(LOBBY_URL + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read(65536)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error", "lobby error")
        except ValueError:
            msg = "lobby error %d" % e.code
        raise LobbyError(msg)
    except (urllib.error.URLError, OSError):
        raise LobbyError("can't reach the lobby service at %s" % LOBBY_URL)
    try:
        return json.loads(raw)
    except ValueError:
        raise LobbyError("the lobby service sent something that isn't valid")


def free_port(base):
    """The first port from `base` upward that nothing on this PC is using (TCP and UDP), so two games never fight over one."""
    import socket
    for p in range(base, base + 80):
        socks = []
        try:
            for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
                s = socket.socket(socket.AF_INET, kind)
                socks.append(s)
                s.bind(("0.0.0.0", p))
            return p
        except OSError:
            continue
        finally:
            for s in socks:
                s.close()
    return base


def _ipconfig():
    import subprocess
    try:
        return subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def private_network():
    """A friends network on this PC (Tailscale or ZeroTier) and its address, or None. Friends can reach that address across the internet."""
    name, found = None, None
    for line in _ipconfig().splitlines():
        if line and not line[0].isspace():                      # an adapter heading such as "Ethernet adapter Tailscale:"
            low = line.lower()
            name = "Tailscale" if "tailscale" in low else "ZeroTier" if "zerotier" in low else None
        elif name and "ipv4" in line.lower():
            m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
            if m:
                found = {"name": name, "ip": m.group(1)}
                break
    return found


_LOCAL = re.compile(r"^(127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|localhost$|\[::1\]$)", re.I)


def reachable(addr):
    """If a game reports an address only this home network can use, swap in the Tailscale/ZeroTier one. Returns (address, network name or None)."""
    host, _, port = addr.rpartition(":") if addr.count(":") == 1 else (addr, "", "")
    if not _LOCAL.match(host or addr):
        return addr, None
    net = private_network()
    if not net:
        return addr, None
    return (net["ip"] + (":" + port if port else "")), net["name"]


def find_address(spec, game, timeout=60):
    """Read the host's address from a log file, on the line after fixed words (Melty's connect.address)."""
    from . import recipe
    log = str(spec["log"])
    if ".." in Path(log.replace("\\", "/")).parts or not log.startswith(("{game}/", "{localappdata}/")):
        raise LobbyError("the log path must start with {game}/ or {localappdata}/ and can't contain '..'")
    path = recipe.safe_dest(log, game) if log.startswith("{game}/") else Path(recipe.resolve(log, game))
    start = time.time()
    while time.time() - start < timeout:
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="ignore")
            i = text.rfind(spec["after"])
            if i >= 0:
                m = re.match(r"[A-Za-z0-9.\-:\[\]]+", text[i + len(spec["after"]):].strip())
                if m and safety.valid_address(m.group(0)):      # whatever the log says must be a plain address
                    return m.group(0)
        time.sleep(1)
    return None


def open_lobby(appid, profile, title, max_players, address, public):
    if not safety.valid_address(address):
        raise LobbyError("that address isn't valid (use host or host:port)")
    r = _call("/lobbies", {"appid": str(appid), "profile": profile, "title": title,
                           "maxPlayers": max_players, "address": address, "public": public})
    stop = threading.Event()

    def beat():
        while not stop.wait(15):
            try:
                _call("/lobbies/%s/beat" % r["code"], {"hostKey": r["hostKey"]})
            except LobbyError:
                pass
    threading.Thread(target=beat, daemon=True).start()
    _HOSTED[str(appid)] = {"code": r["code"], "key": r["hostKey"], "stop": stop}
    return {"code": r["code"]}


def close_lobby(appid):
    h = _HOSTED.pop(str(appid), None)
    if h:
        h["stop"].set()
        try:
            _call("/lobbies/%s/close" % h["code"], {"hostKey": h["key"]})
        except LobbyError:
            pass
    return {"closed": bool(h)}


def resolve(code):
    code = str(code).strip().upper().replace("PLUNGE://JOIN/", "").strip("/")
    if not CODE_RE.match(code):
        raise LobbyError("that isn't a join code (it looks like ABC234)")
    r = _call("/lobbies/%s/join" % code, {})
    if not safety.valid_address(r.get("address")):          # never trust the server's answer: it ends up in launch arguments
        raise LobbyError("the lobby returned an address that isn't valid")
    return r


def counts(appid=None):
    """Open games for a game (or every game): {"lobbies": [...public...], "publicCount": n, "privateCount": n}."""
    r = _call("/lobbies" + ("?appid=%s" % urllib.parse.quote(str(appid), safe="") if appid else ""))
    return {"lobbies": r.get("lobbies", []), "publicCount": int(r.get("publicCount", len(r.get("lobbies", [])))), "privateCount": int(r.get("privateCount", 0))}


def list_open(appid=None):
    return _call("/lobbies" + ("?appid=%s" % urllib.parse.quote(str(appid), safe="") if appid else ""))["lobbies"]
