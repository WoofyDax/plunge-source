"""Everything Plunge can do, as plain functions. The window (pywebview) and the agent CLI both call these."""
import ctypes
import os
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

from . import ads, agents, autosend, stores, headset, updates, hub, launcher, legal, links, lobby, paths, prefs, profiles, prompt, recipe, runtime, scanner, settings, trust, version, vrinfo

_STATE = {"games": None, "steam": None, "demo": False, "startup_link": None}


def _load(refresh=False):
    if _STATE["games"] is None or refresh:
        res = scanner.scan_games()
        _STATE["steam"] = res["steam"]
        if res["games"]:
            _STATE.update(games=res["games"], demo=False)
            vrinfo.refresh_async([g["appid"] for g in res["games"]])
        else:
            _STATE.update(games=scanner.demo_games(), demo=True)
    return _STATE["games"]


def _with_vac(g):
    """Steam tells us (category 'Valve Anti-Cheat enabled') about anti-cheat that leaves no files to find."""
    if g.get("demo") or g["status"] == "blocked":
        return g
    if vrinfo.describe(g["appid"], g["path"]).get("vac"):
        return {**g, "anticheat": sorted(set(g["anticheat"]) | {"Valve Anti-Cheat (VAC)"}), "status": "blocked",
                "why": "Uses Valve Anti-Cheat (VAC). Plunge never touches games with anti-cheat."}
    return g


def _decorate(g):
    """Add the live facts the UI needs to a scanned game."""
    g = _with_vac(g)
    mine = profiles.list_profiles(g["appid"])
    vr = vrinfo.describe(g["appid"], g["path"])
    return {**g, "vr": vr, "installed": recipe.is_installed(g["appid"]), "profileCount": len(mine),
            "customized": bool(mine) or not prefs.is_default(prefs.get(g["appid"]))
            if not g.get("demo") else False}


def find_game(appid):
    g = next((g for g in _load() if g["appid"] == str(appid)), None)
    if not g:
        raise ValueError("unknown game: %s" % appid)
    return _with_vac(g)


def cli_prefix():
    """How an agent should call Plunge's tools from a terminal."""
    if getattr(sys, "frozen", False):
        # Plunge.exe is a windowed app and can't write to an agent's pipes: use the console twin beside it.
        return '"%s" tool' % Path(sys.executable).with_name("plunge-cli.exe")
    return '"%s" "%s" tool' % (sys.executable, paths.resource("app.py"))


# ---- reads ----------------------------------------------------------------------------------
def games(refresh=False):
    g = [_decorate(x) for x in _load(bool(refresh))]
    return {"games": g, "demo": _STATE["demo"], "steam": _STATE["steam"]}


def system():
    return {**runtime.system_status(), "hub": hub.HUB_URL, "lobby": lobby.LOBBY_URL, "version": version.VERSION,
            "links": links.status(), "headset": headset_info()}


def _flag_profile(p, game):
    """Safety facts the UI shows before a profile is run: bundled binaries, and a game that updated since testing."""
    built = (p.get("tested") or {}).get("buildId")
    now = game.get("buildId")
    return {**p, "binaries": trust.binaries(p), "trusted": trust.is_trusted(p["slug"], p),
            "stale": bool(built and now and str(built) != str(now)), "builtFor": built, "currentBuild": now}


def game_info(appid):
    g = _decorate(find_game(appid))
    return {**g, "profiles": [_flag_profile(p, g) for p in profiles.list_profiles(g["appid"])],
            "profileRoot": str(paths.PROFILES), "preferences": prefs.get(g["appid"])}


def trust_profile(slug):
    return trust.trust(slug, profiles.load(slug))


# ---- app shell: links, first run, legal ------------------------------------------------------
def set_startup_link(url):
    _STATE["startup_link"] = links.parse(url)


def forward_link(url):
    """A second Plunge was started with a join link: leave it for the running one to pick up (it asks before joining)."""
    code = links.parse(url)
    if code:
        paths.atomic_write(paths.DATA / "pending_link.txt", code)


def startup_link():
    """A join code waiting to be confirmed, from this launch or from a second launch, or None. Read once."""
    code, _STATE["startup_link"] = _STATE["startup_link"], None
    pending = paths.DATA / "pending_link.txt"
    if not code and pending.exists():
        try:
            code = links.parse("plunge://join/" + pending.read_text(encoding="utf-8").strip())
            pending.unlink()
        except OSError:
            code = None
    return {"code": code}


def register_links(on):
    return links.register() if on else links.unregister()


