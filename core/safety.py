"""Small security helpers shared by the app, the hub and the lobby."""
import re
import threading
import time
from urllib.parse import urlparse

# host or IPv4, or [IPv6], with an optional :port. This is what ends up in a game's launch arguments or config file, so it
# must not be able to carry spaces, quotes, newlines, '+' commands or anything else a game could treat as an instruction.
_HOST = r"(?:\[[0-9A-Fa-f:.]{2,45}\]|[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)"
ADDRESS_RE = re.compile(r"^%s(?::[0-9]{1,5})?$" % _HOST)
# Unicode controls that can make text read differently from what it is (right-to-left overrides, zero-width characters)
_BAD_CHARS = re.compile("[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁠-⁩﻿]")


def valid_address(addr):
    """True only for a plain 'host', 'host:port', '1.2.3.4:port' or '[::1]:port'."""
    # fullmatch, not match: '$' would also accept a trailing newline, which could inject a line into a config file
    if not isinstance(addr, str) or not 1 <= len(addr) <= 260 or not ADDRESS_RE.fullmatch(addr):
        return False
    if ":" in addr and not addr.endswith("]"):
        port = addr.rsplit(":", 1)[1]
        if port.isdigit() and not 1 <= int(port) <= 65535:
            return False
    return ".." not in addr


# A build may set its OWN environment variables for hosting and joining (MYMOD_JOIN), never the system's or a runtime's
# (PATH or a .NET/Java startup hook would let a build run code in every program the game starts).
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,40}$")
_SYSTEM_ENV = {"PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
               "PROGRAMFILES", "HOMEDRIVE", "HOMEPATH", "USERNAME", "PSMODULEPATH", "PROCESSOR_ARCHITECTURE"}
_RUNTIME_ENV = ("LD_", "DYLD_", "COR_", "CORECLR_", "DOTNET_STARTUP", "DOTNET_ADDITIONAL", "DOTNET_ROOT", "JAVA", "_JAVA", "JDK_", "PYTHON", "NODE_", "PERL", "RUBY")


def bad_env_name(name):
    """True when a build must not set this environment variable."""
    return (not isinstance(name, str) or not _ENV_NAME.fullmatch(name) or name in _SYSTEM_ENV or name.startswith(_RUNTIME_ENV))


_JOIN_URI = re.compile(r"^steam://[A-Za-z0-9/_.:?=&-]+$")


def valid_join_uri(uri):
    """A Steam link (steam://connect/{address}) that joins a host. {address} may appear once and nothing else may be a placeholder."""
    if not isinstance(uri, str) or len(uri) > 200 or uri.count("{address}") > 1:
        return False
    return bool(_JOIN_URI.fullmatch(uri.replace("{address}", "host")))


def is_loopback_url(url):
    h = (urlparse(url).hostname or "").lower()
    return h in ("127.0.0.1", "localhost", "::1")


def require_secure_url(url):
    """Hubs, lobbies and update servers must use HTTPS. Plain http is allowed only for a server on this same PC."""
    u = urlparse(str(url))
    if u.scheme == "https" and u.hostname:
        return url
    if u.scheme == "http" and is_loopback_url(url):
        return url
    raise ValueError("refusing to talk to %s over an insecure connection (use https)" % (u.hostname or "that address"))


def clean_text(text, limit):
    """Text from someone else (a title, an author name) made safe to show: no control or direction-override characters."""
    t = re.sub(r"[\t\r\n]+", " ", str(text if text is not None else ""))     # line breaks become a space, other controls vanish
    t = _BAD_CHARS.sub("", t)
    return re.sub(r"\s+", " ", t).strip()[:limit]


class RateLimiter:
    """Sliding-window limiter, in memory. allow(key, limit, seconds) is True while `key` is under `limit` hits in the window."""

    def __init__(self, max_keys=20000):
        self.hits, self.max_keys, self.lock = {}, max_keys, threading.Lock()

    def allow(self, key, limit, seconds):
        now = time.time()
        with self.lock:
            if len(self.hits) > self.max_keys:                       # keep memory bounded under a flood
                self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < seconds}
            q = [t for t in self.hits.get(key, []) if now - t < seconds]
            ok = len(q) < limit
            if ok:
                q.append(now)
            self.hits[key] = q
            return ok
