"""The plungevr.com home page. Same overall shape as Melty's landing page (very dark, tight semibold type, a big headline with a blue pill,
one idea per section, a two-column FAQ, a final download), written from scratch with Plunge's own words and drawings. Real game images are
screenshots of free, open-source games under open licences, credited on /credits. Scroll effects live in web/scroll.js and the 3D hero in
web/hero.js; if either fails to load the page is still complete and readable.
"""
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import logo_svg as _logo  # noqa: E402

CSS = """
@font-face{font-family:Inter;src:url(/fonts/inter.woff2) format("woff2");font-weight:100 900;font-display:swap}
:root{--bg:#050506;--text:#f2f2f2;--soft:rgba(255,255,255,.7);--dim:#6b6b73;--blue:#008cfd;--panel:#101012;--panel2:#18181b;--line:#1b1b1e;--e:cubic-bezier(.2,.7,.2,1)}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%;background:var(--bg);scroll-behavior:smooth}
html.locked,html.locked body{overflow:hidden;height:100%;overscroll-behavior:none}
body{margin:0;background:var(--bg);color:var(--text);font:400 17px/1.45 Inter,"Segoe UI",Arial,sans-serif;letter-spacing:-.02em;overflow-x:hidden}
a{color:inherit;text-decoration:none}button{font:inherit;color:inherit;letter-spacing:inherit}svg{display:block}
.prog{position:fixed;left:0;top:0;right:0;height:2px;background:var(--blue);transform:scaleX(0);transform-origin:0 50%;z-index:40}
/* nav */
.nav{position:fixed;inset:0 0 auto 0;z-index:30;display:flex;align-items:center;justify-content:space-between;padding:14px 20px;background:linear-gradient(#050506 30%,rgba(5,5,6,0));transition:transform .45s var(--e)}
.nav.hide{transform:translateY(-110%)}
.logo{display:flex;align-items:center;gap:10px}.logo .lw{height:19px;width:auto}
.logo .lm{width:30px;height:30px}
.navr{display:flex;align-items:center;gap:8px}
.nbtn{height:44px;min-width:44px;padding:0 18px;border-radius:14px;background:var(--panel2);display:flex;align-items:center;justify-content:center;font-weight:600;font-size:15px}
.nbtn:hover{background:#222226}.nbtn.blue{background:var(--blue);color:#fff}.nbtn.blue:hover{background:#2aa0ff}.nbtn.blue.off{background:var(--panel2);color:var(--dim);pointer-events:none}
/* hero */
.hero{position:relative;padding:74px 40px 40px;height:100svh;min-height:600px}
.copy{position:absolute;z-index:4;left:84px;bottom:92px;text-align:left;pointer-events:none;transition:opacity .6s var(--e),transform .6s var(--e)}
.copy .chip{position:static;display:inline-flex;margin-bottom:20px;pointer-events:auto}
.hero:has(.frame[data-phase=vr]) .copy{opacity:0;transform:translateY(14px)}
.hero h1{margin:0;font-weight:600;font-size:clamp(34px,5vw,72px);line-height:1.03;letter-spacing:-.045em;text-shadow:0 2px 30px rgba(0,0,0,.45)}
.pillbig{display:inline-flex;align-items:center;gap:.2em;background:var(--blue);padding:.02em .3em .09em .18em;border-radius:.3em;margin-top:.1em;color:#fff}
.pillbig svg{width:.58em;height:.58em;fill:currentColor}
.frame{position:relative;width:100%;height:100%;margin:0;border-radius:28px;overflow:hidden;background:#030305;isolation:isolate;text-align:left;container-type:size}
.frame canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
.frame:after{content:"";position:absolute;inset:auto 0 0 0;height:58%;background:linear-gradient(rgba(0,0,0,0),rgba(0,0,0,.74));pointer-events:none;z-index:2;transition:opacity .6s}
.frame[data-phase=vr]:after{opacity:0}
.frame.nogl{background:linear-gradient(#050506,#10243f)}
.lens{position:absolute;inset:0;background:#000;opacity:0;transition:opacity .6s;pointer-events:none;--r:min(46cqh,24cqw);
  -webkit-mask:radial-gradient(circle var(--r) at 25% 50%,transparent 97%,#000 100%),radial-gradient(circle var(--r) at 75% 50%,transparent 97%,#000 100%);
  mask:radial-gradient(circle var(--r) at 25% 50%,transparent 97%,#000 100%),radial-gradient(circle var(--r) at 75% 50%,transparent 97%,#000 100%);
  -webkit-mask-composite:source-in;mask-composite:intersect}
.frame.stereo .lens{opacity:1}
.tag{z-index:3;position:absolute;left:14px;top:14px;display:flex;align-items:center;gap:8px;background:rgba(10,10,12,.72);backdrop-filter:blur(10px);border-radius:999px;padding:6px 14px 6px 6px;font-weight:600;font-size:14px}
.tag span{background:var(--blue);padding:2px 10px;border-radius:999px;min-width:46px;text-align:center}
.skip{z-index:3;position:absolute;right:14px;top:14px;height:40px;padding:0 16px;border-radius:999px;border:0;background:rgba(10,10,12,.72);backdrop-filter:blur(10px);font-weight:600;font-size:14px;cursor:pointer}
.skip:hover{background:rgba(40,40,46,.85)}.frame[data-done=true] .skip{display:none}
.chip{position:absolute;left:14px;bottom:14px;display:flex;align-items:center;gap:10px;background:rgba(10,10,12,.78);backdrop-filter:blur(12px);border-radius:18px;padding:7px 18px 7px 7px;font-weight:600;font-size:17px}
.chip .ic{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;background:#26262a}.chip .ic svg{width:23px;height:23px;fill:#fff}.chip .ic.b{background:var(--blue)}.chip .pl{color:var(--dim)}
.hint{z-index:3;position:absolute;left:50%;bottom:20px;transform:translateX(-50%);background:rgba(10,10,12,.78);backdrop-filter:blur(12px);border-radius:999px;padding:9px 18px;font-weight:600;font-size:14px;display:flex;gap:8px;align-items:center;transition:opacity .3s;pointer-events:none}
.hint svg{width:16px;height:16px;fill:none;stroke:#fff;stroke-width:2.4;animation:bob 1.4s ease-in-out infinite}
@keyframes bob{50%{transform:translateY(4px)}}
/* intro */
.intro{padding:150px 20px 20px;text-align:center}
.intro p{margin:0 auto;max-width:19em;font-size:clamp(24px,3.1vw,42px);line-height:1.12;letter-spacing:-.035em;font-weight:600}
.intro p span{transition:opacity .15s}.intro p .em{color:var(--blue)}
.dl{display:flex;flex-direction:column;align-items:center;gap:10px;margin-top:34px}
.btn{display:inline-flex;align-items:center;justify-content:center;height:56px;padding:0 30px;border-radius:16px;background:var(--blue);color:#fff;font-weight:600;font-size:19px}
.btn:hover{background:#2aa0ff}.btn.off{background:var(--panel2);color:var(--dim);pointer-events:none}
.free{color:var(--soft);font-size:15px;display:flex;align-items:center;gap:6px}.free svg{width:15px;height:15px;fill:currentColor}
/* features */
.feat{padding:130px 20px 20px;max-width:1100px;margin:0 auto;text-align:center}
.feat h2{margin:0;font-weight:600;font-size:clamp(25px,3vw,40px);line-height:1.06;letter-spacing:-.035em}
.feat>p{margin:26px auto 0;max-width:23em;color:var(--soft);font-size:clamp(17px,1.5vw,20px);line-height:1.35;letter-spacing:-.025em}
.feat>p b{color:var(--text);font-weight:600}
.vis{margin:44px auto 0;max-width:640px;background:var(--panel);border:1px solid var(--line);border-radius:28px;padding:26px;text-align:left;min-height:240px;display:flex;flex-direction:column;justify-content:center;gap:16px;will-change:transform}
.playrow{display:flex;align-items:center;gap:16px}
.pbtn{position:relative;height:64px;min-width:210px;border-radius:18px;background:var(--blue);display:grid;place-items:center;font-weight:600;font-size:21px;overflow:hidden}
.pbtn span{position:absolute;opacity:0;animation:cyc 8s infinite;animation-play-state:paused}
.pbtn span:nth-child(2){animation-delay:2s}.pbtn span:nth-child(3){animation-delay:4s}.pbtn span:nth-child(4){animation-delay:6s}
.live .pbtn span,.live .bar b,.live .say u{animation-play-state:running}
@keyframes cyc{0%{opacity:0;transform:translateY(10px)}4%,22%{opacity:1;transform:none}26%,100%{opacity:0;transform:translateY(-10px)}}
.game{display:flex;align-items:center;gap:12px;font-weight:600}.game i{display:block;width:54px;height:54px;border-radius:14px;background:linear-gradient(135deg,#3a3f52,#1e2130)}
.bar{height:8px;border-radius:5px;background:#26262a;overflow:hidden}.bar b{display:block;height:100%;width:0;background:var(--blue);border-radius:5px;animation:fill 8s infinite;animation-play-state:paused}
@keyframes fill{0%{width:0}22%{width:64%}46%{width:100%}100%{width:100%}}
.link{display:flex;align-items:center;justify-content:space-between;gap:10px;background:var(--panel2);border-radius:16px;padding:14px 18px;font-weight:600;font-size:clamp(14px,2.6vw,19px)}
.link code{font:inherit;color:#d7d7dc;overflow:hidden;text-overflow:ellipsis}
.copied{background:#16351f;color:#59d98e;border-radius:999px;font-size:13px;padding:5px 12px;white-space:nowrap}
.avs{display:flex}.avs i{width:44px;height:44px;border-radius:50%;margin-right:-10px;border:3px solid var(--panel);display:grid;place-items:center;font-style:normal;font-weight:700;font-size:15px}
.avs i:nth-child(1){background:#7c5cff}.avs i:nth-child(2){background:#ff7a45}.avs i:nth-child(3){background:#1fb98a}.avs i:nth-child(4){background:#e0457b}.avs i:nth-child(5){background:#333;color:var(--soft)}
.agents{display:flex;flex-wrap:wrap;gap:8px}.agents span{background:var(--panel2);border-radius:999px;padding:8px 16px;font-weight:600;font-size:15px}.agents span.on{background:var(--blue)}
.say{background:var(--panel2);border-radius:16px;padding:16px 18px;color:#d7d7dc;font-size:16px;line-height:1.4}
.say u{text-decoration:none;display:inline-block;width:2px;height:1.1em;background:var(--blue);vertical-align:-.2em;margin-left:2px;animation:blink 1s steps(1) infinite;animation-play-state:paused}
@keyframes blink{50%{opacity:0}}
.send{align-self:flex-start;background:var(--blue);padding:11px 22px;border-radius:14px;font-weight:600}
.row{display:flex;align-items:center;gap:14px;font-weight:600;font-size:clamp(16px,2.4vw,21px)}
.row svg{flex:none;width:30px;height:30px;padding:6px;border-radius:50%;background:#16351f;fill:#59d98e}
/* gallery: real screenshots from open-source games, sliding sideways as you scroll */
.gal{padding:130px 0 20px;overflow:hidden;text-align:center}
.gal h2{margin:0 20px;font-weight:600;font-size:clamp(25px,3vw,40px);line-height:1.06;letter-spacing:-.035em}
.gal .track{display:flex;gap:16px;margin-top:44px;padding:0 24px;width:max-content;will-change:transform}
.card{position:relative;flex:none;width:clamp(260px,34vw,460px);aspect-ratio:16/9;border-radius:22px;overflow:hidden;background:var(--panel)}
.card img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;will-change:transform}
.card b{position:absolute;left:12px;bottom:12px;background:rgba(10,10,12,.78);backdrop-filter:blur(10px);border-radius:999px;padding:6px 14px;font-weight:600;font-size:14px}
.gal small{display:block;margin:26px auto 0;max-width:34em;padding:0 20px;color:var(--soft);font-size:15px}
.gal small a{text-decoration:underline;text-underline-offset:3px}
/* faq */
.faq{max-width:1000px;margin:0 auto;padding:140px 20px 20px}
.faq h2{margin:0 0 34px;font-weight:600;font-size:clamp(28px,3vw,40px);letter-spacing:-.035em}
.faq dl{margin:0}.qa{display:grid;grid-template-columns:1fr 1.4fr;gap:24px;padding:24px 0;border-top:1px solid var(--line)}
.qa dt{font-weight:400;font-size:clamp(20px,2vw,26px);line-height:1.15;letter-spacing:-.03em}
.qa dd{margin:0;color:var(--soft);font-size:clamp(16px,1.4vw,19px);line-height:1.4;letter-spacing:-.025em}
/* final */
.final{padding:140px 20px 160px;text-align:center;will-change:transform}
.final h2{margin:0;font-weight:600;font-size:clamp(25px,3vw,40px);letter-spacing:-.035em}
.final p{margin:12px auto 0;color:var(--soft);font-size:clamp(17px,1.5vw,20px)}
footer{padding:30px 20px 50px;text-align:center;color:var(--dim);font-size:13px;border-top:1px solid var(--line)}
footer a{margin:0 10px}footer a:hover{color:var(--text)}footer p{margin:14px auto 0;max-width:46em}
/* scroll reveal: only hidden when the script is running, so the page is complete without it */
.js [data-reveal]{opacity:0;transform:translateY(30px);filter:blur(8px);transition:opacity .9s var(--e) var(--d,0ms),transform .9s var(--e) var(--d,0ms),filter .9s var(--e) var(--d,0ms)}
.js [data-reveal].in{opacity:1;transform:none;filter:none}
@media (max-width:760px){.hero{height:auto;min-height:0;padding:78px 16px 20px;text-align:center}.copy{position:static;text-align:center;pointer-events:auto;margin-bottom:18px}.copy .chip{display:none}.hero:has(.frame[data-phase=vr]) .copy{opacity:1;transform:none}.hero h1{font-size:clamp(32px,9vw,46px)}.frame{height:clamp(300px,calc(100svh - 280px),560px);border-radius:22px}.frame:after{height:35%}.qa{grid-template-columns:1fr;gap:8px}.nbtn.hide{display:none}.pbtn{min-width:150px}.chip{font-size:15px}}
@media (prefers-reduced-motion:reduce){.pbtn span,.bar b,.say u,.hint svg{animation:none}.pbtn span:first-child{opacity:1}.bar b{width:64%}.nav{transition:none}}
"""

