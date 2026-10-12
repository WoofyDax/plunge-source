"""plunge://join/CODE links. Registering the handler is per-user (HKCU) and only when the player asks."""
import re
import sys
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

KEY = r"Software\Classes\plunge"


def parse(url):
    """Return the join code from 'plunge://join/CODE', or None for anything else."""
    m = re.fullmatch(r"plunge://join/([A-Za-z0-9]{4,12})/?", str(url or "").strip())
    return m.group(1).upper() if m else None


def _command():
    if getattr(sys, "frozen", False):
        return '"%s" "%%1"' % sys.executable
    pyw = Path(sys.executable).with_name("pythonw.exe")
    app = Path(__file__).resolve().parent.parent / "app.py"
    return '"%s" "%s" "%%1"' % (pyw if pyw.exists() else sys.executable, app)


def status():
    if not winreg:
        return {"registered": False, "supported": False}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY + r"\shell\open\command") as k:
            cmd, _ = winreg.QueryValueEx(k, "")
        return {"registered": cmd == _command(), "supported": True}
    except OSError:
        return {"registered": False, "supported": True}


def register():
    if not winreg:
        raise RuntimeError("only supported on Windows")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as k:
        winreg.SetValue(k, "", winreg.REG_SZ, "URL:Plunge")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY + r"\shell\open\command") as k:
        winreg.SetValue(k, "", winreg.REG_SZ, _command())
    return status()


def unregister():
    if not winreg:
        return {"registered": False}
    for sub in (r"\shell\open\command", r"\shell\open", r"\shell", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY + sub)
        except OSError:
            pass
    return status()
