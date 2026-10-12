# Plunge Privacy Policy

> DRAFT: not yet reviewed by a lawyer. Keep this accurate if the app changes.

Last updated: October 10, 2026

Elizabeth Lennox ("we", "us") runs Plunge. This policy explains what the Plunge desktop app and our online services (the hub and lobby) do with your information. Plunge has **no analytics and no tracking of what you do in the app**. You only need an account to publish or like builds on the hub.

## 1. What stays on your computer

Plunge reads your Steam library folders to list your games, find each game's engine, and check for anti-cheat. This information is used on your computer only. We do not upload your game list.

Plunge stores these files on your computer, in `%LOCALAPPDATA%\Plunge`:

- profiles you made or downloaded, and records of what Plunge installed into a game (so it can undo it)
- your preferences for each game (camera, controls, comfort, notes)
- settings, such as whether you finished the welcome screen, which profiles you chose to trust, and the ad on/off switch
- caches (Steam VR-support answers, legal pages)

You can delete this folder at any time. Uninstalling the app does not remove it unless you choose to.

## 2. What the app sends over the internet, and to whom

Whenever the app contacts another server, that server sees your IP address and ordinary connection details. Specifically:

- **Steam store (Valve).** To tell you whether a game already supports VR, Plunge asks Steam's public store for each installed game's app number. This means Valve receives requests for the app numbers of the games you own. Answers are cached for 7 days.
- **Steam image servers.** Game artwork shown in the app is loaded from Steam's image servers.
- **GitHub.** If you click to install UEVR, Plunge downloads it from the UEVR project's official GitHub releases.
- **The Plunge hub (hub.plungevr.com).** When you open Discover or search, the app asks the hub for builds. If you add a build, the hub counts a download. If you press Like, it counts a like (one per account). If you publish, the hub receives the profile you upload (all of its files and its details), and puts your account username on it as the author.
- **Your account (hub.plungevr.com, plungevr.com/account).** To sign in you can use an email address and password, an emailed 6-digit code, or Google. The first time you give an email address (or use Google) we create your account: we store your email address, your username, when the account was created, your signed-in sessions, and, if you set one, your password as a salted scrypt hash (we cannot read it). If you use Google, we receive your Google account's ID and verified email address (nothing else is kept) and Google learns that you signed in to Plunge. Emailed codes are sent through our email provider, Resend. Codes and session tokens are stored only as keyed hashes. On the website, signing in sets cookies that keep you signed in (strictly necessary, HttpOnly, not used for tracking). In the app, the sign-in is kept in the app's settings on your PC until you sign out.
- **Update check (plungevr.com).** When the app starts it asks our website for a small file saying which version is newest. Like any web request, this shows your IP address to the site's host. The app never downloads or installs an update by itself.
- **The Plunge lobby service (lobby.plungevr.com).** If you host a multiplayer game, the lobby receives the game's number, the profile name, a title, the player limit and **your game's network address** (which is usually your IP address and port), and shares that address with anyone who has your join code. Public lobbies appear in a list (without the address). The lobby forgets a game shortly after you stop hosting.
- **Advertising.** If an ad source is set up, the app asks it for one "Sponsored" card, which shares your IP address with that source. If the ad includes an impression link, the app calls it once. The app sends the ad source nothing about your games. You can turn this off in Settings, and no ad is requested while it is off.

We do not sell your information.

## 3. What the hub and lobby keep

- **Hub:** your account (email address, username, creation time, sessions, a password hash if you set one, and your Google account ID if you linked one), uploaded profiles and their details, who liked what (as account numbers, to allow one like each), download and like counters, and the time of upload. Sign-in codes are deleted when used or after 10 minutes. Hosting providers and our servers may also keep standard technical logs (such as IP address and time) for security and troubleshooting, for up to 30 days.
- **Lobby:** the information in section 2 while a game is open, held in memory and not saved long term.

Anything you publish to the hub is public, including the author name you chose. Do not put personal information in a profile.

## 4. How we use information

To run the hub and lobby, show you builds, prevent abuse and malware, respond to takedown requests and legal claims, and keep the Service secure. Where privacy law requires a legal basis, we rely on our legitimate interest in running and securing the Service, and on your request when you use a feature.

## 5. Sharing

We share information only with: the hosting and infrastructure providers that run our servers; an advertiser's ad source, as described above; people you choose to share a join code with; and authorities when the law requires it. Third parties you visit through links (such as Steam, GitHub or an advertiser) have their own policies.

## 6. Children

Plunge is not aimed at children under 13. We do not knowingly collect their information. Contact us if you think a child has uploaded something.

## 7. Your choices and rights

You can use the app without the hub, lobby or ads. Depending on where you live (for example the EU, UK or California) you may have the right to ask what we hold about you, and to have it corrected or deleted, or to object to processing. You can delete your account yourself, in the app (click your name, then Delete my account) or at plungevr.com/account. That deletes your email address, username, sessions and every build you published. You can also email support@plungevr.com to ask for access, correction or deletion. Contact: support@plungevr.com.

## 8. Security

We use reasonable measures to protect the services, but no system is perfectly secure. Profiles from other people can contain programs that run on your computer; Plunge asks before running them. See the Terms of Use.

## 9. International transfers

Our servers may be in the United States. If you are elsewhere, your information is transferred there when you use the hub or lobby.

## 10. Changes and contact

We will update this policy when the app changes and show the new date above. Questions: Elizabeth Lennox, Dallas, Texas, United States, support@plungevr.com.