def onboarded(done=None):
    if done:
        settings.set("onboarded", True)
    return {"done": bool(settings.get("onboarded", False))}


def open_legal(name):
    return legal.open_doc(name)


def search_profiles(appid=None):
    return {"profiles": profiles.list_profiles(appid)}


def local_builds():
    """Everything in the profiles folder, for the 'Publish a build' window: finished builds (with their problems, if any) and
    unfinished folders that have no plunge.json (an agent that stopped before saving)."""
    paths.ensure()
    out, incomplete = [], []
    for d in sorted(paths.PROFILES.iterdir()):
        if not d.is_dir():
            continue
        if not (d / "plunge.json").exists():
            incomplete.append(d.name)
            continue
        try:
            meta = profiles.load(d.name)
        except (ValueError, OSError):
            incomplete.append(d.name)
            continue
        findings = profiles.validate(d.name)
        errs = [f["msg"] for f in findings if f["level"] == "error"]
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        out.append({"slug": d.name, "title": meta.get("title") or d.name, "tier": meta.get("tier"), "steamAppId": meta.get("steamAppId"),
                    "errors": errs[:4], "ready": not errs, "mb": round(size / 1048576, 1)})
    return {"profiles": out, "incomplete": incomplete}


def preferences(appid):
    return prefs.get(appid)


def validate_profile(slug, appid=None):
    game = find_game(appid) if appid else None
    if game is None:
        meta = profiles.load(slug)
        game = next((g for g in _load() if g["appid"] == str(meta.get("steamAppId"))), None)
    findings = profiles.validate(slug, game)
    return {"ok": not any(f["level"] == "error" for f in findings), "findings": findings}


def profile_dir(slug):
    return {"path": str(profiles.profile_dir(slug))}


def make_prompt(appid):
    g = find_game(appid)
    p = prefs.get(appid)
    return {"prompt": prompt.build(g, cli_prefix(), paths.PROFILES, prefs.brief_text(p),
                                   vrinfo.describe(appid, g["path"]), p["interview"],
                                   headset.brief_line(headset.get(), environment_vendor()))}


def input_choices():
    return {"inputs": prefs.INPUTS, "perspectives": prefs.PERSPECTIVES, "locomotion": list(prefs.LOCOMOTION),
            "stance": list(prefs.STANCE)}


# ---- preferences ----------------------------------------------------------------------------
def get_prefs(appid):
    find_game(appid)
    return prefs.get(appid)


def save_prefs(appid, p):
    find_game(appid)
    return prefs.save(appid, p)


# ---- sponsored cards ------------------------------------------------------------------------
def ad():
    return {"ad": ads.public(ads.current()), **ads.status()}


def ad_seen(ad_id):
    return ads.seen(ad_id)


def ad_click(ad_id):
    return ads.click(ad_id)


def ads_enable(on):
    return ads.set_enabled(on)


# ---- discover / hub -------------------------------------------------------------------------
def discover():
    """Sections for the Discover page. Hub sections need the hub; local sections never do."""
    out = {"featured": [], "released": [], "popular": [], "hubError": None}
    try:
        out["featured"] = hub.browse("featured")
        out["released"] = hub.browse("new")
        out["popular"] = hub.browse("popular")
    except hub.HubError as e:
        out["hubError"] = str(e)
    mine = {p["slug"] for p in profiles.list_profiles()}
    for sec in ("featured", "released", "popular"):
        for r in out[sec]:
            r["owned"] = r["id"] in mine
    return out


def discover_search(text):
    rows = hub.browse("new", text=text)
    mine = {p["slug"] for p in profiles.list_profiles()}
    for r in rows:
        r["owned"] = r["id"] in mine
    return rows


def get_profile(pid):
    r = hub.get(pid)
    return {**r, "meta": profiles.load(r["slug"])}


def publish(slug):
    return hub.publish(slug)


def like(pid):
    return hub.like(pid)


# ---- account ----------------------------------------------------------------------------------
def account():
    """Who is signed in (no network call): {"user": {...}|None}."""
    return {"user": hub.account()}


def account_check():
    """Ask the hub whether the saved sign-in is still good."""
    try:
        return {"user": hub.me()}
    except hub.HubError as e:
        return {"user": hub.account(), "offline": str(e)}      # offline: keep showing who was signed in


def sign_in_start(email):
    return hub.sign_in_start(email)


def sign_in_verify(email, code, username=None, password=None):
    return hub.sign_in_verify(email, code, username, password)


def password_sign_in(email, password):
    return hub.password_sign_in(email, password)


