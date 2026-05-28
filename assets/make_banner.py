"""Generate assets/banner.png for the Analogue 3D Utility.

Original art (no third-party/Analogue assets): a clean "terminal window" header -
the tool's gold wordmark on a dark framed panel with a title bar and green status
dots. Run `python assets/make_banner.py` to regenerate the PNG.
"""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 820, 230
SS = 4

BLACK = (10, 10, 10)
PANEL = (18, 18, 18)
BORDER = (42, 42, 42)
DIVIDER = (38, 38, 38)
GOLD = (244, 205, 1)
GREEN = (74, 222, 128)
GREY = (150, 150, 150)
DIMGREY = (110, 110, 110)
DOTGREY = (70, 70, 70)

w, h = W * SS, H * SS
img = Image.new("RGB", (w, h), BLACK)
d = ImageDraw.Draw(img)


def s(v):
    return int(v * SS)


def font(candidates, size):
    for p in candidates:
        try:
            return ImageFont.truetype(p, s(size))
        except OSError:
            continue
    return ImageFont.load_default()


BOLD = ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
MONO = ["C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/cour.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
MONOB = ["C:/Windows/Fonts/consolab.ttf", "C:/Windows/Fonts/courbd.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"]

f_word = font(BOLD, 52)
f_pill = font(BOLD, 15)
f_bar = font(MONO, 14)
f_label = font(MONO, 14)
f_prompt = font(MONOB, 15)


def rr(x0, y0, x1, y1, r, fill=None, outline=None, width=1):
    d.rounded_rectangle([s(x0), s(y0), s(x1), s(y1)], radius=s(r),
                        fill=fill, outline=outline, width=s(width) if outline else 0)


def dot(cx, cy, r, fill):
    d.ellipse([s(cx - r), s(cy - r), s(cx + r), s(cy + r)], fill=fill)


# terminal window panel
rr(20, 18, 800, 212, 14, fill=PANEL, outline=BORDER, width=2)
# title bar + divider
d.line([s(20), s(54), s(800), s(54)], fill=DIVIDER, width=s(2))
dot(44, 36, 5, GOLD)
dot(64, 36, 5, DOTGREY)
dot(84, 36, 5, DOTGREY)
d.text((s(108), s(28)), "a3d.py", font=f_bar, fill=DIMGREY)

# a faint shell prompt above the wordmark, for the terminal feel
d.text((s(52), s(72)), "> ", font=f_prompt, fill=GREEN)
d.text((s(72), s(72)), "analogue 3d utility", font=f_prompt, fill=DIMGREY)

# wordmark
d.text((s(50), s(92)), "ANALOGUE 3D", font=f_word, fill=GOLD)

# UTILITY pill
px0, py0, pw, ph = 54, 150, 150, 30
rr(px0, py0, px0 + pw, py0 + ph, ph / 2, fill=GOLD)
t = "U T I L I T Y"
bb = d.textbbox((0, 0), t, font=f_pill)
d.text((s(px0 + pw / 2) - (bb[2] - bb[0]) / 2, s(py0 + 7)), t, font=f_pill, fill=BLACK)

# status dots
for label, x in [("firmware", 240), ("art packs", 360), ("saves", 500), ("8BitDo 64", 600)]:
    dot(x, 166, 5, GREEN)
    d.text((s(x + 12), s(160)), label, font=f_label, fill=GREY)

final = img.resize((W * 2, H * 2), Image.LANCZOS)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banner.png")
final.save(out)
print("wrote", out, final.size)
