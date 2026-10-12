"""A Plunge profile is a folder: plunge.json (with a recipe) + the files the recipe installs.

It never contains the game's own content. Third-party loaders (DLLs, exes) may ship only when
declared in `bundled` with author, license, url and a matching sha256.
"""
import hashlib
import json
import re
from pathlib import Path

from . import paths, recipe

MAX_BYTES = 50 * 1024 * 1024
GAME_CONTENT_EXT = {".pak", ".ucas", ".utoc", ".uasset", ".umap", ".assets", ".bundle", ".bank", ".fsb",
                    ".wem", ".dds", ".pck", ".bsa", ".ba2", ".arc", ".wad", ".vpk", ".gcf", ".mpq"}
BINARY_EXT = {".exe", ".dll", ".sys", ".msi", ".bat", ".ps1", ".cmd", ".scr", ".so", ".dylib", ".vbs", ".jar"}
TEXT_EXT = {".json", ".txt", ".ini", ".cfg", ".md", ".lua", ".toml", ".yaml", ".yml", ".cs", ".cpp", ".h", ".py"}
SECRET_PATTERNS = [r"llc_[A-Za-z0-9_-]{16,}", r"sk-[A-Za-z0-9]{20,}", r"Bearer\s+[A-Za-z0-9._-]{16,}",
                   r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9._-]{12,}"]
REQUIRED = ["schema", "title", "tagline", "steamAppId", "engine", "tier", "author", "license",
            "comfort", "controls", "tested", "recipe"]
TIERS = {"native": "real stereo VR through the engine (UEVR, a Unity plugin...)",
         "injected": "depth/geometry-based 3D injected from outside the engine",
         "theater": "the flat game on a big virtual screen (works on anything)"}
BUNDLE_FIELDS = ("path", "name", "author", "license", "url", "sha256")


def profile_dir(slug, root=None):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,60}", slug or ""):
        raise ValueError("bad profile slug")
    return (root or paths.PROFILES) / slug


def load(slug):
    f = profile_dir(slug) / "plunge.json"
    if not f.exists():
        raise ValueError("no such profile: %s" % slug)
    return json.loads(f.read_text(encoding="utf-8-sig"))


def list_profiles(appid=None):
    paths.ensure()
    out = []
    for d in sorted(paths.PROFILES.iterdir()):
        f = d / "plunge.json"
        if f.exists():
            try:
                meta = json.loads(f.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                continue
            if appid is None or str(meta.get("steamAppId")) == str(appid):
                out.append({"slug": d.name, **meta})
    return out


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate(slug, game=None, root=None):
    """Return findings [{level, msg}]. Never raises on bad content. Pass `game` to check destinations."""
    f = []
    err = lambda m: f.append({"level": "error", "msg": m})  # noqa: E731
    warn = lambda m: f.append({"level": "warn", "msg": m})  # noqa: E731
    d = profile_dir(slug, root)
    try:
        meta = json.loads((d / "plunge.json").read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return [{"level": "error", "msg": "plunge.json is missing"}]
    except json.JSONDecodeError as e:
        return [{"level": "error", "msg": "plunge.json is not valid JSON: %s" % e}]

    for k in REQUIRED:
        if meta.get(k) in (None, "", [], {}):
            err("missing field: %s" % k)
    if meta.get("tier") and meta["tier"] not in TIERS:
        err("tier must be one of: %s" % ", ".join(TIERS))
    t = meta.get("tested") or {}
    if not t.get("minutesPlayed") or not t.get("gameVersion"):
        err("tested.minutesPlayed and tested.gameVersion must record a real play test")

    rc = meta.get("recipe") or {}
    declared = {}
    for b in meta.get("bundled", []):
        miss = [k for k in BUNDLE_FIELDS if not b.get(k)]
        if miss:
            err("bundled entry %s is missing: %s" % (b.get("path", "?"), ", ".join(miss)))
        else:
            declared[str(Path(b["path"]).as_posix())] = b

    total = 0
    for p in d.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(d).as_posix()
        total += p.stat().st_size
        ext = p.suffix.lower()
        if ext in GAME_CONTENT_EXT:
            err("%s: game content may never ship in a profile" % rel)
        elif ext in BINARY_EXT:
            b = declared.get(rel)
            if not b:
                err("%s: executables and DLLs must be declared in `bundled` (author, license, url, sha256)" % rel)
            elif _sha256(p) != b["sha256"].lower():
                err("%s: sha256 does not match the bundled entry" % rel)
        if ext in TEXT_EXT and p.stat().st_size < 512 * 1024:
            text = p.read_text(encoding="utf-8", errors="ignore")
            if any(re.search(pat, text) for pat in SECRET_PATTERNS):
                err("%s: looks like it contains a secret" % rel)
    if total > MAX_BYTES:
        err("profile is over 50 MB")

    for item in rc.get("install", []):
        src = (d / item.get("from", "")).resolve()
        if not item.get("from") or d.resolve() not in src.parents or not src.exists():
            err("recipe.install: source missing or outside the profile: %s" % item.get("from"))
        try:
            if game:
                recipe.safe_dest(item.get("to", ""), game)
            elif not str(item.get("to", "")).startswith(("{game}/", "{uevr-config}/")) or ".." in item.get("to", ""):
                err("recipe.install: bad destination %s" % item.get("to"))
        except recipe.RecipeError as e:
            err("recipe.install: %s" % e)
    if not rc.get("install") and not rc.get("runtime"):
        warn("recipe installs nothing and uses no runtime: this profile changes nothing")
    if rc.get("runtime") not in (None, "uevr"):
        err("recipe.runtime must be null or 'uevr'")
    launch = rc.get("launch") or {}
    if launch.get("mode", "steam") not in ("steam", "exe"):
        err("recipe.launch.mode must be 'steam' or 'exe'")

    pf = rc.get("prefsFile")
    if pf:
        if pf.get("format", "json") not in ("json", "ini"):
            err("recipe.prefsFile.format must be 'json' or 'ini'")
        try:
            if game:
                recipe.safe_dest(pf.get("path", ""), game)
            elif not str(pf.get("path", "")).startswith(("{game}/", "{uevr-config}/")) or ".." in pf.get("path", ""):
                err("recipe.prefsFile: bad destination %s" % pf.get("path"))
        except recipe.RecipeError as e:
            err("recipe.prefsFile: %s" % e)

    mp = rc.get("multiplayer")
    if mp:
        if not isinstance(mp.get("maxPlayers"), int) or mp["maxPlayers"] < 2:
            err("recipe.multiplayer.maxPlayers must be a whole number of at least 2")
        if not (mp.get("joinArgs") or mp.get("joinEnv") or mp.get("joinFile") or mp.get("manualJoin")):
            err("recipe.multiplayer needs joinArgs, joinEnv, joinFile, or manualJoin: true")
        if not t.get("multiplayer"):
            err("multiplayer profiles must record how hosting and joining were tested in tested.multiplayer")
        if mp.get("officialServers") is not False:
            err("recipe.multiplayer.officialServers must be false: Plunge never connects to a game's official servers")
    return f
