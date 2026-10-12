"""Which kind of VR the player uses. Detected from the active OpenXR runtime, but the player can say which."""
from . import settings

TYPES = {
    "meta-link": "Meta Quest (Link or Air Link)",
    "virtual-desktop": "Quest or Pico via Virtual Desktop",
    "steamvr": "SteamVR (Index, Vive, Pimax...)",
    "pico": "Pico (Connect / Streaming)",
    "wmr": "Windows Mixed Reality",
    "other": "Something else",
    "none": "I don't have a headset yet",
}
# runtime vendor names from api.environment() -> our type
_FROM_VENDOR = {"meta": "meta-link", "virtualdesktop": "virtual-desktop", "steamvr": "steamvr", "pico": "pico",
                "windows-mixed-reality": "wmr"}
# what to pick in UEVR's injector for each setup
_UEVR_RUNTIME = {"meta-link": "OpenXR", "virtual-desktop": "OpenXR", "pico": "OpenXR", "wmr": "OpenXR",
                 "steamvr": "OpenVR (or OpenXR)", "other": "OpenXR", "none": "OpenXR"}


def detect(vendor):
    """Best guess from the active OpenXR runtime's vendor ('meta', 'steamvr', ...), or None."""
    return _FROM_VENDOR.get(vendor)


def get():
    t = settings.get("headset")
    return t if t in TYPES else None


def set_type(t):
    if t not in TYPES:
        raise ValueError("unknown headset type: %s" % t)
    settings.set("headset", t)
    return {"type": t, "label": TYPES[t]}


def label(t):
    return TYPES.get(t, "not chosen yet")


def uevr_runtime(t):
    return _UEVR_RUNTIME.get(t, "OpenXR")


def brief_line(t, vendor):
    """One line for the AI brief so it tests with the right headset software."""
    if t == "none":
        return "- Headset: none attached (use SteamVR's null driver and say plainly it cannot prove the picture)"
    if t:
        return "- Headset: %s (active OpenXR runtime: %s)" % (TYPES[t], vendor or "unknown")
    return "- Headset: not chosen (active OpenXR runtime: %s); work it out with the environment tool" % (vendor or "unknown")