def auth_config():
    return hub.config()


def google_start():
    return hub.google_start()


def google_poll():
    return hub.google_poll()


def set_password(new, current=None):
    return hub.set_password(new, current)


def rename_account(username):
    return hub.rename(username)


def sign_out():
    return hub.sign_out()


def my_builds():
    return {"profiles": hub.my_profiles()}


def remove_build(pid):
    return hub.remove(pid)


def delete_account():
    return hub.delete_account()


# ---- actions --------------------------------------------------------------------------------
def install_runtime():
    return runtime.install_uevr()


def _ready(game, modify=True):
    """Games with anti-cheat are never modified. Starting one that already has official VR support, exactly as it
    ships (nothing installed, nothing injected), is the same thing Steam's own Play button does, so that is allowed."""
    if game.get("demo"):
        raise ValueError("Demo library entry: install Steam games to launch")
    if game["status"] == "blocked":
        if not modify and vrinfo.describe(game["appid"], game["path"])["level"]:
            return
        raise ValueError(game["why"])


def play(appid, slug=None, mode="solo", address=None, port=None):
    game = find_game(appid)
    native_vr = vrinfo.describe(appid, game["path"])["level"]
    _ready(game, modify=bool(slug) or not native_vr)        # a profile or injector always needs a game without anti-cheat
    steps, rc = [], {}
    if slug:
        v = validate_profile(slug, appid)
        if not v["ok"]:
            raise ValueError("profile failed validation: " + v["findings"][0]["msg"])
        meta = profiles.load(slug)
        if not trust.is_trusted(slug, meta):
            raise ValueError("TRUST_REQUIRED: this build ships third-party programs that will run with the game. Review and allow them first.")
        rc = meta.get("recipe") or {}
        if rc.get("install"):
            steps.append("Installed %d files" % recipe.install(profiles.profile_dir(slug), rc, game)["files"])
        if rc.get("prefsFile"):
            recipe.write_prefs(rc["prefsFile"], game, prefs.effective(prefs.get(appid)), appid)
            steps.append("Applied your preferences")
    elif native_vr:
        steps.append("This game has built-in VR support")
    elif game["route"]["id"] != "uevr":
        raise ValueError("This game needs a VR profile first")
    runtime_id = rc.get("runtime") or ("uevr" if not slug and not native_vr and game["route"]["id"] == "uevr" else None)
    if runtime_id == "uevr" and not runtime.find_injector():
        raise ValueError("UEVR is not installed yet")
    res = recipe.launch(game, rc, mode, address, port)      # raises with Steam's own reason if Steam refuses
    steps.append("Started the game" if res.get("started") else
                 "Asked %s to start the game. It hasn't confirmed yet (it may still be signing in or loading)" % ("Steam" if res.get("how") == "steam" else "the launcher"))
    if runtime_id == "uevr":
        subprocess.Popen([str(runtime.find_injector())], cwd=str(runtime.find_injector().parent))
        steps.append("Opened the UEVR injector: pick the game, choose %s as the runtime, and press Inject"
                     % headset.uevr_runtime(headset.get()))
    return {"steps": steps}


def uninstall(appid):
    lobby.close_lobby(appid)
    return recipe.uninstall(appid)


# ---- agent tools: test a build exactly the way Play installs and starts it --------------------
def install_profile(slug, appid):
    """Install a profile's files (and the player's preferences) into the game, tracked so it can be removed cleanly."""
    game = find_game(appid)
    _ready(game)                                       # never install into a game with anti-cheat, not even for an agent's test
    v = validate_profile(slug, appid)
    if not v["ok"]:
        raise ValueError("profile failed validation: " + v["findings"][0]["msg"])
    rc = profiles.load(slug).get("recipe") or {}
    n = recipe.install(profiles.profile_dir(slug), rc, game)["files"] if rc.get("install") else 0
    if rc.get("prefsFile"):
        recipe.write_prefs(rc["prefsFile"], game, prefs.effective(prefs.get(appid)), appid)
    return {"installed": n, "note": "Tracked by Plunge: uninstall_profile %s restores the game exactly." % appid}


def uninstall_profile(appid):
    return uninstall(appid)


def launch_game(appid):
    """Start the game (Steam games go through Steam) and report whether it really started."""
    game = find_game(appid)
    _ready(game)                                           # agents test builds, which is modifying: no anti-cheat games
    try:
        res = launcher.start(game)
    except launcher.LaunchError as e:
        raise ValueError(str(e))
    return {"started": res["started"], "how": res["how"]}


