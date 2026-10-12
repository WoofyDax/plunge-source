# Security

## Reporting a problem
Email **[SECURITY EMAIL]** with what you found and how to reproduce it. Please don't post it publicly until it is fixed.
We aim to answer within [3 business days]. (Fill the bracket in before publishing.)

## What Plunge protects, and how

| Risk | What stops it |
|---|---|
| Changing a game that has anti-cheat (account bans) | Detected from the game's files, plus Steam's "Valve Anti-Cheat" flag. No install, no injection, no override. The AI agent's tools refuse these games too. An anti-cheat game with official VR can only be started exactly as Steam starts it. |
| A shared build running something harmful | Builds can't contain a game's own files. Programs (DLLs, loaders) must be declared with author, licence, source link and a SHA-256 that is re-checked. The player must approve each build that ships programs, and is asked again if one changes. |
| Files written outside the game | Every install destination must be inside the game folder (links are resolved first). A failed install rolls back, and every change is recorded so Remove restores the original. Records are saved atomically so a crash can't corrupt them. |
| Hostile zip files (hub or downloads) | Path escapes, link entries, zip bombs (size and compression ratio), too many files and oversized files are rejected on upload **and** again when the app downloads. |
| A malicious lobby host or lobby server | Join addresses are checked to be plain `host[:port]` before they reach a launch argument or a config file (no spaces, quotes, newlines, `+commands`). Join codes are validated. Servers must use HTTPS (plain http only for a server on the same PC). |
| Web content reaching the app's controls | The window loads only its own inline page, with a strict Content-Security-Policy (no network from the page, no frames, images only over https), blocks navigation, and shows text from outside (titles, author names, ads) as plain text with control characters removed. Ads are data, never scripts. |
| Running the wrong AI agent command | Plunge only starts an agent the player picked, in a visible window, with a fixed first message. Model names are validated, and no flag that turns off the agent's own permission prompts is ever passed. |
| Abuse of the hub and lobby | Per-address rate limits, caps on stored profiles and total size, one like per profile per day, a limit on wrong join codes, request timeouts, and security headers. |
| Two Plunge windows changing one game | A single-instance lock. A second launch hands any join link to the first. |

## What Plunge does NOT do (read this before you rely on it)
- It does **not** vet the code inside a third-party loader. The player's approval and the declared checksums are the safeguard, not a scan.
- Author names on the hub are self-declared. There are no accounts yet, so there is no real identity or reputation.
- UEVR is downloaded from its official GitHub release over HTTPS; its publisher doesn't provide a checksum for Plunge to compare against.
- The first message to an AI agent points it at a brief file. What the agent then does is governed by that agent's own permission system.
- Updates are announced, never installed automatically.

## Before you run the hub or lobby for real
Use `deploy/` (HTTPS reverse proxy, containers that run as a normal user, limited resources), set `PLUNGE_HUB_ADMIN` to a long random value,
set `PLUNGE_TRUST_PROXY=1` only behind your own proxy, back up the hub's data folder, and keep the host patched.

## Supply chain
`requirements.txt` pins exact versions. Build on a clean machine, sign the installer, and publish its SHA-256 next to the download.
- Google sign-in uses the standard authorization-code flow with the secret kept on the hub. The round trip carries a signed, expiring state and is tied to the browser that started it by a cookie (blocks login CSRF). A Google identity is matched to an account only by Google''s verified email, so one person has one account. The desktop app gets its sign-in by presenting a secret it generated (whose hash it gave the hub at the start), once.