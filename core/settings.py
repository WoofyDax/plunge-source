"""Tiny JSON settings store in %LOCALAPPDATA%\\Plunge\\settings.json (shared with the ads on/off switch)."""
import json

from . import paths


def _file():
    return paths.DATA / "settings.json"


def _read():
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def get(key, default=None):
    return _read().get(key, default)


def set(key, value):  # noqa: A001
    s = _read()
    s[key] = value
    _file().parent.mkdir(parents=True, exist_ok=True)
    paths.atomic_write(_file(), json.dumps(s))
    return value
