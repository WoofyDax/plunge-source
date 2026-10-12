"""Regenerate every logo file from tools/logo_svg.py (dev tool; needs Pillow and Microsoft Edge for the PNG render).

Writes assets/logo-mark.svg, assets/logo-wordmark.svg, assets/logo.svg, assets/plunge.png and assets/plunge.ico,
and updates the inline logo in ui/index.html (the app's top bar).
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import logo_svg as L  # noqa: E402

A = ROOT / "assets"
A.mkdir(exist_ok=True)
NS = ' xmlns="http://www.w3.org/2000/svg"'
(A / "logo-mark.svg").write_text(L.mark(uid="m").replace("<svg", "<svg" + NS, 1) + "\n", encoding="utf-8")
(A / "logo-wordmark.svg").write_text(L.wordmark().replace("<svg", "<svg" + NS, 1).replace("currentColor", "#ffffff") + "\n", encoding="utf-8")
(A / "logo.svg").write_text(L.full() + "\n", encoding="utf-8")

# render the mark to a transparent PNG with Edge, then build the icon sizes from it
EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if Path(p).exists()), None)
if EDGE:
    tmp = Path(tempfile.mkdtemp())
    page = tmp / "m.html"
    page.write_text('<!doctype html><html><body style="margin:0;background:transparent">%s</body></html>' % L.mark(size=512, uid="r"), encoding="utf-8")
    png = tmp / "m.png"
    subprocess.run([EDGE, "--headless=old", "--disable-gpu", "--hide-scrollbars", "--default-background-color=00000000", "--window-size=512,512",
                    "--screenshot=%s" % png, page.as_uri()], check=True, capture_output=True, timeout=60)
    img = Image.open(png).convert("RGBA")
    img.save(A / "plunge.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.resize((256, 256), Image.LANCZOS).save(A / "plunge.png")
    print("wrote icon and png from", img.size)
else:
    print("Edge not found: SVGs written, PNG/ICO not regenerated")

# the app's top bar
idx = ROOT / "ui" / "index.html"
html = idx.read_text(encoding="utf-8")
brand = '<div class="wordmark" aria-label="Plunge">%s%s</div>' % (L.mark(css_class="wm-mark", uid="app"), L.wordmark(css_class="wm-word"))
html = re.sub(r'<div class="wordmark"[^>]*>.*?</div>', lambda m: brand, html, count=1, flags=re.S)
idx.write_text(html, encoding="utf-8")
print("done")
