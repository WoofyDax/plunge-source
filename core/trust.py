"""Profiles that ship third-party binaries (DLLs/exes run by the game) need the player's explicit OK.

The OK is tied to a fingerprint of the bundled files' sha256 values, so if an update swaps a binary
the player is asked again.
"""
import hashlib

from . import settings


def binaries(meta):
    """The bundled third-party binaries a profile declares (what the validator already checks)."""
    return [{k: b.get(k) for k in ("path", "name", "author", "license", "url", "sha256")} for b in meta.get("bundled", [])]


def fingerprint(meta):
    h = hashlib.sha256()
    for sha in sorted(str(b.get("sha256", "")).lower() for b in meta.get("bundled", [])):
        h.update(sha.encode())
    return h.hexdigest()


def needs_trust(meta):
    return bool(meta.get("bundled"))


def is_trusted(slug, meta):
    if not needs_trust(meta):
        return True
    return settings.get("trusted", {}).get(slug) == fingerprint(meta)


def trust(slug, meta):
    t = dict(settings.get("trusted", {}))
    t[slug] = fingerprint(meta)
    settings.set("trusted", t)
    return {"trusted": True}
