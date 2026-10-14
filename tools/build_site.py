"""Build the static website for plungevr.com into site/ (landing page, download page, legal pages, latest.json, security.txt).

    python tools/build_site.py                      # download button says "coming soon"
    python tools/build_site.py --download-url https://github.com/<you>/plunge/releases/latest

The output is plain files: host it on Cloudflare Pages, Vercel, Netlify or any web server. No scripts, no cookies, no trackers.
"""
import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.version import VERSION  # noqa: E402
import logo_svg  # noqa: E402

DOMAIN = "plungevr.com"
PAGES = [("terms", "Terms of Use", "TERMS.md"), ("privacy", "Privacy Policy", "PRIVACY.md"), ("copyright", "Copyright and Takedowns", "COPYRIGHT.md"),
         ("guidelines", "Community Guidelines", "GUIDELINES.md"), ("notices", "Third-Party Notices", "NOTICES.md")]

CSS = """
:root{--bg:#141414;--card:#1e1e1e;--text:#f2f2f2;--muted:#a0a0a8;--blue:#4c8dff;--line:#2c2c30}
@media (prefers-color-scheme:light){:root{--bg:#f6f6f8;--card:#fff;--text:#16161a;--muted:#5d5d66;--line:#e1e1e6}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--blue)}header,main,footer{max-width:760px;margin:0 auto;padding:0 16px}
header{display:flex;align-items:center;gap:10px;padding-top:20px;padding-bottom:20px}
header a{color:var(--text);text-decoration:none;font-weight:700;font-size:20px;display:flex;align-items:center;gap:10px}
header .lm{width:32px;height:32px}header .lw{height:20px;width:auto}
.hero{padding:56px 0 28px}h1{font-size:clamp(34px,7vw,56px);line-height:1.1;margin:0 0 14px;letter-spacing:-.02em}
.lead{font-size:20px;color:var(--muted);margin:0 0 26px}
.btn{display:inline-block;background:var(--blue);color:#fff;text-decoration:none;font-weight:600;padding:13px 22px;border-radius:14px}
.btn.off{background:var(--line);color:var(--muted);pointer-events:none}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));margin:30px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px}.card h3{margin:0 0 6px;font-size:17px}.card p{margin:0;color:var(--muted);font-size:15px}
.note{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;color:var(--muted);font-size:15px}
footer{padding-top:30px;padding-bottom:40px;color:var(--muted);font-size:14px;border-top:1px solid var(--line);margin-top:40px}footer a{color:var(--muted);margin-right:14px}
.legal h1{font-size:32px}.legal blockquote{margin:0 0 18px;padding:10px 14px;border-left:3px solid var(--blue);background:var(--card);border-radius:8px;color:var(--muted)}
"""


def md(text):
    """A small, safe Markdown converter for our own documents: headings, lists, quotes, bold, italic, links, paragraphs."""
    def inline(s):
        s = html.escape(s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+|mailto:[^)\s]+)\)", r'<a href="\2" rel="noopener">\1</a>', s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    out, para, lst = [], [], None

    def flush():
        nonlocal para, lst
        if para:
            out.append("<p>%s</p>" % inline(" ".join(para)))
            para = []
        if lst:
            out.append("<%s>%s</%s>" % (lst[0], "".join("<li>%s</li>" % inline(i) for i in lst[1]), lst[0]))
            lst = None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^(#{1,4})\s+(.*)", s)
        b = re.match(r"^[-*]\s+(.*)", s)
        n = re.match(r"^\d+[.)]\s+(.*)", s)
        if not s:
            flush()
        elif m:
            flush()
            out.append("<h%d>%s</h%d>" % (len(m.group(1)), inline(m.group(2)), len(m.group(1))))
        elif s.startswith(">"):
            flush()
            out.append("<blockquote>%s</blockquote>" % inline(s.lstrip("> ")))
        elif b or n:
            kind = "ul" if b else "ol"
            if not lst or lst[0] != kind:
                flush()
                lst = (kind, [])
            lst[1].append((b or n).group(1))
        else:
            if lst:
                flush()
            para.append(s)
    flush()
    return "\n".join(out)


def page(title, body, desc="", cls=""):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title><meta name="description" content="%s"><meta name="color-scheme" content="dark light">'
            '<link rel="icon" href="/plunge.png"><style>%s</style></head><body>'
            '<header><a href="/" aria-label="Plunge">%s%s</a></header>'
            '<main class="%s">%s</main>'
            '<footer><a href="/terms">Terms</a><a href="/privacy">Privacy</a><a href="/copyright">Copyright</a><a href="/guidelines">Guidelines</a>'
            '<a href="/notices">Notices</a><p>Plunge is not made by or endorsed by any game publisher, Valve, Meta or Sony. All game names belong to their owners.</p></footer>'
            '</body></html>') % (html.escape(title), html.escape(desc), CSS, logo_svg.mark(css_class="lm", uid="lg"), logo_svg.wordmark(css_class="lw"), cls, body)


