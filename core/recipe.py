"""Install, launch and uninstall a profile's recipe (the Melty 'recipe' idea, for VR layers).

A recipe maps files inside the profile folder to places inside the player's own game folder, says how
to start the game, and optionally how players host and join each other. Everything Plunge writes is
recorded in a manifest so Uninstall puts the original files back.
"""
import json
import re
import shutil
import time
from pathlib import Path

from . import launcher, paths, safety


class RecipeError(ValueError):
    pass


def manifest_path(appid):
    return paths.INSTALLS / str(appid) / "manifest.json"


def is_installed(appid):
    return manifest_path(appid).exists()


def _tokens(game):
    return {
        "{game}": game["path"],
        "{uevr-config}": str(paths.UEVR_CONFIG_ROOT / Path(game["exe"]).stem) if game.get("exe") else None,
        "{localappdata}": str(paths.DATA.parent),
    }


def resolve(template, game, extra=None):
    out = template
    for k, v in {**_tokens(game), **(extra or {})}.items():
        if k in out:
            if v is None:
                raise RecipeError("%s is not available for this game" % k)
            out = out.replace(k, str(v))
    return out


def safe_dest(template, game):
    """Destinations may only live inside the game folder or UEVR's per-game config folder."""
    if ".." in Path(template.replace("\\", "/")).parts:
        raise RecipeError("'..' is not allowed in a destination: %s" % template)
    if not (template.startswith("{game}/") or template.startswith("{uevr-config}/")):
        raise RecipeError("destination must start with {game}/ or {uevr-config}/: %s" % template)
    dest = Path(resolve(template, game)).resolve()
    roots = [Path(game["path"]).resolve()]
    if game.get("exe"):
        roots.append((paths.UEVR_CONFIG_ROOT / Path(game["exe"]).stem).resolve())
    if not any(dest == r or r in dest.parents for r in roots):
        raise RecipeError("destination escapes the game folder: %s" % template)
    return dest


def _backup(dest, backup_root, rel_key, manifest):
    if dest.exists():
        b = backup_root / rel_key
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dest, b)
        manifest["replaced"].append({"path": str(dest), "backup": str(b)})
    else:
        manifest["created"].append(str(dest))


def _same(a, b):
    """Byte-for-byte equal (size first, then content)."""
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                x, y = fa.read(1 << 20), fb.read(1 << 20)
                if x != y:
                    return False
                if not x:
                    return True
    except OSError:
        return False


def _put_file(src, dest, backup_root, manifest, counter):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and _same(src, dest):
        # an identical file is already there (for example from an earlier hand-made test install): adopt it as
        # ours, so Remove VR layer cleans it up instead of "restoring" a copy of the mod as if it were the game's own
        manifest["created"].append(str(dest))
        manifest.setdefault("adopted", []).append(str(dest))
        return
    _backup(dest, backup_root, "%04d-%s" % (counter[0], dest.name), manifest)
    counter[0] += 1
    shutil.copy2(src, dest)


def install(profile_dir, recipe, game):
    """Copy the recipe's files into the game. Safe to call again: it uninstalls first."""
    if is_installed(game["appid"]):
        uninstall(game["appid"])
    root = paths.INSTALLS / str(game["appid"])
    backup_root = root / "backup"
    manifest = {"profile": Path(profile_dir).name, "time": int(time.time()), "created": [], "replaced": []}
    counter = [0]
    try:
        for item in recipe.get("install", []):
            src = (Path(profile_dir) / item["from"]).resolve()
            if Path(profile_dir).resolve() not in src.parents or not src.exists():
                raise RecipeError("source missing or outside the profile: %s" % item["from"])
            dest = safe_dest(item["to"], game)
            if src.is_dir():
                for f in src.rglob("*"):
                    if f.is_file():
                        _put_file(f, dest / f.relative_to(src), backup_root, manifest, counter)
            else:
                _put_file(src, dest, backup_root, manifest, counter)
    except Exception:
        _write_manifest(root, manifest)
        uninstall(game["appid"])
        raise
    _write_manifest(root, manifest)
    return {"files": len(manifest["created"]) + len(manifest["replaced"])}


def _write_manifest(root, manifest):
    root.mkdir(parents=True, exist_ok=True)
    paths.atomic_write(root / "manifest.json", json.dumps(manifest, indent=1))     # Remove depends on this: never half-written


