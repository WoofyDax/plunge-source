"""Per-game player preferences: perspective, controller bindings, comfort, free-form wishes.

They feed two places: the AI brief (so the build honours them) and, when a profile declares
recipe.prefsFile, a config file Plunge writes into the game at launch.
"""
import json
import re

from . import paths

PERSPECTIVES = {"auto": "Let the VR build decide", "first": "Always first person", "third": "Keep third person"}
INPUTS = ["Left trigger", "Right trigger", "Left grip", "Right grip", "Left thumbstick click", "Right thumbstick click",
          "Left thumbstick up", "Left thumbstick down", "Left thumbstick left", "Left thumbstick right",
          "Right thumbstick up", "Right thumbstick down", "Right thumbstick left", "Right thumbstick right",
          "A", "B", "X", "Y", "Left menu", "Right menu (system)"]
LOCOMOTION = ("smooth", "teleport", "room-scale only")
STANCE = ("seated", "standing")

DEFAULTS = {"perspective": "auto",
            "comfort": {"snapTurn": True, "vignette": True, "locomotion": "smooth", "stance": "seated"},
            "bindingsMode": "auto", "bindings": [], "notes": "", "interview": "skip"}


def _file(appid):
    return paths.DATA / "prefs" / ("%s.json" % re.sub(r"[^A-Za-z0-9_-]", "_", str(appid)))


def clean(p):
    """Validate untrusted input from the UI into a well-formed preferences dict."""
    p = p if isinstance(p, dict) else {}
    c = p.get("comfort") if isinstance(p.get("comfort"), dict) else {}
    out = {
        "perspective": p.get("perspective") if p.get("perspective") in PERSPECTIVES else "auto",
        "comfort": {
            "snapTurn": bool(c.get("snapTurn", True)),
            "vignette": bool(c.get("vignette", True)),
            "locomotion": c.get("locomotion") if c.get("locomotion") in LOCOMOTION else "smooth",
            "stance": c.get("stance") if c.get("stance") in STANCE else "seated",
        },
        "bindingsMode": "custom" if p.get("bindingsMode") == "custom" else "auto",
        "bindings": [],
        "notes": str(p.get("notes", ""))[:2000],
        "interview": "ask" if p.get("interview") == "ask" else "skip",   # skip = the agent just builds, using defaults
    }
    seen = set()
    for b in (p.get("bindings") or [])[:40]:
        if isinstance(b, dict) and b.get("input") in INPUTS and str(b.get("action", "")).strip():
            if b["input"] in seen:
                continue  # one action per input
            seen.add(b["input"])
            out["bindings"].append({"input": b["input"], "action": str(b["action"]).strip()[:80]})
    return out


def get(appid):
    try:
        return clean(json.loads(_file(appid).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return clean({})


def save(appid, prefs):
    p = clean(prefs)
    f = _file(appid)
    f.parent.mkdir(parents=True, exist_ok=True)
    paths.atomic_write(f, json.dumps(p, indent=1))
    return p


def effective(p):
    """What actually applies: custom bindings only count when the player switched to custom controls."""
    p = clean(p)
    return {**p, "bindings": p["bindings"] if p["bindingsMode"] == "custom" else []}


def is_default(p):
    """True when the player changed nothing that affects the build (how the agent is briefed doesn't count)."""
    a, b = effective(p), clean({})
    a.pop("interview", None), b.pop("interview", None)
    return a == b


def brief_text(p):
    """The preferences as a block for the agent brief ('' when the player changed nothing)."""
    p = effective(p)
    if is_default(p):
        return ""
    lines = ["Player preferences (these are requirements, not suggestions):",
             "- Perspective: %s" % PERSPECTIVES[p["perspective"]],
             "- Comfort: snap turn %s, vignette %s, locomotion %s, %s" % (
                 "on" if p["comfort"]["snapTurn"] else "off", "on" if p["comfort"]["vignette"] else "off",
                 p["comfort"]["locomotion"], p["comfort"]["stance"])]
    if p["bindingsMode"] == "auto":
        lines.append("- Controller bindings: the VR build decides the best mapping")
    for b in p["bindings"]:
        lines.append("- Controller binding: %s -> %s" % (b["input"], b["action"]))
    if p["notes"].strip():
        lines.append("- In the player's words: %s" % p["notes"].strip())
    lines.append("If a preference cannot be done in this game, say so in one line and do the closest thing. "
                 "Expose each of these as a setting the build reads at start, and list what the build supports under plunge.json \"options\".")
    return "\n".join(lines)
