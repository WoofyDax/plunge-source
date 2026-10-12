"""Plunge: any game, in VR. Desktop app (native window), plus an agent CLI and a lobby service.

    Plunge.exe                  open the app
    Plunge.exe tool <name> ...  agent tools (prints JSON): game_info, search_profiles, validate_profile, profile_dir,
                                preferences, environment, install_profile, uninstall_profile, launch_game
    Plunge.exe lobby            run the multiplayer lobby service
    Plunge.exe hub              run the community hub (Discover uploads)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # so `core` imports work from any cwd


_MUTEXES = []


def _attach_console():
    """The windowed exe has no console; borrow the parent terminal for CLI output."""
    if getattr(sys, "frozen", False):
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8")
            sys.stderr = sys.stdout


def run_tool(argv):
    from core import api, paths
    paths.ensure()
    tools = {"game_info": api.game_info, "search_profiles": api.search_profiles,
             "validate_profile": api.validate_profile, "profile_dir": api.profile_dir,
             "preferences": api.preferences, "environment": api.environment, "install_profile": api.install_profile,
             "uninstall_profile": api.uninstall_profile, "launch_game": api.launch_game,
             "list_games": lambda: api.games()}
    if not argv or argv[0] not in tools:
        print(json.dumps({"error": "tools: " + ", ".join(tools)}))
        return 2
    try:
        print(json.dumps(tools[argv[0]](*argv[1:]), indent=1))
        return 0
    except (ValueError, TypeError) as e:
        print(json.dumps({"error": str(e)}))
        return 1


class Bridge:
    """The methods the UI may call. Thin wrappers so errors reach JS as {error}."""

    def __init__(self):
        from core import api
        self._api = api

    def pick_game_folder(self):
        """Native folder picker, then add the chosen folder to the scan."""
        import webview
        try:
            chosen = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
            if not chosen:
                return {"cancelled": True}
            return self._api.add_game_folder(chosen[0])
        except Exception as e:
            return {"error": str(e)}

    def _wrap(name):  # noqa: N805
        def call(self, *a):
            from core import log
            try:
                return getattr(self._api, name)(*a)
            except (ValueError, RuntimeError, OSError) as e:      # expected problems: shown to the user as a toast
                log.LOGGER.info("%s: %s", name, e)
                return {"error": str(e)}
            except Exception as e:                                  # a bug: keep the stack trace in the log
                log.LOGGER.exception("%s crashed", name)
                return {"error": "Something went wrong (%s). Details are in the log." % type(e).__name__}
        call.__name__ = name
        return call

    games = _wrap("games")
    system = _wrap("system")
    game_info = _wrap("game_info")
    profiles = _wrap("search_profiles")
    validate = _wrap("validate_profile")
    prompt = _wrap("make_prompt")
    install_runtime = _wrap("install_runtime")
    play = _wrap("play")
    uninstall = _wrap("uninstall")
    host = _wrap("host")
    publish_lobby = _wrap("publish_lobby")
    stop_hosting = _wrap("stop_hosting")
    join = _wrap("join")
    lobbies = _wrap("lobbies")
    copy_text = _wrap("copy_text")
    agents_detect = _wrap("agents_detect")
    agent_preview = _wrap("agent_preview")
    agent_start = _wrap("agent_start")
    open_url = _wrap("open_url")
    headset_info = _wrap("headset_info")
    set_headset = _wrap("set_headset")
    scan_report = _wrap("scan_report")
    deep_scan = _wrap("deep_scan")
    game_folders = _wrap("game_folders")
    add_game_folder = _wrap("add_game_folder")
    remove_game_folder = _wrap("remove_game_folder")
    trust_profile = _wrap("trust_profile")
    startup_link = _wrap("startup_link")
    register_links = _wrap("register_links")
    onboarded = _wrap("onboarded")
    open_legal = _wrap("open_legal")
    ad = _wrap("ad")
    ad_seen = _wrap("ad_seen")
    ad_click = _wrap("ad_click")
    ads_enable = _wrap("ads_enable")
    discover = _wrap("discover")
    discover_search = _wrap("discover_search")
    get_profile = _wrap("get_profile")
    publish = _wrap("publish")
    like = _wrap("like")
    input_choices = _wrap("input_choices")
    get_prefs = _wrap("get_prefs")
    save_prefs = _wrap("save_prefs")
    local_builds = _wrap("local_builds")
    account = _wrap("account")
    account_check = _wrap("account_check")
    sign_in_start = _wrap("sign_in_start")
    sign_in_verify = _wrap("sign_in_verify")
    password_sign_in = _wrap("password_sign_in")
    auth_config = _wrap("auth_config")
    google_start = _wrap("google_start")
    google_poll = _wrap("google_poll")
    set_password = _wrap("set_password")
    rename_account = _wrap("rename_account")
    sign_out = _wrap("sign_out")
    my_builds = _wrap("my_builds")
    remove_build = _wrap("remove_build")
    delete_account = _wrap("delete_account")
    update_check = _wrap("update_check")
    open_update = _wrap("open_update")
    open_logs = _wrap("open_logs")


def _single_instance(name="Local\\PlungeSingleInstance"):
    """True if this is the only Plunge running. Two copies could change the same game folder at the same time."""
    import ctypes
    k = ctypes.windll.kernel32
    _MUTEXES.append(k.CreateMutexW(None, False, name))               # kept alive for the life of the process
    return k.GetLastError() != 183                                    # 183 = ERROR_ALREADY_EXISTS


def _focus_existing():
    import ctypes
    u = ctypes.windll.user32
    h = u.FindWindowW(None, "Plunge")
    if h:
        u.ShowWindow(h, 9)                                            # restore if minimized
        u.SetForegroundWindow(h)


def run_app(link=None):
    import webview
    from core import api, log, paths
    paths.ensure()
    log.setup()
    if not _single_instance():
        if link:
            api.forward_link(link)                                    # the running copy picks it up and asks before joining
        _focus_existing()
        return
    log.LOGGER.info("Plunge %s starting", __import__("core.version", fromlist=["VERSION"]).VERSION)
    # Inline the UI into one page so no local web server is started: the app listens on no port.
    ui = paths.resource("ui")
    page = (ui / "index.html").read_text(encoding="utf-8")
    import base64
    font = base64.b64encode((ui / "fonts" / "inter.woff2").read_bytes()).decode()
    css = (ui / "style.css").read_text(encoding="utf-8").replace("url(fonts/inter.woff2)", "url(data:font/woff2;base64,%s)" % font)
    page = page.replace('<link rel="stylesheet" href="style.css">', "<style>%s</style>" % css)
    page = page.replace('<script src="app.js"></script>',
                        "<script>%s</script>" % (ui / "app.js").read_text(encoding="utf-8"))
    webview.create_window("Plunge", html=page, js_api=Bridge(),
                          width=1280, height=800, min_size=(960, 640), background_color="#141414")
    webview.start()


def main():
    argv = sys.argv[1:]
    if argv[:1] == ["tool"]:
        _attach_console()
        sys.exit(run_tool(argv[1:]))
    if argv[:1] == ["lobby"]:
        _attach_console()
        from core import lobby_server
        port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8787
        bind = argv[argv.index("--bind") + 1] if "--bind" in argv else "127.0.0.1"
        lobby_server.serve(port, bind)
        return
    if argv[:1] == ["hub"]:
        _attach_console()
        from core import hub_server
        port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8788
        bind = argv[argv.index("--bind") + 1] if "--bind" in argv else "127.0.0.1"
        data = argv[argv.index("--data") + 1] if "--data" in argv else None
        hub_server.serve(port, bind, data)
        return
    if argv[:1] in (["--version"], ["-v"]):
        _attach_console()
        from core.version import VERSION
        print("Plunge " + VERSION)
        return
    link = argv[0] if argv and argv[0].lower().startswith("plunge://") else None
    if link:
        from core import api
        api.set_startup_link(link)      # only a well-formed plunge://join/CODE is kept; the UI asks before joining
    run_app(link)


if __name__ == "__main__":
    main()
