# Putting Plunge online (plungevr.com)

Three pieces, each on the host that suits it:

| What | Address | Where | Cost |
|---|---|---|---|
| Website, download page, legal pages, update file | `plungevr.com` | Cloudflare Pages (free), or Vercel, Netlify | free |
| Hub (Discover, profile uploads) + lobby (join codes) | `hub.plungevr.com`, `lobby.plungevr.com` | one small server (VPS) running Docker | about $4–6 a month |
| The installer file | a link on the download page | GitHub Releases (free) | free |

## Why not Vercel for everything

Vercel runs short-lived functions. The lobby keeps who is hosting in memory and expects a program that stays running, and the hub
stores uploaded profiles on a disk. Neither fits Vercel, so they go on a normal server. Vercel (or Cloudflare Pages) is fine for the
static website. Note: Vercel's free "Hobby" plan is for non-commercial use only, and Plunge shows ads, so use Cloudflare Pages
(free, commercial use allowed) or a paid Vercel plan.

## 1. The server (hub + lobby)

1. Rent a server: Hetzner CX22 (about €4/month), DigitalOcean or Vultr (about $6), Ubuntu 24.04. Add your SSH key when asked.
2. Copy the `plunge` folder to it (`scp -r plunge root@SERVER_IP:/opt/plunge`).
3. In your DNS (Unstoppable Domains → plungevr.com → DNS records) add two **A** records pointing at the server's IP:
   `hub` → SERVER_IP and `lobby` → SERVER_IP. Wait a few minutes.
4. On the server: `cd /opt/plunge && sudo bash deploy/setup-server.sh`. It installs Docker, a firewall, automatic security updates,
   creates a random admin key in `deploy/.env`, starts everything with HTTPS certificates (Caddy gets them itself), and schedules a daily backup.
5. Check: open `https://hub.plungevr.com/health` and `https://lobby.plungevr.com/health`. Each should show `{"ok": true, ...}`.
6. Add an uptime monitor (UptimeRobot free plan) on both /health addresses.
7. Copy a backup off the server now and then (`/var/backups/plunge`).

Updating the server later: copy the new `plunge` folder over and run `docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build`.

## 2. The website

1. Put the installer on a GitHub Release (create a free GitHub repo, upload `dist/PlungeSetup-<version>.exe`).
2. `python tools/build_site.py --download-url https://github.com/<you>/<repo>/releases/latest` writes the site into `site/`.
3. Cloudflare Pages → create a project → upload the `site` folder (or connect the repo, output folder `site`). Add the custom domain `plungevr.com`.
   If you use Vercel instead, `site/vercel.json` already sets the security headers.
4. If Cloudflare manages the DNS, it will tell you the exact records. If DNS stays at Unstoppable Domains, add the records the host asks for
   (usually a CNAME for `www` and an A or ALIAS for the bare domain). Keep the `hub` and `lobby` A records from step 1.3.
5. Check `https://plungevr.com/latest.json`: the app reads it to tell players a new version exists.

To release a new version: bump `core/version.py`, run `build.ps1`, upload the installer to a new GitHub Release, run `tools/build_site.py` again, and upload `site/`.

## 3. Things only you can do

- Email: set up `security@plungevr.com` and `support@plungevr.com` (Unstoppable Domains, Cloudflare Email Routing and Zoho Mail all offer this).
  The legal pages and `security.txt` refer to these.
- Fill every `[bracket]` in `legal/*.md` (your name, address, DMCA agent, jurisdiction), have a lawyer read them, then rebuild the site.
- Buy a code-signing certificate and sign the installer with `sign.ps1`, or Windows will warn people.
- Keep `deploy/.env` private. The admin key lets someone feature profiles on Discover.

## What is not built yet

No user accounts, no moderation tools beyond the admin key, no automatic scanning of uploaded profiles for malware, and no database
(the hub keeps files on disk, which is fine for a small community and should move to a database if it grows). The deploy scripts have
not been run on a real server by the author: do a first run on a throwaway server and read `docker compose logs`.

## Taking a profile down

To remove an uploaded profile (a takedown notice, malware, abuse), you need its id (the last part of its Discover link, or from GET https://hub.plungevr.com/profiles) and the admin key from Railway (service **hub** > Variables > PLUNGE_HUB_ADMIN):

    curl -X POST https://hub.plungevr.com/profiles/<id>/remove -H "X-Admin: <your key>" -d "{}"

It deletes the profile and its file. Keep the key private.

## Accounts and sign-in emails

The hub has accounts: people sign in with email + password, a 6-digit code sent to their email, or Google. Publishing and liking need an account.

Set these variables on the **hub** service in Railway:

| Variable | What it is |
|---|---|
| `RESEND_API_KEY` | a Resend **sending-only** key limited to plungevr.com (create it in Resend: API Keys > Sending access) |
| `PLUNGE_MAIL_FROM` | the sender, default `Plunge <no-reply@plungevr.com>` (the domain must be verified in Resend) |
| `PLUNGE_WEB_ORIGINS` | the websites allowed to call the hub from a browser, default `https://plungevr.com,https://www.plungevr.com` |
| `PLUNGE_EMAIL_DAILY_CAP` | most sign-in emails per day, default 90 (Resend's free plan allows 100) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | turn on "Continue with Google" (see the setup steps below) |
| `PLUNGE_PUBLIC_URL` | the hub's public address, default `https://hub.plungevr.com` (used for Google's redirect) |
| `PLUNGE_HUB_REQUIRE_AUTH` | `1` (default): publishing and liking need an account. `0` only for a private hub |

Accounts live in `accounts.db` in the hub's data volume (back it up with the rest of the volume). Deleting an account deletes its profiles. To rotate the Resend key, make a new one, change `RESEND_API_KEY`, redeploy, then delete the old key.
### Google sign-in setup (one time, about 10 minutes, done by you)

The button stays hidden until the hub has these two settings. You create them in Google Cloud (free):

1. Go to https://console.cloud.google.com/ and create a project named "Plunge".
2. **APIs & Services > OAuth consent screen**: choose **External**, app name "Plunge", your support email (`support@plungevr.com`), app domain `https://plungevr.com`, privacy policy `https://plungevr.com/privacy`, terms `https://plungevr.com/terms`, authorized domain `plungevr.com`. Scopes: only `openid`, `email`, `profile` (these need no Google review). Then click **Publish app** so anyone can sign in (otherwise only test users can).
3. **APIs & Services > Credentials > Create credentials > OAuth client ID**: type **Web application**, name "Plunge hub". Under **Authorized redirect URIs** add exactly `https://hub.plungevr.com/auth/google/callback`.
4. Copy the **Client ID** and **Client secret**, and set them on the Railway **hub** service as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, then redeploy.

Check: `https://hub.plungevr.com/auth/config` should now show `"google": true`, and the "Continue with Google" button appears in the app and on plungevr.com/account. Keep the secret private.