def build(download_url, installer=None):
    out = ROOT / "site"
    if out.exists():
        shutil.rmtree(out)
    (out / ".well-known").mkdir(parents=True)
    shutil.copy(ROOT / "assets" / "plunge.png", out / "plunge.png")
    sha = size = fname = None
    if installer and Path(installer).is_file():                  # host the installer itself, so the link never depends on another service
        import hashlib
        fname = Path(installer).name
        (out / "download").mkdir(exist_ok=True)
        shutil.copy(installer, out / "download" / fname)
        data = Path(installer).read_bytes()
        sha, size = hashlib.sha256(data).hexdigest(), len(data)
        download_url = "https://%s/download/%s" % (DOMAIN, fname)
    ok = bool(download_url)
    btn = '<a class="btn" href="%s" rel="noopener">Download for Windows</a>' % html.escape(download_url) if ok else '<span class="btn off">Download: coming soon</span>'
    shutil.copytree(ROOT / "web" / "vendor", out / "vendor")
    (out / "js").mkdir()
    for js in ("hero.js", "scroll.js", "nav.js", "account.js", "join.js"):
        shutil.copy(ROOT / "web" / js, out / "js" / js)
    shutil.copytree(ROOT / "web" / "img", out / "img")
    import site_home
    (out / "fonts").mkdir()
    shutil.copy(ROOT / "ui" / "fonts" / "inter.woff2", out / "fonts" / "inter.woff2")
    links = "".join('<a href="/%s">%s</a>' % (s, n.replace(" of Use", "")) for s, n, _ in PAGES[:4]) + '<a href="/credits">Credits</a>'
    (out / "index.html").write_text(site_home.page(download_url, VERSION, links), encoding="utf-8")
    (out / "join").mkdir()
    jbody = ('<h1>You\u2019re invited to play in VR</h1><p>A friend opened a Plunge game and sent you this link.</p>'
             '<p>Join code: <b id="jcode"></b></p>'
             '<p><a class="btn" id="jopen" href="#">Open in Plunge</a></p>'
             '<p id="jmsg" class="muted"></p>'
             '<p>You need Plunge and your own copy of the game. Don\u2019t have Plunge yet? <a href="/download">Get it here</a>.</p>'
             '<script src="/js/join.js"></script>')
    (out / "join" / "index.html").write_text(page("Join a Plunge game", jbody, "Open a friend\u2019s invite in Plunge", "legal"), encoding="utf-8")
    (out / "_redirects").write_text("/join/*  /join/index.html  200\n", encoding="utf-8")
    (out / "account").mkdir()
    (out / "account" / "index.html").write_text(site_home.account_page(links), encoding="utf-8")
    dl = ('<h1>Download Plunge</h1><p>%s</p><h2>Install</h2><ol><li>Run the installer.</li><li>If Windows shows a blue "Windows protected your PC" screen, '
          'Plunge may not be signed yet: choose <em>More info</em>, then <em>Run anyway</em> only if you downloaded it from this site.</li>'
          '<li>Open Plunge and pick a game.</li></ol><h2>You will also need</h2><ul><li>A VR headset set up on your PC.</li>'
          '<li>An AI coding agent such as Claude Code or Codex, with its own subscription. Plunge opens yours; it does not include one.</li></ul>'
          '<p class="note">Games with anti-cheat are not modified. Always keep a backup of saves for games you care about.</p>') % btn
    if sha:
        dl += ('<h2>Check your download</h2><p>Plunge %s, %.1f MB. To be sure the file is exactly the one published here, run this in PowerShell and compare:</p>'
               '<p><code>Get-FileHash .\\%s -Algorithm SHA256</code></p><p>SHA-256: <code>%s</code></p>'
               '<p class="note">This early version is not code-signed yet, so Windows will warn you. That is expected; the checksum above is how you can be sure it is the real file.</p>') % (VERSION, size / 1048576, html.escape(fname), sha)
    (out / "download").mkdir(exist_ok=True)
    (out / "download" / "index.html").write_text(page("Download Plunge", dl, "Download Plunge for Windows"), encoding="utf-8")
    for slug, title, src in PAGES:
        f = ROOT / "legal" / src
        (out / slug).mkdir()
        (out / slug / "index.html").write_text(page(title, md(f.read_text(encoding="utf-8")), title, "legal"), encoding="utf-8")
    rows = ""
    for c in json.loads((ROOT / "web" / "credits.json").read_text(encoding="utf-8-sig")):
        rows += ('<li><b>%s</b>: screenshot by %s, <a href="%s" rel="noopener">%s</a>. Source: <a href="%s" rel="noopener">Wikimedia Commons</a>. Resized and compressed.</li>'
                 % (html.escape(c["game"]), html.escape(c["artist"][:120]), html.escape(c["licenseUrl"] or "#"), html.escape(c["license"]), html.escape(c["page"])))
    credits = ('<h1>Credits</h1><p>The game screenshots on the home page are from free, open-source games, used under the licences below. '
               'Plunge is not affiliated with these projects, and they are shown only as examples of different kinds of games.</p><h2>Screenshots</h2><ul>%s</ul>'
               '<h2>Software on this site</h2><ul><li><b>three.js</b>, MIT licence, &copy; the three.js authors (<a href="/vendor/three.LICENSE">licence text</a>).</li>'
               '<li><b>Inter</b> typeface, SIL Open Font License 1.1, &copy; The Inter Project Authors.</li></ul>') % rows
    (out / "credits").mkdir()
    (out / "credits" / "index.html").write_text(page("Credits", credits, "Credits for the screenshots and software used on this site", "legal"), encoding="utf-8")
    (out / "latest.json").write_text(json.dumps({"version": VERSION, "url": "https://%s/download" % DOMAIN, "notes": "", **({"sha256": sha, "size": size} if sha else {})}, indent=1) + "\n", encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: https://%s/sitemap.xml\n" % DOMAIN, encoding="utf-8")
    urls = [""] + ["download", "credits"] + [p[0] for p in PAGES]
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>\n' %
                                     "".join("<url><loc>https://%s/%s</loc></url>" % (DOMAIN, u) for u in urls), encoding="utf-8")
    (out / ".well-known" / "security.txt").write_text("Contact: mailto:security@%s\nPolicy: https://%s/guidelines\nPreferred-Languages: en\nExpires: 2027-10-01T00:00:00.000Z\n" % (DOMAIN, DOMAIN), encoding="utf-8")
    # headers: Cloudflare Pages / Netlify read _headers, Vercel reads vercel.json. No scripts are used anywhere, so scripts are fully blocked.
    sec = {"Content-Security-Policy": "default-src 'none'; img-src 'self'; font-src 'self'; script-src 'self'; connect-src https://hub.plungevr.com; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
           "Strict-Transport-Security": "max-age=31536000; includeSubDomains", "X-Content-Type-Options": "nosniff",
           "Referrer-Policy": "no-referrer", "Permissions-Policy": "camera=(), microphone=(), geolocation=()"}
    (out / "_headers").write_text("/*\n" + "".join("  %s: %s\n" % kv for kv in sec.items()) + "/latest.json\n  Cache-Control: public, max-age=300\n", encoding="utf-8")
    (out / "vercel.json").write_text(json.dumps({"cleanUrls": True, "trailingSlash": False,
                                                 "rewrites": [{"source": "/join/:code", "destination": "/join/index.html"}],
                                                 "headers": [{"source": "/(.*)", "headers": [{"key": k, "value": v} for k, v in sec.items()]}]}, indent=1) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--download-url", default="")
    ap.add_argument("--installer", default="", help="path to PlungeSetup-x.y.z.exe: it is copied into the site and linked, with its SHA-256")
    a = ap.parse_args()
    if a.download_url and not a.download_url.startswith("https://"):
        sys.exit("the download URL must start with https://")
    print("built", build(a.download_url, a.installer or None))