I_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4.05C4 1.62 6.72.16 8.75 1.52l11.82 7.9c1.8 1.2 1.8 3.85 0 5.07L8.75 22.46C6.73 23.82 4 22.37 4 19.93z"/></svg>'
I_PADDLE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 6h10a5 5 0 0 1 4.8 6.4l-1.1 4A3 3 0 0 1 15.4 17l-.6-1.5H9.2L8.6 17a3 3 0 0 1-5.3-.6l-1.1-4A5 5 0 0 1 7 6Zm.5 3.2v1.3H6.2v1.5h1.3v1.3H9V12h1.3v-1.5H9V9.2Zm8 .3a1 1 0 1 0 0 2 1 1 0 0 0 0-2Zm2 2a1 1 0 1 0 0 2 1 1 0 0 0 0-2Z"/></svg>'
I_VR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7.5C3 6.1 4.1 5 5.5 5h13C19.9 5 21 6.1 21 7.5v7c0 1.4-1.1 2.5-2.5 2.5h-3.2c-.7 0-1.3-.4-1.7-1l-.6-1c-.4-.6-1.4-.6-1.8 0l-.6 1c-.4.6-1 1-1.7 1H5.5A2.5 2.5 0 0 1 3 14.5Zm5.2 2a2.3 2.3 0 1 0 0 4.6 2.3 2.3 0 0 0 0-4.6Zm7.6 0a2.3 2.3 0 1 0 0 4.6 2.3 2.3 0 0 0 0-4.6Z"/></svg>'
I_WIN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 4.2 10.4 3v8.2H2Zm9.4-1.3L22 1.5v9.7H11.4ZM2 12.3h8.4v8.2L2 19.3Zm9.4 0H22v9.7l-10.6-1.4Z"/></svg>'
I_OK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.5 16.6 5.4 12.5l-1.4 1.4 5.5 5.5L20.4 8.5 19 7.1Z"/></svg>'
I_DOWN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" stroke-linecap="round" stroke-linejoin="round"/></svg>'