def uninstall(appid):
    mp = manifest_path(appid)
    if not mp.exists():
        return {"restored": 0, "removed": 0}
    m = json.loads(mp.read_text())
    removed = restored = 0
    for p in m["created"]:
        p = Path(p)
        if p.exists():
            p.unlink()
            removed += 1
            for parent in p.parents:  # prune folders we emptied
                try:
                    parent.rmdir()
                except OSError:
                    break
    for r in m["replaced"]:
        shutil.copy2(r["backup"], r["path"])
        restored += 1
    shutil.rmtree(mp.parent, ignore_errors=True)
    return {"restored": restored, "removed": removed}


def _fill(items, game, extra):
    return [resolve(str(i), game, extra) for i in items]


def managed_write(dest, text, appid):
    """Write a file Plunge owns inside the game, recording a backup so Uninstall can undo it."""
    mp = manifest_path(appid)
    m = json.loads(mp.read_text()) if mp.exists() else {"created": [], "replaced": [], "profile": "?", "time": int(time.time())}
    known = str(dest) in m["created"] or any(r["path"] == str(dest) for r in m["replaced"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not known:
        _backup(dest, paths.INSTALLS / str(appid) / "backup", "managed-" + dest.name, m)
    dest.write_text(text, encoding="utf-8")
    _write_manifest(paths.INSTALLS / str(appid), m)


def write_join_file(spec, game, address, appid):
    """joinFile {path, key}: put 'key=address' into a config file the game reads at start."""
    dest = safe_dest(spec["path"], game)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", str(spec.get("key", ""))):
        raise RecipeError("joinFile.key can only contain letters, digits and _ . -")
    if address and not safety.valid_address(address):          # it is written into a config file the game reads: no newlines or commands
        raise RecipeError("that address isn't valid (use host or host:port)")
    lines = dest.read_text(encoding="utf-8", errors="ignore").splitlines() if dest.exists() else []
    lines = [ln for ln in lines if not ln.startswith(spec["key"] + "=")]
    if address:
        lines.append("%s=%s" % (spec["key"], address))
    managed_write(dest, "\n".join(lines) + "\n", appid)


def write_prefs(spec, game, prefs, appid):
    """prefsFile {path, format}: hand the player's preferences to the VR build as json or key=value lines."""
    dest = safe_dest(spec["path"], game)
    if spec.get("format", "json") == "ini":
        c = prefs["comfort"]
        lines = ["perspective=%s" % prefs["perspective"], "snapTurn=%s" % str(c["snapTurn"]).lower(),
                 "vignette=%s" % str(c["vignette"]).lower(), "locomotion=%s" % c["locomotion"], "stance=%s" % c["stance"]]
        lines += ["bind.%s=%s" % (b["input"].replace(" ", "_"), b["action"]) for b in prefs["bindings"]]
        text = "\n".join(lines) + "\n"
    else:
        text = json.dumps(prefs, indent=1)
    managed_write(dest, text, appid)


def launch(game, recipe, mode="solo", address=None, port=None):
    """Start the game. mode: solo | host | join."""
    mp = recipe.get("multiplayer") or {}
    extra = {"{address}": address or "", "{port}": port or ""}
    args, env = [], {}
    if mode == "host":
        args, env = _fill(mp.get("hostArgs", []), game, extra), mp.get("hostEnv", {})
    elif mode == "join":
        if not address:
            raise RecipeError("no address to join")
        if not safety.valid_address(address):              # it goes into launch arguments: never pass anything but host[:port]
            raise RecipeError("that address isn't valid (use host or host:port)")
        args, env = _fill(mp.get("joinArgs", []), game, extra), mp.get("joinEnv", {})
        if mp.get("joinFile"):
            write_join_file(mp["joinFile"], game, address, game["appid"])
    elif mp.get("joinFile") and is_installed(game["appid"]):
        write_join_file(mp["joinFile"], game, "", game["appid"])  # solo: empty the join address
    env = {k: resolve(str(v), game, extra) for k, v in env.items()}
    spec = recipe.get("launch") or {"mode": "steam"}
    args = _fill(spec.get("args", []), game, extra) + args
    forced = str(safe_dest(spec["exe"], game)) if spec.get("mode") == "exe" else None
    try:
        res = launcher.start(game, args, env, forced_exe=forced)     # Steam games always go through Steam
    except launcher.LaunchError as e:
        raise RecipeError(str(e))
    return {"mode": mode, **res}
