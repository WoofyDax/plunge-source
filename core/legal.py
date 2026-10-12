"""Open the bundled legal documents (Markdown in legal/) as a readable page in the default browser."""
import html
import os
import re

from . import paths

DOCS = {
    "terms": ("Terms of Use", "TERMS.md"),
    "privacy": ("Privacy Policy", "PRIVACY.md"),
    "copyright": ("Copyright and Takedown Policy", "COPYRIGHT.md"),
    "guidelines": ("Community Guidelines", "GUIDELINES.md"),
    "notices": ("Third-Party Notices", "NOTICES.md"),
}
CSS = ("body{font:16px/1.6 system-ui,Segoe UI,sans-serif;background:#141414;color:#f4f4f5;max-width:760px;margin:40px auto;padding:0 20px}"
       "h1,h2,h3{letter-spacing:-.02em}h1{font-size:34px}h2{margin-top:2em}a{color:#3a9fff}li{margin:.3em 0}"
       "code{background:#28282b;padding:1px 6px;border-radius:6px}.draft{background:#3a2e12;border-radius:12px;padding:12px 16px}")


def render(md):
    """Small, safe Markdown subset: #/##/### headings, '- ' lists, **bold**, `code`, [text](https://link)."""
    out, in_list = [], False

    def inline(t):
        t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
        return re.sub(r"\[([^\]]+)\]\((https://[^)\s]+)\)", r'<a href="\2">\1</a>', t)

    for line in md.splitlines():
        s = line.rstrip()
        m = re.match(r"^(#{1,3}) (.+)", s)
        if s.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>%s</li>" % inline(s[2:]))
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if m:
            out.append("<h%d>%s</h%d>" % (len(m.group(1)), inline(m.group(2)), len(m.group(1))))
        elif s.startswith("> "):
            out.append('<p class="draft">%s</p>' % inline(s[2:]))
        elif s:
            out.append("<p>%s</p>" % inline(s))
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def open_doc(name):
    if name not in DOCS:
        raise ValueError("unknown document")
    title, fname = DOCS[name]
    src = paths.resource("legal/" + fname)
    body = render(src.read_text(encoding="utf-8"))
    dest = paths.DATA / "legal-cache" / (name + ".html")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text('<!doctype html><meta charset="utf-8"><title>%s</title><style>%s</style>%s' % (html.escape(title), CSS, body),
                    encoding="utf-8")
    os.startfile(str(dest))
    return {"ok": True}
