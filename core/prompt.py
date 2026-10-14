"""Builds the 'Create VR build' prompt that gets copied to the clipboard (the Melty pattern).

Written to make the player's life simple: by default the agent does not interview them, it checks the
environment itself, tests the way Play installs, and cleans up after itself.
"""

ENGINE_HINTS = {
    "unreal": "Unreal Engine. Fast first pass: UEVR (github.com/praydog/UEVR, Unreal 4.8 to 5.4) gives real stereo VR. Set recipe.runtime to \"uevr\" and put its per-game config in the profile. Then redesign what UEVR cannot fix (HUD, aiming, cutscenes, hands) with its plugin system and UObjectHook (see the engine cards below).",
    "unity": "Unity. Use BepInEx plus UnityVRMod (OpenXR) for the camera rig and stereo rendering, and write your own plugin for hands, aiming, HUD and comfort. See the Unity cards below: check whether the game is Mono or IL2CPP first.",
    "godot": "Godot. Find the engine version. Godot 4 has OpenXR support built in: patch or wrap the main scene so the camera becomes an XROrigin3D rig and the viewport renders to the headset.",
    "emulator": "An emulated game. The program in 'Install folder' is an emulator and the game file is the player's own: work on the EMULATOR (its renderer, camera, input and settings) and its plugin or fork ecosystem, never on the game file. Prefer an emulator or fork that already has VR or stereo support, or a post-process or depth-based injected 3D route, and fall back to tier \"theater\" (the emulator window on a virtual screen). Never download, share or bundle game files, BIOS images, firmware or encryption keys: the player supplies their own, and the build must say so. Plunge launches the emulator with the game file as the first argument, so launch_game starts the right game.",
    "other": "Engine not recognised. Identify it first (file layout, exports, strings, window class). If the engine has no practical stereo hook, aim for tier \"injected\" (depth/geometry-based 3D) or tier \"theater\" (flat game on a virtual screen) and say honestly which you reached.",
}

START_SKIP = """Start here. I pasted this and pressed send, and I do NOT want to be interviewed: do not ask me any questions. Use these defaults, unless my preferences above say otherwise, and tell me in one line what you assumed: seated, gamepad, tier "native" if you can reach it, comfort "moderate", no multiplayer.
- Read up first: call game_info, search_profiles and environment. Don't summarize them for me. Tell me in one line only if a profile already exists or part of this can't be done.
- Then start building right away: don't play back a plan or ask whether to start. If something can't be built, say so in one line and build the closest version that can.
- Keep me posted in plain words every few minutes while you work ("flying in the headset now, fixing the menus").

If anything is written below this line, it is what I want: use it. If it tells you not to ask questions, never ask."""

START_ASK = """Start here. I pasted this and pressed send without adding anything, so don't wait for more from me.
- Read up first: call game_info, search_profiles and environment. Use what you learn to shape your questions; don't summarize them for me. Tell me in one line only if a profile already exists or part of this can't be done.
- Then interview me until you can picture it: one short question at a time, each with two to four concrete ideas to pick from (I can answer in my own words). Find out: seated or standing; motion controllers or gamepad; whether the flat screen should float as a theater or the world should be fully 3D; what comfort settings I need; whether it should be playable with friends; what the first five minutes must feel good. Skip what I already told you and stop after about five questions. If I say "just do it", stop asking and use the defaults (seated, gamepad, tier "native" if possible, comfort "moderate", no multiplayer), and tell me what you assumed.
- As soon as you have the answers, start building right away: don't play back a plan or ask whether to start. If something I asked for can't be built, say so in one line and build the closest version that can.

If anything is written below this line, it is what I want: use it, and skip the questions it answers. If it tells you not to ask questions, never ask."""

