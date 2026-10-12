> Source published so testers can review what Plunge does before installing it. All rights reserved for now; no licence is granted to copy or redistribute. Questions: support@plungevr.com

# Plunge: any game, in VR

A Windows desktop app. You pick a game you own; an AI agent (Claude Code, Codex) reads it with
[universal-modder](https://github.com/rehan-remade/universal-modder), redesigns it for VR the way *you* want it,
and saves a **profile**. Plunge installs it in one click, can remove it again, and lets friends join your session.

## Run it

- `dist\Plunge.exe`: the app (native window, no web server, listens on no port).
- `dist\plunge-cli.exe`: console twin for agents (`tool ...`) and the services (`lobby`, `hub`).
- From source: `python app.py` (needs `pip install pywebview`). Rebuild both exes with `build.ps1`.
- UI work without rebuilding: `python tools\devserve.py` serves the same UI in a browser with the real backend (dev only).

## The app

- **Discover** (opens first): Featured carousel, Just released, Popular (from the community hub), plus
  "Already VR-ready in your library" and "Quick try with UEVR" from your own games. Search covers games and hub builds.
- **Library**: your games. "My VR games" = anything with a build or saved preferences. Filters: built-in VR, quick try, blocked.
- **Create**: pick a game, set your preferences, copy the brief for your agent, manage and publish your builds.
- **Join a friend** (people icon, top right): paste a join code.

### Games that already support VR
Plunge asks Steam (category "VR Supported" / "VR Only", cached 7 days) and also looks for VR runtime files in the install.
Those games get a "VR ready" badge and can be played in VR with no build. The AI brief then says "build on top of
the official VR mode" instead of rebuilding it.

### Your own controls and preferences
Per game: camera (let the build decide / always first person / **keep third person**), movement, stance, snap turn,
vignette, **any controller binding** (e.g. Right grip -> Reload, Y -> Open map) and free-text wishes.
They go into the AI brief as requirements, and a profile that declares `recipe.prefsFile` gets them written into
the game on every Play (and removed again on uninstall). Builds list what they support under `options`.

### Quality tiers (set honestly in each profile)
`native` real stereo VR through the engine · `injected` depth/geometry-based 3D · `theater` the flat game on a virtual screen.

## How a build gets made and installed
1. Scan Steam; detect engine and anti-cheat (blocked, no override).
2. **Copy brief** -> your agent interviews you, studies the game, builds, tests, saves
   `%LOCALAPPDATA%\Plunge\profiles\<slug>\plunge.json` + files. Agent tools:
   `plunge-cli.exe tool game_info|search_profiles|validate_profile|profile_dir|preferences ...`
3. **Play**: validate, copy the recipe's files into the game (backing up anything replaced), write preferences, launch.
   **Remove VR layer** restores everything. Unreal games can also be tried instantly via [UEVR](https://github.com/praydog/UEVR)
   (Unreal only: 4.8 to 5.4).

## Community hub (Discover uploads)
`plunge-cli.exe hub --port 8788 --data <dir>`; clients use `PLUNGE_HUB` (default `http://127.0.0.1:8788`).
Players **Publish** a build (zip); the hub re-runs the same validator (no game content, no undeclared DLLs, no secrets,
a recorded play test, safe paths, zip-slip protection) and lists it. Featured needs `PLUNGE_HUB_ADMIN`.
**Add to Library** downloads and re-validates locally. Author names are self-declared: there are no accounts yet.

## Sponsored cards (ads)
Dormant until you set an ad source. Create `%LOCALAPPDATA%\Plunge\ads.json` with `{"url": "https://your-ad-endpoint"}`
(or set `PLUNGE_ADS_URL`). The endpoint returns JSON: `{"ad": {"id","title","body","image","link","cta","advertiser","viewUrl"}}`
(`link`, `image`, `viewUrl` must be https). Plunge draws one labelled **Sponsored** card in a Discover row; clicking opens
the link in the normal browser; `viewUrl` is pinged once per session from Python as the impression.
Ads are data, never scripts: nothing from an ad runs inside the app, so it can't reach Plunge's functions.
Players can switch them off in Settings. Loading one shares the player's IP with the ad source (disclosed in Settings).
- **Google AdSense does not allow desktop apps** and AdMob is mobile-only: don't use them here.
- Options that fit: sell sponsorships directly (headset makers, game studios) by hosting a small JSON endpoint,
  or use a network that offers a server-side JSON/API format and approves desktop apps (apply to them yourself).
- At small scale ad revenue is tiny; direct sponsorships, a donation link or a paid tier usually earn more.

## Playing together
`recipe.multiplayer` lets Plunge host (reads the host's address from the game's log, opens a lobby, shows a code) and
join by code. `officialServers: false` is mandatory; games run on player-hosted or private servers.
`plunge-cli.exe lobby --port 8787`; clients use `PLUNGE_LOBBY`.

## Finding games
Plunge reads Steam's own records (every Steam library, including other drives), then also looks for:
Steam game folders that have no record (leftover or moved installs), **Epic** (launcher manifests), **GOG** and **Ubisoft Connect**
(registry), Xbox/Game Pass folders, common folders such as `D:\Games`, and any folder you add with **Library > Add a game folder**
(a folder that is a game, or a folder that holds games). Non-Steam games get ids like `dir-1a2b3c4d` / `epic-<AppName>`.
Not covered yet: EA app and Battle.net (use Add a game folder). Games that Steam marks as Valve Anti-Cheat (VAC) are blocked too.
Empty leftover folders are ignored (a game needs a real program of at least 1 MB).

More sources: **EA** (registry), **Windows' installed-apps list** (kept only when the folder contains a Unity, Unreal or Godot game, so
software and drivers never show up), common game folders on **every local drive** (including USB), the Steam install found in
several registry locations or on any drive, and both old and new Steam `libraryfolders.vdf` layouts.
**Library > Missing a game?** shows exactly what was looked at, and offers *Add a game folder*, *Scan my drives* (seconds) and
*Look deeper* (a minute or two) for games buried in nested folders. On the dev PC a deep scan found 6 games nothing else saw.
Tested only on one PC with Steam + loose folders: Epic, GOG, Ubisoft and EA detection follow those launchers' documented
locations but have not been run against real installs.

## Your VR headset
Welcome screen and Settings ask which VR you use (Meta Quest via Link/Air Link, Quest/Pico via Virtual Desktop, SteamVR, Pico, Windows
Mixed Reality, something else, no headset). Plunge pre-selects it from the active OpenXR runtime. The choice goes into the AI brief
(so the agent tests with the right headset software) and picks the runtime to choose in UEVR's injector.

## Anti-cheat
Plunge **never modifies, injects into, or installs anything for a game with anti-cheat** (Easy Anti-Cheat, BattlEye, Vanguard, XIGNCODE3,
EQU8, Valve Anti-Cheat), and there is no override: doing so risks account bans and is how cheating works. One thing is allowed: a
protected game that **already has official VR support** can be launched exactly as Steam launches it (nothing installed, nothing
changed), shown as "Built-in VR". The AI agent's tools refuse protected games too.

Melty works the same way: its own prompt for War Thunder says it "never mods its client" (anti-cheat: BattlEye). Plunge is not a
mashup tool; its one job is making a single game playable in VR.

## Launching
Steam games are always started through Steam (`steam.exe -applaunch`), never by running the exe, and Plunge then **reads Steam's
log to confirm the game really started**, or shows Steam's own reason (for example Family Sharing: a borrowed game can't start
while its owner is playing). Epic games start through the Epic launcher, others by their program.

