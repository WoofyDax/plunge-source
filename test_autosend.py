"""Auto-send tests. They use a stand-in for the Windows calls: no test ever presses a real key."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import autosend

fails = 0


def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name)
    fails += 0 if ok else 1


def fake(window=1, front_ok=True, stays_front=True):
    log = []
    state = {"front": False}

    def bring(h):
        state["front"] = front_ok
        return front_ok
    api = types.SimpleNamespace(
        find_window=lambda p: window, bring_front=bring,
        is_front=lambda h: state["front"] and (stays_front or not log),
        paste_keys=lambda: log.append("paste"), enter_key=lambda: log.append("enter"))
    return api, log


a, log = fake(); r = autosend.run("claude-app", False, wait=1, settle=0, _api=a)
check("app open and in front: Enter only (message already filled in)", r == "sent" and log == ["enter"])
a, log = fake(); r = autosend.run("codex-app", True, wait=1, settle=0, _api=a)
check("app open and in front: paste then Enter", r == "sent" and log == ["paste", "enter"])
a, log = fake(window=None); r = autosend.run("claude-app", True, wait=1, settle=0, _api=a)
check("app not open: nothing typed", r == "app-not-found" and log == [])
a, log = fake(front_ok=False); r = autosend.run("claude-app", True, wait=1, settle=0, _api=a)
check("app can't be brought to the front: nothing typed", r == "not-in-front" and log == [])
a, log = fake(stays_front=False); r = autosend.run("claude-app", True, wait=1, settle=0, _api=a)
check("focus lost after the paste: Enter is NOT sent", r == "not-in-front" and log == ["paste"])
check("only two apps can ever be typed into", set(autosend.TARGETS) == {"claude-app", "codex-app"})
check("unknown provider has no window", autosend.find_window("vscode") is None and autosend.find_window("../x") is None)
check("a real lookup runs without error (reads window list only)", autosend.find_window("claude-app") in (None,) or isinstance(autosend.find_window("claude-app"), int))
check("key structures have the real Windows size", __import__("ctypes").sizeof(autosend._IN) in (28, 40))
sys.exit(1 if fails else 0)