FAQ = [
    ("What does<br>Plunge do?", "It makes the games you own playable in VR. An AI coding agent works out how, and Plunge installs the result into your own copy with one click."),
    ("Do I need<br>the games?", "Yes. Plunge never includes or shares game files. It changes the copy you already own, and you can undo it."),
    ("Does every<br>game work?", "No. Some games work well in VR and some do not, and results vary. Games with anti-cheat are left alone."),
    ("What does Play<br>actually do?", "It installs the VR build, starts the game and checks that it really started. Uninstall puts every file back the way it was."),
    ("Can I<br>play together?", "Only if the game or the build has online play. Plunge doesn't add multiplayer to a single-player game. Where it exists, press Host to get a short join code and send it to friends."),
    ("Can I make<br>my own?", "Yes. Plunge hands a brief to the AI agent you already use, such as Claude Code or Codex. It builds the VR version and you can share it."),
    ("Is it<br>safe?", "Plunge asks before it installs anything, backs up the files it changes, and checks community builds for dangerous files first."),
    ("What does it<br>cost?", "Plunge is free. You pay for your own AI agent if you use one."),
]

GAMES = [("veloren-sunset", "Veloren"), ("xonotic", "Xonotic"), ("supertuxkart", "SuperTuxKart"), ("0ad", "0 A.D."), ("minetest", "Luanti"), ("veloren-horizon", "Veloren")]