## The AI brief (what the agent is told)
By default the agent is **not** allowed to interview the player (toggle "Let the agent ask me questions first" on Create).
It checks the environment itself (`environment`: active OpenXR runtime, headset software, tools), may download tools, launch the
game and take screenshots without asking, and may stop only for a sign-in, a payment or a system change. It tests with
`install_profile` / `launch_game` / `uninstall_profile` (tracked, removable), follows test-harness rules (launch through Steam,
confirm the foreground window, success signals), uses engine cards (Unity IL2CPP/Mono, Unreal, other), converts UI to world space,
packages within the validator's limits (50 MiB, every DLL declared, no BOM, CREDITS.md), writes an honest verification matrix and
cleans up after itself. Agent tools: `environment, game_info, search_profiles, preferences, validate_profile, profile_dir,
install_profile, uninstall_profile, launch_game`.

## Safety checks for players
- **Bundled programs need your OK.** A profile that ships DLLs/exes (mod loaders) shows who made them, their licence and source
  before it can run; the OK is tied to their checksums, so a swapped file asks again.
- **Game-update warning.** Profiles record the Steam build they were tested on; a newer game shows "Game updated since this build was tested".
- **`plunge://join/CODE` links** (opt-in, per-user, in Settings or the installer): a link only pre-fills the Join box and never starts a game by itself.
- First-run welcome, a Settings page with version, ad switch, link handler and the legal documents.

## Release engineering
- `build.ps1` builds `dist\Plunge.exe`, `dist\plunge-cli.exe` and `dist\PlungeSetup-<version>.exe` (Inno Setup, per-user, no admin).
  Silent install/uninstall tested: `/VERYSILENT /CURRENTUSER /SUPPRESSMSGBOXES`.
- `sign.ps1` / `build.ps1 -Sign <thumbprint>` sign the exes, then the installer. Needs a real code-signing certificate that only you can buy
  (identity verification); tested here with a throwaway certificate. Until then Windows SmartScreen will warn.
- `legal/` holds draft Terms, Privacy, Copyright/Takedown, Guidelines and Notices; `LEGAL-CHECKLIST.md` lists the blanks and what only you can do.
- Version lives in `core\version.py`. Icon: `tools\make_icon.py`.

## Tested
`test_plunge.py` (47: validator, install/uninstall/rollback, lobby, CLI), `test_features.py` (51: VR detection,
preferences, prefsFile, hub upload/reject/sort/feature/download/publish), `test_bridge.py` (the app bridge, the brief,
agent commands, clipboard; the launcher is stubbed so tests never start a game). All pass.
The built exes open a native window with 0 listening ports.

## Not done / not verified
- **No hub or lobby is hosted yet**: Discover shows "hub offline" until you run one and point clients at it.
  No accounts, ratings beyond a like counter, or moderation beyond automatic validation. No NAT relay for multiplayer.
- **"Any game" is a pipeline, not a guarantee.** No agent-built profile has been played in a headset yet,
  and none ships with Plunge. How good a result is depends on the game.
- Preferences only change a game if the build reads them (`prefsFile`); otherwise they only shape the brief.
- UEVR quick-try still needs you to pick the game and press Inject. Its per-game config path is from memory.
- VR detection is Steam's tag (or file hints marked unconfirmed); a few games tag VR support inaccurately.
- Steam games only. Unsigned exe (SmartScreen warns). No `plunge://` link handler (paste the code).
