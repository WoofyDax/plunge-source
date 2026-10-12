import os
import sys
from pathlib import Path


def _base(env, fallback):
    return Path(os.environ.get(env) or Path.home() / fallback)


DATA = _base("LOCALAPPDATA", "AppData/Local") / "Plunge"
PROFILES = DATA / "profiles"
RUNTIMES = DATA / "runtimes"
INSTALLS = DATA / "installs"
# Where UEVR keeps per-game settings. Verify against your UEVR version before trusting it.
UEVR_CONFIG_ROOT = _base("APPDATA", "AppData/Roaming") / "UnrealVRMod"


def resource(rel):
    """Path to a bundled file, both from source and from a PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


def atomic_write(path, text, encoding="utf-8"):
    """Write a file so a crash or power cut can never leave it half-written: write a temp file next to it, then swap it in.
    Used for everything Plunge must be able to read back later (settings, install records for Remove, preferences)."""
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-%d" % os.getpid())
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)                      # never leave a stray temp file, and the old file stays exactly as it was
        except OSError:
            pass
        raise


def ensure():
    for p in (PROFILES, RUNTIMES, INSTALLS):
        p.mkdir(parents=True, exist_ok=True)