def page(download_url, version, footer_links):
    ok = bool(download_url)
    nav_dl = ('<a class="nbtn blue" href="%s" rel="noopener">Download</a>' % html.escape(download_url)) if ok else '<span class="nbtn blue off">Coming soon</span>'
    big_dl = ('<a class="btn" href="%s" rel="noopener">Download Plunge</a>' % html.escape(download_url)) if ok else '<span class="btn off">Download coming soon</span>'
    faq = "".join('<div class="qa" data-reveal><dt>%s</dt><dd>%s</dd></div>' % (q, a) for q, a in FAQ)
    cards = "".join('<div class="card" data-card><img src="/img/%s.jpg" alt="Screenshot of %s" loading="lazy" decoding="async" width="1280" height="720"><b>%s</b></div>' % (s, n, n) for s, n in GAMES)
    free = '<span class="free">Free for %s Windows.</span>' % I_WIN
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Plunge VR: play any game in VR</title>'
            '<meta name="description" content="Plunge turns the games you own into VR games, in one click.">'
            '<meta name="color-scheme" content="dark"><meta name="theme-color" content="#050506">'
            '<link rel="icon" href="/plunge.png"><link rel="preload" href="/fonts/inter.woff2" as="font" type="font/woff2" crossorigin>'
            '<style>%(css)s</style></head><body><div class="prog" data-progress></div>'
            '<header class="nav"><a class="logo" href="/" aria-label="Plunge">%(lm)s%(lw)s</a>'
            '<nav class="navr"><a class="nbtn" href="/account" data-signin>Sign in</a>%(navdl)s<a class="nbtn hide" href="#faq">FAQ</a></nav></header>'
            '<main>'
            '<section class="hero"><div class="copy"><div class="chip"><span class="ic">%(pad)s</span><span class="pl">+</span><span class="ic b">%(vr)s</span>Any game</div><h1>Play any game<br><span class="pillbig">%(play)s in VR</span></h1></div>'
            '<div class="frame" data-hero-frame data-phase="flat" role="img" aria-label="A flat game screenshot that bends around you into a two-lens VR view">'
            '<canvas></canvas><div class="lens" aria-hidden="true"></div>'
            '<div class="tag"><span data-phase-label>Flat</span>Your game</div>'
            '<button type="button" class="skip" data-skip>Skip</button>'
            '<div class="hint" data-hint>Scroll to plunge %(down)s</div>'
            '</div></section>'
            '<section class="intro"><p data-words>Turn the games you own into <em>VR games.</em></p><div class="dl" data-reveal>%(bigdl)s%(free)s</div></section>'
            '<section class="gal" data-gallery><h2 data-reveal>From racing to strategy<br>Every kind of game</h2>'
            '<div class="track" data-track>%(cards)s</div>'
            '<small data-reveal>Screenshots of free, open-source games. Plunge works with the games you own. <a href="/credits">Credits</a></small></section>'
            '<section class="feat"><h2 data-reveal>Forget setup<br>Play in one click</h2>'
            '<div class="vis" data-live><div class="game"><i></i>Your game</div><div class="playrow"><div class="pbtn"><span>Play</span><span>Installing</span><span>Starting</span><span>Playing</span></div></div><div class="bar"><b></b></div></div>'
            '<p data-reveal><b>Just press Play.</b> Plunge installs what it needs and starts the game.</p></section>'
            '<section class="feat"><h2 data-reveal>Multiplayer<br>With a join code</h2>'
            '<div class="vis"><div class="link"><code>plunge://join/K7Q2MX</code><span class="copied">Link copied</span></div><div class="avs"><i>M</i><i>K</i><i>I</i><i>T</i><i>+3</i></div></div>'
            '<p data-reveal>For games and builds that have online play, hosting gives you a join code. Send it to friends, or open a public lobby.</p></section>'
            '<section class="feat"><h2 data-reveal>Create and share<br>With your AI</h2>'
            '<div class="vis" data-live><div class="agents"><span class="on">Claude Code</span><span>Codex</span><span>Gemini</span></div>'
            '<div class="say">Make this game playable in VR, seated, with smooth turning<u></u></div><div class="send">Send to agent</div></div>'
            '<p data-reveal>Give your coding agent Plunge\'s brief. It builds the VR version for you.</p></section>'
            '<section class="feat"><h2 data-reveal>Safe by design<br>Easy to undo</h2>'
            '<div class="vis"><div class="row">%(ok)s Backs up every file it changes</div><div class="row">%(ok)s Uninstall puts everything back</div><div class="row">%(ok)s Leaves games with anti-cheat alone</div></div>'
            '<p data-reveal>Plunge works on your own copy, and asks before it installs anything.</p></section>'
            '<section class="faq" id="faq"><h2 data-reveal>Frequently asked questions</h2><dl>%(faq)s</dl></section>'
            '<section class="final" data-final><h2>Safe and free</h2><p>Turn your own games into VR games.</p><div class="dl">%(bigdl)s%(free)s<span class="free">v%(ver)s</span></div></section>'
            '</main>'
            '<footer>%(links)s<p>Plunge is a free Windows app that turns games you own into VR games. You can create a Plunge account with an email address or Google; Plunge uses your email address and Google account ID only to create and recognise your account, and never posts or reads anything else. See the <a href="/privacy">Privacy Policy</a>.</p><p>Independent tool. Not made by or endorsed by any game publisher, Valve, Meta or Sony. Game names belong to their owners.</p></footer>'
            '<script type="module" src="/js/hero.js"></script><script type="module" src="/js/scroll.js"></script><script type="module" src="/js/nav.js"></script>'
            '</body></html>') % {"css": CSS, "navdl": nav_dl, "play": I_PLAY, "pad": I_PADDLE, "vr": I_VR, "down": I_DOWN, "bigdl": big_dl, "free": free,
                                 "ok": I_OK, "lm": _logo.mark(css_class="lm", uid="hn"), "lw": _logo.wordmark(css_class="lw"), "faq": faq, "ver": html.escape(version), "links": footer_links, "cards": cards}


