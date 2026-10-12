"""Plunge lobby service. Hosts register a game and get a join code; joiners trade the code for the
host's address. It never touches a game's own servers. In-memory, standard library only.

Run it behind an HTTPS reverse proxy (see deploy/); set PLUNGE_TRUST_PROXY=1 only when the proxy sets X-Forwarded-For.

    python app.py lobby [--port 8787] [--bind 0.0.0.0]
"""
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import safety

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L
TTL = 45  # seconds without a heartbeat before a lobby disappears
MAX_LOBBIES = 2000
LOCK = threading.Lock()
LOBBIES = {}
LIMITER = safety.RateLimiter()
LIMITS = {"read": (240, 60), "create": (10, 60), "join": (30, 60), "other": (60, 60), "guess": (20, 60)}   # (hits, seconds) per client address


def _sweep():
    now = time.time()
    for code in [c for c, l in LOBBIES.items() if now - l["beat"] > TTL]:
        del LOBBIES[code]


def _public(l):
    return {k: l[k] for k in ("code", "appid", "profile", "title", "maxPlayers", "players", "public")}


def _int(v, default, lo, hi):
    try:
        return max(lo, min(int(v), hi))
    except (TypeError, ValueError):
        return default


class Handler(BaseHTTPRequestHandler):
    timeout = 20                                      # drops slow or stalled connections

    def log_message(self, *a):
        pass

    def _ip(self):
        if os.environ.get("PLUNGE_TRUST_PROXY") == "1":
            # the LAST entry is the one our own proxy appended; earlier entries can be forged by the client to dodge rate limits
            return (self.headers.get("X-Forwarded-For", "").split(",")[-1].strip() or self.client_address[0])[:64]
        return self.client_address[0]

    def _limited(self, kind):
        hits, secs = LIMITS[kind]
        if LIMITER.allow((kind, self._ip()), hits, secs):
            return False
        self._send({"error": "slow down: too many requests"}, 429)
        return True

    def _send(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = _int(self.headers.get("Content-Length"), 0, 0, 8192)
        try:
            b = json.loads(self.rfile.read(n) or b"{}")
            return b if isinstance(b, dict) else {}
        except ValueError:
            return {}

    def _miss(self):
        """A wrong code counts against the caller, so private lobbies can't be found by guessing codes."""
        hits, secs = LIMITS["guess"]
        if not LIMITER.allow(("guess", self._ip()), hits, secs):
            return self._send({"error": "slow down: too many requests"}, 429)
        return self._send({"error": "no such lobby (it may have closed)"}, 404)

    def do_GET(self):
        if self.path == "/health":                              # for the uptime monitor and the container health check
            return self._send({"ok": True, "service": "lobby"})
        if self._limited("read"):
            return
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        with LOCK:
            _sweep()
            if parts == ["lobbies"]:
                appid = (parse_qs(u.query).get("appid") or [None])[0]
                rows = [_public(l) for l in LOBBIES.values() if l["public"] and (not appid or l["appid"] == appid)]
                return self._send({"lobbies": rows[:100]})
            if len(parts) == 2 and parts[0] == "lobbies":
                l = LOBBIES.get(parts[1].upper())
                return self._send(_public(l)) if l else self._miss()
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        b = self._body()
        with LOCK:
            _sweep()
            if parts == ["lobbies"]:
                if self._limited("create"):
                    return
                if len(LOBBIES) >= MAX_LOBBIES:
                    return self._send({"error": "lobby service is full"}, 503)
                addr, appid = str(b.get("address", "")), safety.clean_text(b.get("appid", ""), 40)
                if not safety.valid_address(addr):
                    return self._send({"error": "that address isn't valid (use host or host:port)"}, 400)
                if not appid:
                    return self._send({"error": "address and appid are required"}, 400)
                code = "".join(secrets.choice(ALPHABET) for _ in range(6))
                key = secrets.token_urlsafe(16)
                LOBBIES[code] = {
                    "code": code, "hostKey": key, "address": addr, "appid": appid,
                    "profile": safety.clean_text(b.get("profile", ""), 60),
                    "title": safety.clean_text(b.get("title", ""), 60) or "Untitled game",
                    "maxPlayers": _int(b.get("maxPlayers"), 2, 2, 64), "players": 1, "joined": set(),
                    "public": bool(b.get("public")), "beat": time.time(),
                }
                return self._send({"code": code, "hostKey": key})
            if len(parts) == 3 and parts[0] == "lobbies":
                if self._limited("other"):
                    return
                l = LOBBIES.get(parts[1].upper())
                if not l:
                    return self._miss()
                if parts[2] == "join":
                    if self._limited("join"):
                        return
                    ip = self._ip()
                    if ip not in l["joined"]:                      # one slot per address, so repeated joins can't fill a lobby
                        if l["players"] >= l["maxPlayers"]:
                            return self._send({"error": "lobby is full"}, 409)
                        l["joined"].add(ip)
                        l["players"] += 1
                    return self._send({"address": l["address"], "appid": l["appid"], "profile": l["profile"]})
                host_ok = secrets.compare_digest(str(b.get("hostKey", "")), l["hostKey"])
                if parts[2] in ("beat", "close") and not host_ok:
                    return self._send({"error": "not the host"}, 403)
                if parts[2] == "beat":
                    l["beat"] = time.time()
                    if isinstance(b.get("players"), int):
                        l["players"] = max(1, min(b["players"], l["maxPlayers"]))
                    return self._send({"ok": True})
                if parts[2] == "close":
                    del LOBBIES[l["code"]]
                    return self._send({"ok": True})
        self._send({"error": "not found"}, 404)


def serve(port=8787, bind="127.0.0.1"):
    srv = ThreadingHTTPServer((bind, port), Handler)
    print("Plunge lobby service on http://%s:%d" % (bind, port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