TEMPLATE = """Help me turn {name} into a VR game with Plunge, and save it as a Plunge profile so any player who owns the game can play it in VR with one click. I picked this game on Plunge's Create page; there is no profile yet unless I say so. Look at the game, redesign it slightly for VR, build it, test it, and save it. You do the work; keep me out of the technical details.

Plunge is for VR versions of existing PC games only. The player must own {name}; the profile never ships the game's content. Standalone VR demos, browser previews and look-alike games do not qualify.

What Plunge already knows (call game_info for the details):
- Game: {name} (id {appid}, from {store}). Put this id in plunge.json as steamAppId, exactly as given.
- Engine: {engine}
- Install folder: {path}
- Main executable: {exe}
- Steam build id: {build} (record it as tested.buildId so Plunge can warn players when the game updates)
- Anti-cheat found: {anticheat}
{headset_line}
- Hint for this engine: {hint}
{vr_note}{prefs_block}
You may do all of this without asking me (I authorize it):
- Download tools and runtimes from official sources: GitHub releases (use the REST API, there may be no gh), builds.bepinex.dev, NuGet, and install what you need (the .NET SDK, ilspycmd with DOTNET_ROLL_FORWARD=Major, Python run with -I).
- Launch and kill the game, launch the headset software that matches the active runtime, and take desktop screenshots of the game window.
- Create temporary config files, as long as you list each one and revert it at the end.
- Back up the game's saves and settings first, including its registry keys (for example HKCU\\Software\\<company>\\<game> PlayerPrefs).
- Install and remove the VR layer with Plunge's tools (below).
Stop and ask me ONLY for: a Steam or account sign-in, a payment, or a system-level change (for example switching the active OpenXR runtime). Nothing else.

Rules that cannot be bent:
- If game_info lists any anti-cheat (including Valve Anti-Cheat), stop and tell me. Never work around it.
- Never connect to a game's official servers and never touch its online services. If the game demands a login, calibration or an online service before it will start, find the game's own offline or keyboard-mode bypass. Anything multiplayer runs on player-hosted or private servers only.
- Never put the game's own content (models, textures, sounds, levels, paks, assets) in the profile. Third-party tools and loaders may be bundled only when their license allows, declared in "bundled" with name, author, license, url and sha256, and credited.
- Leave secrets out of the profile, your notes and your replies.

Step 0, check the environment before anything else (call environment, it reads this for you):
- Detect the headset path yourself: the active OpenXR runtime (HKLM\\SOFTWARE\\Khronos\\OpenXR\\1\\ActiveRuntime) and which headset software is running (Meta/Oculus, SteamVR, Virtual Desktop, Pico). Match your test to it. Don't start SteamVR if the active runtime is Meta.
- No headset attached? Use SteamVR's null driver, and say plainly that it cannot prove the picture: its session may never become visible and its field of view is synthetic. Mark everything seen only there as "simulator only".

How to work (any engine, any game):
- Look before designing. Call search_profiles: if a profile exists, tell me, because improving it may beat starting over.
- Use universal-modder (github.com/rehan-remade/universal-modder) to look at the game: its mod-any-game skill covers working out the engine, reading the game's real code, and testing in the running game. Set it up yourself (clone it and follow skills/mod-any-game/SKILL.md). Ask me before anything that costs money. Read only as much of the game as the VR version needs.
- Discover before you design: where the game keeps its settings (a file in the game folder, the registry, or AppData), whether its resolution or window mode is unusual (a multi-monitor span such as 5760x1080 counts), what content is locked, and whether it needs a calibrated controller or login (see the rules).
- Redesign the game slightly so it is VR-compatible: a head-tracked camera at the right scale and height, controller input, a HUD and menus that sit in the world, comfort options, and a way to handle cutscenes and forced camera moves. Prefer the game's established modding route (its loader, SDK or script extender) over patching its files.
- Be honest about the tier you reached and set it in plunge.json: "native" is real stereo VR through the engine, "injected" is depth/geometry-based 3D from outside, "theater" is the flat game on a big virtual screen. Always try the highest tier first. Falling back is fine; calling it higher than it is is not.
- Keep the design in JSON sheets in {profile_dir}/design/ and build from them: camera.json, input.json, ui.json, comfort.json, hooks.json. Each row is one thing, each column one property. The sheets are the source of truth: change the sheet before the code. Before every build, preflight: lay the sheets over each other, list every empty cell and unresolved reference, fix those first, and build only when the preflight is clean.

Engine cards (what has actually worked):
- Unity IL2CPP (BepInEx 6 be.788 + UnityVRMod, OpenXR IL2CPP backend): the game's own code may live in a separate interop assembly, not Assembly-CSharp (check the interop folder). UnityVRMod needs OpenXRConstants.XR_API_VERSION_1_1 set to 1.0 on SteamVR. It starts in safe mode, so toggle it once. It never moves the rig, so patch the pose update (UpdatePoses) with Harmony to follow the player or vehicle. It needs Camera.main tagged. Disable TemporaryLiveReloadTester. Disable BepInEx's console window: it steals focus.
- Unity Mono: BepInEx 5.4.x (what CWVR uses) or BepInEx 6 Mono with UnityVRMod. The game's code is in Assembly-CSharp.dll: decompile it with ilspycmd and patch with Harmony.
- Unreal (UEVR): turn on UObjectHook ("Enabled at Startup" in the profile). To get a weapon in the hand: hide the first-person arm mesh, Attach the gun component to a controller, Adjust the offset, Permanent Change (carefully), Save State, set Aim Method to that controller. Component names differ per game; search the SkeletalMeshComponent entries.
- Godot and other engines: identify the engine and version first, then use its own XR support if it has any.

Motion controls, hands and weapons (this is what makes a conversion feel real; don't stop at "the camera works"):
- Decouple the weapon from the first-person view: hide the first-person arms, attach the weapon (or the viewmodel) to the dominant controller's pose with a tuned offset, and stop the game snapping it back to the camera.
- Move the aim with it. The aim ray, hitscan origin or projectile spawn comes from the weapon's muzzle and forward vector, not the screen centre. Replace the crosshair with a laser sight or muzzle reticle.
- Two-handed weapons: aim along the line from the dominant hand to the off hand.
- Hands and gestures: holster zones, a grab for pickups, a reload gesture or button, melee from hand velocity, haptics on fire and hit.
- Body and comfort: separate head yaw from body yaw, snap or smooth turning, a HUD in world space (or on the wrist), no recoil or screen shake in the camera, and a virtual-screen fallback for cutscenes and forced camera moves.
- Not first person (vehicles, drones, cars)? Offer view-stabilization levels, because roll is the main sickness source. Map my comfort preferences to what you really built, and mark every option you did NOT build as supported: false in "options" instead of implying it.
- Respect my preferences: if I want third person, keep the character visible and put VR on the camera and aim only. If I set custom bindings, they override your defaults.
References (read what you need, don't recite them to me):
- UEVR 6DoF guide, the standard Unreal recipe: http://docs.uevr.io/usage/adding_6dof.html . Caveats: UObjectHook is off by default, component names differ per game, and Permanent Change on a component that controls player position can launch the player.
- UnityVRMod, a framework that injects a 6DOF camera rig and stereo rendering into Unity games (Mono and IL2CPP, OpenXR recommended, BepInEx 6, live-reloadable config; it does not do hands or weapons, you write those): https://github.com/NewUnityModder/UnityVRMod
- CWVR, an open-source OpenXR mod with motion-controlled hands for a Unity game on BepInEx 5 (read its Source folder for patterns; archived): https://github.com/DaXcess/CWVR
- The Flat2VR community (Discord, plus Flat2VR Studios for licensed ports) is where these mods are made and discussed. I could not find official public documentation from them, so do not claim to be following it.
- REA (Reverse Engineer Anything, MIT): an MCP server that lets you inspect native binaries, .NET assemblies, Electron/JavaScript apps and runtime behavior locally, with evidence for each conclusion. Use it when you must find out how a game loads its camera, input or UI and no source is available (setup: npx rea-agents setup, then restart the agent): https://github.com/morluto/rea . Only on my own offline, single-player copy. Never on a game with anti-cheat or an online service, and never to bypass DRM or licensing.
- UnityVRMod and CWVR are GPL-3.0. Learn from them; do not copy their code into a profile unless you will comply with the GPL and say so in "bundled", the credits and CREDITS.md.

UI conversion checklist (flat menus and HUDs are most of what looks broken):
- Overlay canvases become world-space panels. If the game reports a multi-monitor span, normalize the panel to 16:9.
- Stack canvases by sortingOrder as depth. Make sure the camera's culling mask includes every UI layer.
- A menu with no 3D camera gets its own anchor camera and a dark void. Give the canvas a world camera so the desktop mouse still works.
- Check CanvasGroup alpha for hidden menus. When swapping cameras, disable the camera component, not just the object.

Menus that are not translated to VR (the pointer fallback; do this for every game where a menu, launcher, settings or pause screen still looks flat):
- Never leave me stuck on a flat menu. If a screen cannot be turned into a proper in-world panel, show the game's flat screen on a large floating virtual screen in front of me, and let a controller act as a mouse on it.
- The controller is a laser pointer: where the ray meets the virtual screen decides the mouse position. Trigger = left click (hold to drag), grip or the secondary button = right click, thumbstick = scroll wheel, the B/Y or menu button = Escape or Back. Show the ray and a small cursor dot so I can see what I am pointing at.
- Switch automatically: pointer mode while a menu is up (the game shows a cursor, the cursor is unlocked, the game is paused or on a menu scene), and back to the normal VR controls the moment gameplay resumes. Add a manual toggle too (for example both thumbsticks pressed) for screens the game does not announce.
- Move the real system cursor with the game's own input path first (the engine's pointer or event system, or UEVR's mouse emulation). Only fall back to SetCursorPos and SendInput if nothing else works, and only while the game window is the foreground window.
- Test it with the controllers alone: start the game, change a setting, open and close the pause menu and quit, without touching the real mouse or keyboard. Report which screens needed the pointer.

Testing rules (these cost the most time before; follow them):
- Install with Plunge's tool (install_profile), not by copying files by hand, so the install is tracked and removable. Launch with launch_game, or steam -applaunch <appid>: never run a Steam game's exe directly, because Steamworks games exit without Steam. Do not restart Steam (sign-in is a human step). Handle Steam's stuck "Starting game" screen and SteamVR's Room Setup dialog.
- Before you send any keystroke or click, confirm the game is the foreground window (use the ALT-key trick, because plain SetForegroundWindow fails and your keystrokes land in my chat box). Report any stray input that reached my other windows.
- Make sure my own Plunge app isn't installing or overwriting the game folder while you test.
- Poll for these success signals in order: BepInEx "Chainloader startup complete", then "OpenXR fully initialized", then the session FOCUSED. Fail fast: if the process dies within about 10 seconds, read the loader's preloader log in the game folder.
- Build a test hook early (a command file for button clicks and UI dumps, an eye-render screenshot, a raycast probe) and gate it behind an enable-file, so shipped installs ignore it. Remove or disable it at the end.
- Play at least five real minutes including a menu, a cutscene and a fast camera turn, and record what you saw. Use only the controllers for the menus, so you prove the pointer fallback works.

Saving it (do this yourself):
1. Put the profile in {profile_dir}/ (slug: {slug}). Everything the recipe installs lives inside that folder, e.g. {profile_dir}/files/.
2. Write {profile_dir}/plunge.json (UTF-8 without a BOM):
   schema 2, title, tagline, steamAppId ({appid}), engine, tier, author, license, remix (true/false), comfort ("gentle", "moderate", "intense"), controls ("motion", "gamepad", "both"),
   tested {{ gameVersion, buildId, minutesPlayed, headset, notes }},
   bundled [ {{ path, name, author, license, url, sha256 }} ]   (third-party DLLs/exes only),
   recipe {{
     runtime: "uevr" or null,
     install: [ {{ from: "files/...", to: "{{game}}/..." }} ]   (destinations must start with {{game}}/ or {{uevr-config}}/),
     launch: {{ mode: "steam" or "exe", exe: "{{game}}/Game.exe", args: [], env: {{}} }}   (Steam games are always started through Steam),
     prefsFile: {{ path: "{{game}}/.../plunge-prefs.json", format: "json" or "ini" }},
     multiplayer: optional, see below
   }}
   options {{ perspective: ["auto","first","third"], bindings: true, comfort: true }}   (what your build really supports)
   The player's preferences (perspective, controller bindings, comfort) are written to recipe.prefsFile every time they press Play, as JSON like
   {{"perspective":"third","comfort":{{"snapTurn":true,"vignette":true,"locomotion":"smooth","stance":"seated"}},"bindingsMode":"custom","bindings":[{{"input":"Right grip","action":"Reload"}}]}}.
   When bindingsMode is "auto" the bindings list is empty and YOU choose the best controller mapping for this game.
   Make your build read that file at start and honour it, so players can change their setup without a new build.
3. Packaging limits that the validator enforces:
   - The whole profile folder is at most 50 MiB, raw. Trim the runtime: run a type-forwarding dependency analysis, keep every facade assembly under 60 KB, and test the trimmed profile on a clean install that includes first-run interop generation. If anything fails, read the loader's preloader log.
   - Every DLL or exe anywhere in the profile, including your own plugin and anything in src/obj, must be listed in "bundled" with its sha256. Clean obj and bin first, and don't ship source build folders.
   - Add a license classification table and a CREDITS.md. For any GPL dependency, state the licence consequence for your own plugin and give a source URL.
4. Call validate_profile with the slug. Fix every error. Explain every warning to me.
5. Install it with install_profile and launch it with launch_game once more as the final check.

Definition of done and honesty:
- Write a verification matrix into tested.notes: what was seen in a real headset, what was seen only in the simulator, and what was not tested. Don't claim more than you saw. After I confirm it works in my headset, update tested.headset and the notes to say so.
- Clean up: remove every temporary config file you made (name them), run uninstall_profile so the game folder is exactly how you found it (or state exactly what is installed), confirm my saves and settings are unchanged, and remove or disable the test hooks.
- Give me a rerunnable launch script and a one-line "how to play". Then show me a short summary: what the player gets, the required game version, tier, comfort, multiplayer, and the test result. Then stop. Do not publish anywhere yourself: tell me I can press Publish on the build in the Plunge app (Create page, or Discover > Publish a build) to share it with everyone.

Playing together (only if I want it):
Plunge gives every multiplayer profile a join code, an invite link friends can click, and a list of open games on the build\u2019s page; a joiner is put straight into the host\u2019s game and gets this build automatically. Set recipe.multiplayer: maxPlayers (at least 2), officialServers: false (required), hostArgs/hostEnv (the host writes its address to a log line, tell Plunge with address: {{ log: "{{game}}/.../latest.log", after: "Hosting at " }}), and one way to join: joinArgs, joinEnv, joinFile {{ path, key }}, joinUri (a steam://connect/{{address}} link), or manualJoin: true (the address is then shown to the joiner to paste into the game\u2019s own menu). "{{port}}" is a free port Plunge picks for you and "{{address}}" is the host\u2019s address. Environment variables must be the mod\u2019s own (for example MYMOD_JOIN), never system or runtime ones like PATH or DOTNET_STARTUP_HOOKS: Plunge refuses those. Players behind home routers cannot reach each other by local address: use the game\u2019s own relay or lobby, or tell players to use a private network. If the host has Tailscale or ZeroTier, Plunge swaps that address in for a home-only one by itself. Never tell players to forward ports. Test hosting and joining with two running copies and describe it in tested.multiplayer; if you could not test joining, leave multiplayer out.

Adding multiplayer to a single-player game (ONLY if my preferences above ask for "Multiplayer even if the game is single-player"; otherwise do not build any netcode):
- Say up front that this is experimental and that you will only claim what you proved with two running copies.
- Start with the smallest thing that is really fun, and build upward only if it works: (1) see each other: every player's head and hands appear as simple avatars in the others' worlds, with voice left to Discord; (2) shared goals: share only the state that matters for that game (scores, lap times, checkpoints, who has the ball, doors and pickups), with the host's copy as the authority; (3) shared world: only for games that are small and deterministic enough that it can really work. Say honestly which step you reached and why you stopped.
- Every player owns and runs their own copy of the game and installs the same build. Never share, upload or stream the game itself.
- Use plain sockets (UDP is fine) on the "{{port}}" and "{{address}}" Plunge gives you. No third-party relay, no account, no official servers, no telemetry. Keep packets small (positions about 20 times a second), ignore bad or oversized packets, and cap players at the number you tested.
- Players are not always on the same network: the host's address must be reachable. Say in tested.multiplayer exactly what you tested (same PC, LAN, or over the internet) and tell me that friends outside my network need a private network such as Tailscale or ZeroTier, or a port forward that I set up myself. Do not touch my router.
- Set recipe.multiplayer.kind to "added" (not "native"), start tested.multiplayer with the word "experimental", and list what is shared and what is not. Plunge refuses an added layer that does not say so.
- Same rules as everything else: no anti-cheat games, no cheating tools that give one player an edge, and never combine two games into one.

Plunge tools (run these in a terminal, they print JSON):
  {cli} environment
  {cli} game_info {appid}
  {cli} search_profiles {appid}
  {cli} preferences {appid}
  {cli} validate_profile {slug}
  {cli} profile_dir {slug}
  {cli} install_profile {slug} {appid}
  {cli} uninstall_profile {appid}
  {cli} launch_game {appid}

{start}
"""