ACCOUNT_CSS = """
.acct{max-width:480px;margin:0 auto;padding:130px 20px 80px}
.acct h1{margin:0 0 8px;font-weight:600;font-size:clamp(28px,5vw,38px);letter-spacing:-.035em}
.acct h2{margin:28px 0 10px;font-weight:600;font-size:18px;letter-spacing:-.02em}
.acct .muted{color:var(--soft);margin:0 0 18px;font-size:17px}.acct .tiny{color:var(--dim);font-size:13px;margin:12px 0 18px}.acct .tiny a{text-decoration:underline}
.ainput{width:100%;background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:14px 16px;color:var(--text);font:inherit;outline:0}
.ainput:focus{border-color:#4a4a52}.ainput.code{letter-spacing:.5em;text-align:center;font-size:26px;font-weight:700}
.abtn{display:inline-flex;align-items:center;justify-content:center;height:50px;padding:0 24px;border-radius:14px;border:0;background:var(--panel2);color:var(--text);font-weight:600;font-size:16px;cursor:pointer;margin:14px 10px 0 0}
.abtn.blue{background:var(--blue);color:#fff}.abtn.blue:hover{background:#2aa0ff}.abtn.danger{background:#3a1717;color:#ff9a9a}.abtn:disabled{opacity:.6;cursor:default}
.err{background:rgba(255,107,107,.12);color:#ff9a9a;border-radius:12px;padding:10px 14px;margin-top:12px;font-size:15px}
.list{display:grid;gap:8px}.row{display:flex;align-items:center;justify-content:space-between;gap:12px;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:12px 16px}
.row b{display:block}.row .muted{margin:0;font-size:14px}.row .abtn{height:38px;margin:0;padding:0 16px}
.actions{margin-top:26px}.acct .actions .abtn{margin-top:10px}`n.gsi{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;height:46px;background:#fff;color:#1f1f1f;border:1px solid #dadce0;border-radius:999px;font:500 15px/1 Inter,Arial,sans-serif;cursor:pointer;margin:0}.gsi:hover{background:#f6f7f8}.gsi:focus-visible{outline:2px solid #4285F4;outline-offset:2px}.or{display:flex;align-items:center;gap:12px;color:var(--dim);font-size:13px;margin:16px 0}.or:before,.or:after{content:"";flex:1;height:1px;background:var(--line)}`n.linkrow{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin:12px 2px 0}.alink{background:none;border:0;color:#8ab4ff;padding:0;font:inherit;font-size:14px;cursor:pointer;text-decoration:underline;text-underline-offset:3px}`n.acct .ainput+.ainput{margin-top:10px}
"""


def account_page(footer_links):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Your Plunge account</title><meta name="robots" content="noindex"><meta name="color-scheme" content="dark"><meta name="theme-color" content="#050506">'
            '<link rel="icon" href="/plunge.png"><link rel="preload" href="/fonts/inter.woff2" as="font" type="font/woff2" crossorigin>'
            '<style>%s%s</style></head><body>'
            '<header class="nav"><a class="logo" href="/" aria-label="Plunge">%s%s</a><nav class="navr"><a class="nbtn" href="/download">Download</a></nav></header>'
            '<main class="acct" data-account><h1>Account</h1><p class="muted">Loading…</p><noscript><p class="muted">Sign-in needs JavaScript turned on.</p></noscript></main>'
            '<footer>%s<p>Independent tool. Not made by or endorsed by any game publisher, Valve, Meta or Sony. Game names belong to their owners.</p></footer>'
            '<script type="module" src="/js/account.js"></script></body></html>') % (CSS, ACCOUNT_CSS, _logo.mark(css_class="lm", uid="ac"), _logo.wordmark(css_class="lw"), footer_links)