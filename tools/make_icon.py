"""Generate assets/plunge.ico (dev tool; needs Pillow). A bold white P on a blue rounded square."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "assets"
OUT.mkdir(exist_ok=True)
S = 1024


def font(size):
    for f in ("seguibl.ttf", "arialbd.ttf", "segoeuib.ttf"):
        try:
            return ImageFont.truetype("C:/Windows/Fonts/" + f, size)
        except OSError:
            continue
    return ImageFont.load_default()


img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
# dark rounded square with a subtle edge
sq = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sq).rounded_rectangle([40, 40, S - 40, S - 40], radius=230, fill=(24, 24, 27, 255), outline=(58, 58, 64, 255), width=10)
img.alpha_composite(sq)
# a bold "P" filled with a blue gradient
f = font(760)
glyph = Image.new("L", (S, S), 0)
gd = ImageDraw.Draw(glyph)
bbox = gd.textbbox((0, 0), "P", font=f)
w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
gd.text(((S - w) / 2 - bbox[0], (S - h) / 2 - bbox[1] - 10), "P", font=f, fill=255)
fill = Image.new("RGBA", (S, S))
fd = ImageDraw.Draw(fill)
for y in range(S):
    t = y / S
    fd.line([(0, y), (S, y)], fill=(int(90 - 70 * t), int(185 - 50 * t), 255, 255))
img.paste(fill, (0, 0), glyph)
img.save(OUT / "plunge.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.resize((256, 256), Image.LANCZOS).save(OUT / "plunge.png")
print("wrote", OUT / "plunge.ico")