def slugify(name):
    s = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return (s + "-vr")[:60]


def build(game, cli, profile_root, prefs_block="", vr=None, interview="skip", headset_line="- Headset: not chosen"):
    slug = slugify(game["name"])
    level = (vr or {}).get("level")
    vr_note = ""
    if level:
        vr_note = ("\nThis game already has official VR support (%s: %s). Do not rebuild what it has. Start by testing its own VR mode, "
                   "then build only what the player asks for on top of it (custom controls, comfort, perspective, mods), and set tier "
                   "\"native\" only for what you actually changed.\n" % ("VR only" if level == "only" else "VR supported", vr["via"]))
    return TEMPLATE.format(
        vr_note=vr_note, prefs_block=("\n" + prefs_block + "\n") if prefs_block else "",
        name=game["name"], appid=game["appid"], store=game.get("store", "Steam"), engine=game["engine"], path=game["path"],
        exe=game["exe"] or "not found", build=game.get("buildId") or "unknown", anticheat=", ".join(game["anticheat"]) or "none found",
        hint=ENGINE_HINTS[game["engine"]], cli=cli, slug=slug,
        profile_dir="%s/%s" % (str(profile_root).replace("\\", "/"), slug),
        start=START_ASK if interview == "ask" else START_SKIP, headset_line=headset_line,
    )