_HEADSET_PROCS = {"meta": ("OVRServer_x64.exe", "OculusClient.exe"), "steamvr": ("vrserver.exe", "vrmonitor.exe"),
                  "virtualdesktop": ("VirtualDesktop.Streamer.exe",), "pico": ("PICO Connect.exe", "PicoLink.exe")}


def environment():
    """What an agent needs to know before testing in VR: active runtime, running headset software, installed tools."""
    xr = runtime.openxr_runtime()
    vendor = environment_vendor()
    try:
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=10).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        out = ""
    running = [k for k, names in _HEADSET_PROCS.items() if any(n.lower() in out for n in names)]
    tools = {}
    for name in ("dotnet", "ilspycmd", "python", "git", "gh", "node"):
        tools[name] = shutil.which(name)
    sdks = ""
    if tools["dotnet"]:
        try:
            sdks = subprocess.run(["dotnet", "--list-sdks"], capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return {"openxrRuntime": xr, "activeRuntimeVendor": vendor, "headsetSoftwareRunning": running,
            "tools": tools, "dotnetSdks": sdks.splitlines(), "steam": {"running": "steam.exe" in out, "path": launcher.steam_exe()},
            "advice": ("Match your test to the active OpenXR runtime (%s). Do not start SteamVR if the active runtime is Meta, "
                       "and never switch the runtime yourself: that is a system change, ask the player." % vendor)}


# ---- game folders the player adds ---------------------------------------------------------------
def game_folders():
    return {"folders": settings.get("gameFolders", [])}


def add_game_folder(path):
    p = Path(str(path)).expanduser()
    if not p.is_dir():
        raise ValueError("that folder doesn't exist: %s" % path)
    before = len(_load())                       # count first, so "found" really means new
    cur = list(settings.get("gameFolders", []))
    if str(p.resolve()) not in cur:
        cur.append(str(p.resolve()))
        settings.set("gameFolders", cur)
    _load(True)
    return {"folders": cur, "found": len(_load()) - before}


def remove_game_folder(path):
    settings.set("gameFolders", [f for f in settings.get("gameFolders", []) if f != path])
    _load(True)
    return {"folders": settings.get("gameFolders", [])}


def host(appid, slug, public=False, address=None):
    game = find_game(appid)
    _ready(game)
    meta = profiles.load(slug)
    mp = (meta.get("recipe") or {}).get("multiplayer")
    if not mp:
        raise ValueError("this profile has no multiplayer setup")
    lobby._call("/lobbies")  # fail early if the lobby service is unreachable
    port = 25000 + (zlib.crc32(str(game["appid"]).encode()) % 1000)
    play(appid, slug, "host", None, port)
    spec = mp.get("address")
    addr = address or (lobby.find_address(spec, game) if spec else None)
    if not addr:
        return {"needAddress": True}
    return {"code": lobby.open_lobby(appid, slug, meta["title"], mp["maxPlayers"], addr, public)["code"], "address": addr}


def publish_lobby(appid, slug, address, public=False):
    meta = profiles.load(slug)
    mp = meta["recipe"]["multiplayer"]
    return lobby.open_lobby(appid, slug, meta["title"], mp["maxPlayers"], address, public)


def join(code):
    info = lobby.resolve(code)
    find_game(info["appid"])  # the joiner must own the game
    if info["profile"] not in [p["slug"] for p in profiles.list_profiles(info["appid"])]:
        raise ValueError("you need the profile '%s' to join this game" % info["profile"])
    return play(info["appid"], info["profile"], "join", info["address"])


def lobbies(appid=None):
    return {"lobbies": lobby.list_open(appid)}


def stop_hosting(appid):
    return lobby.close_lobby(appid)


def copy_text(text):
    """Put text on the Windows clipboard (works even when the web view blocks navigator.clipboard)."""
    k, u = ctypes.windll.kernel32, ctypes.windll.user32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    data = (text + "\0").encode("utf-16-le")
    h = k.GlobalAlloc(0x0002, len(data))
    p = k.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    k.GlobalUnlock(h)
    if not u.OpenClipboard(None):
        raise RuntimeError("clipboard is busy")
    try:
        u.EmptyClipboard()
        u.SetClipboardData(13, h)  # CF_UNICODETEXT
    finally:
        u.CloseClipboard()
    return {"ok": True}


# ---- headset -------------------------------------------------------------------------------------
def headset_info():
    env_vendor = environment_vendor()
    chosen = headset.get()
    detected = headset.detect(env_vendor)
    return {"type": chosen, "detected": detected, "label": headset.label(chosen or detected),
            "choices": [{"id": k, "label": v} for k, v in headset.TYPES.items()], "vendor": env_vendor}


def set_headset(t):
    headset.set_type(t)
    return headset_info()


def environment_vendor():
    xr = runtime.openxr_runtime()
    low = (xr or "").lower()
    return ("meta" if "oculus" in low or "meta" in low else "steamvr" if "steamxr" in low or "steamvr" in low
            else "virtualdesktop" if "virtualdesktop" in low else "pico" if "pico" in low else
            "windows-mixed-reality" if "mixedreality" in low or "wmr" in low else "unknown" if xr else "none")


# ---- scanning help --------------------------------------------------------------------------------
def scan_report():
    return {"rows": [{"label": a, "value": b} for a, b in scanner.report()], "games": len(_load())}


def deep_scan(seconds=150, depth=4):
    """Look through every drive for game engines. Started on purpose by the player. depth 4 takes seconds; depth 6
    reaches games buried in nested folders but can take a minute or two."""
    before = len(_load())
    r = stores.deep_scan(max_seconds=min(max(int(seconds), 5), 300), max_depth=min(max(int(depth), 2), 8))
    _load(True)
    return {**r, "newGames": len(_load()) - before}


# ---- send the brief to the player's own AI agent -------------------------------------------------------
def agents_detect():
    return {"agents": agents.detect(), "saved": settings.get("agent")}


def _agent_plan(appid, provider, model, effort, game_access):
    game = find_game(appid)
    _ready(game)                                          # a build can't be made for a game with anti-cheat
    if provider not in agents.PROVIDERS:
        raise ValueError("unknown agent: %s" % provider)
    exe = agents.find_provider(provider)[0]
    if not exe:
        raise ValueError("%s isn't installed on this PC" % agents.PROVIDERS[provider]["name"])
    slug = prompt.slugify(game["name"])
    workdir = paths.DATA / "agent" / slug
    add = [str(paths.PROFILES / slug)] + ([game["path"]] if game_access and game.get("path") and game["path"] != "(demo)" else [])
    (paths.PROFILES / slug).mkdir(parents=True, exist_ok=True)
    args, notes = agents.build_command(provider, exe, model, effort, add, workdir)
    return game, slug, workdir, args, notes


def agent_preview(appid, provider, model="default", effort="default", game_access=True):
    """What would run, without running or writing anything (the player sees this before pressing Start)."""
    _, _, workdir, args, notes = _agent_plan(appid, provider, model, effort, bool(game_access))
    return {"command": agents.display(args), "folder": str(workdir), "notes": notes, "mode": agents.PROVIDERS[provider]["mode"]}


def agent_start(appid, provider, model="default", effort="default", game_access=True, auto_send=True):
    game, slug, workdir, args, notes = _agent_plan(appid, provider, model, effort, bool(game_access))
    agents.write_brief(slug, make_prompt(appid)["prompt"])
    mode = agents.PROVIDERS[provider]["mode"]
    pasted = False
    if mode in ("paste", "app-paste", "editor"):
        copy_text(agents.FIRST_MESSAGE)
        pasted = True
    if mode.startswith("app"):
        agents.launch_app(provider, args)
    elif mode == "editor":
        agents.launch_editor(args)
    sent = None
    if auto_send and provider in autosend.TARGETS:           # checks the app is open and in front before it types anything
        sent = autosend.run(provider, paste=(mode == "app-paste"))
        if sent == "sent":
            pasted = False
    else:
        agents.launch(args, workdir)
    settings.set("agent", {"provider": provider, "model": model or "default", "effort": effort or "default", "gameAccess": bool(game_access)})
    return {"started": True, "mode": mode, "pasted": pasted, "sent": sent, "notes": notes, "folder": str(workdir)}


def open_url(url):
    """Open a page in the browser, but only the official install/pricing pages Plunge itself lists (the web page can't pick URLs)."""
    allowed = {u for pr in agents.PROVIDERS.values() for u in (pr["install"], pr["plans"])}
    if url not in allowed:
        raise ValueError("that link isn't one Plunge opens")
    os.startfile(url)
    return {"ok": True}


# ---- production helpers ------------------------------------------------------------------------------------
def update_check():
    return updates.check()


def open_update():
    return updates.open_download()


def open_logs():
    from . import log
    log.log_dir().mkdir(parents=True, exist_ok=True)
    os.startfile(str(log.log_dir()))
    return {"ok": True}
