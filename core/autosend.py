"""Press Ctrl+V and Enter in a desktop AI app for the player, but only when that app's window is really there and in front.

Plunge types into another program here, so it is deliberately careful:
  * it only ever targets a window owned by a process that runs from the app's own install folder (not a title match);
  * it brings that window to the front and checks that it IS in front before every key press, and stops if anything else is;
  * it sends exactly two things: Ctrl+V (the one-line message already on the clipboard) and Enter. Nothing else, ever.
If any check fails it sends nothing and the player does the paste themselves.
"""
import ctypes
import time
from ctypes import wintypes

# the install folders of the apps Plunge may type into (lower-case fragments of the owning process's path)
TARGETS = {"claude-app": "\\windowsapps\\claude_", "codex-app": "\\windowsapps\\openai.codex_"}

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None
VK_CONTROL, VK_V, VK_RETURN, VK_MENU = 0x11, 0x56, 0x0D, 0x12
KEYUP, INPUT_KEYBOARD = 0x0002, 1


def _exe_of(pid):
    h = kernel32.OpenProcess(0x1000, False, pid)              # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        return buf.value.lower() if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        kernel32.CloseHandle(h)


def find_window(provider):
    """The main window (handle) of the app, or None when it isn't open."""
    frag = TARGETS.get(provider)
    if not frag or not user32:
        return None
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4) and user32.GetWindowTextLengthW(hwnd) > 0:   # 4 = owner
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if frag in _exe_of(pid.value):
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                found.append(((rect.right - rect.left) * (rect.bottom - rect.top), hwnd))
        return True
    user32.EnumWindows(each, 0)
    return max(found)[1] if found else None


def is_front(hwnd):
    return bool(hwnd) and user32.GetForegroundWindow() == hwnd


def bring_front(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)                            # restore
    user32.keybd_event(VK_MENU, 0, 0, 0)                      # a tap of Alt lets this process take the foreground
    user32.keybd_event(VK_MENU, 0, KEYUP, 0)
    user32.SetForegroundWindow(hwnd)
    for _ in range(10):
        if is_front(hwnd):
            return True
        time.sleep(0.15)
    return False


class _KI(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _MI(ctypes.Structure):                                  # only here so the union has its real size
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("d", wintypes.DWORD), ("f", wintypes.DWORD), ("t", wintypes.DWORD), ("x", ctypes.c_size_t)]


class _IN(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KI), ("mi", _MI)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _key(vk, up=False):
    i = _IN(type=INPUT_KEYBOARD)
    i.ki = _KI(wVk=vk, dwFlags=KEYUP if up else 0)
    return i


def _send(*keys):
    arr = (_IN * len(keys))(*keys)
    return user32.SendInput(len(keys), arr, ctypes.sizeof(_IN)) == len(keys)


def paste_keys():
    return _send(_key(VK_CONTROL), _key(VK_V), _key(VK_V, True), _key(VK_CONTROL, True))


def enter_key():
    return _send(_key(VK_RETURN), _key(VK_RETURN, True))


def run(provider, paste, wait=30, settle=4.0, _api=None):
    """Wait for the app, check it is in front, then paste (if `paste`) and press Enter.
    Returns "sent", "app-not-found", or "not-in-front". `_api` lets tests replace the Windows calls."""
    a = _api or __import__(__name__, fromlist=["x"])
    end = time.time() + wait
    hwnd = None
    while time.time() < end and not hwnd:                     # 1. is the app open?
        hwnd = a.find_window(provider)
        if not hwnd:
            time.sleep(0.5)
    if not hwnd:
        return "app-not-found"
    time.sleep(settle)                                        # let its window finish drawing and focus its text box
    if not a.bring_front(hwnd) or not a.is_front(hwnd):       # 2. is it in front?
        return "not-in-front"
    if paste:
        a.paste_keys()
        time.sleep(0.6)
        if not a.is_front(hwnd):                              # 3. still in front? otherwise the Enter could go elsewhere
            return "not-in-front"
    a.enter_key()
    return "sent"
