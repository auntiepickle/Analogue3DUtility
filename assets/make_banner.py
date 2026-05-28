"""Generate assets/banner.png for the Analogue 3D Utility.

Original art (no third-party/Analogue assets): a black-gold header with an N64
cartridge seated in a cartridge console, the wordmark, a UTILITY pill, and green
status dots. Run `python assets/make_banner.py` to regenerate the PNG.
"""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 820, 230
SS = 4  # supersample, then downscale, for smooth edges

BLACK = (10, 10, 10)
FRAME = (31, 31, 31)
DARK = (28, 28, 28)
BEVEL = (38, 38, 38)
GOLD = (244, 205, 1)
LABELBG = (20, 20, 20)
GREEN = (74, 222, 128)
GREY = (154, 154, 154)
VENT = (60, 60, 60)

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

f_word = font(BOLD, 54)
f_pill = font(BOLD, 15)
f_label = font(MONO, 14)
f_ver = font(MONO, 13)
f_3d = font(BOLD, 15)


def rr(x0, y0, x1, y1, r, fill=None, outline=None, width=1):
    d.rounded_rectangle([s(x0), s(y0), s(x1), s(y1)], radius=s(r),
                        fill=fill, outline=outline, width=s(width) if outline else 0)


def dot(cx, cy, r, fill):
    d.ellipse([s(cx - r), s(cy - r), s(cx + r), s(cy + r)], fill=fill)


# frame
d.rounded_rectangle([s(3), s(3), s(W - 3), s(H - 3)], radius=s(8), outline=FRAME, width=s(2))

# console + cartridge
ox, oy = 64, 60
rr(ox, oy + 48, ox + 150, oy + 126, 12, fill=DARK, outline=GOLD, width=3)
rr(ox + 8, oy + 52, ox + 142, oy + 63, 5, fill=BEVEL)
rr(ox + 44, oy + 44, ox + 106, oy + 54, 2, fill=(0, 0, 0))
for vy in (96, 104, 112):
    d.line([s(ox + 116), s(oy + vy), s(ox + 138), s(oy + vy)], fill=VENT, width=s(2))
dot(ox + 20, oy + 108, 4.5, GREEN)
d.text((s(ox + 38), s(oy + 99)), "3D", font=f_3d, fill=GOLD)
rr(ox + 40, oy + 4, ox + 110, oy + 22, 4, fill=GOLD)
rr(ox + 46, oy - 8, ox + 104, oy + 52, 5, fill=GOLD)
rr(ox + 55, oy + 1, ox + 95, oy + 46, 3, fill=LABELBG)
for (px, py) in [(60, 7), (75, 7), (67, 21), (60, 35), (82, 35)]:
    rr(ox + px, oy + py, ox + px + 9, oy + py + 9, 1, fill=GOLD)

# wordmark
wx = 250
d.text((s(wx), s(40)), "ANALOGUE 3D", font=f_word, fill=GOLD)

# UTILITY pill
px0, py0, pw, ph = wx + 2, 118, 150, 32
rr(px0, py0, px0 + pw, py0 + ph, ph / 2, fill=GOLD)
t = "U T I L I T Y"
bb = d.textbbox((0, 0), t, font=f_pill)
d.text((s(px0 + pw / 2) - (bb[2] - bb[0]) / 2, s(py0 + 8)), t, font=f_pill, fill=BLACK)

# status dots
for label, x in [("firmware", 252), ("art packs", 366), ("saves", 500), ("8BitDo 64", 596)]:
    dot(x, 188, 5, GREEN)
    d.text((s(x + 12), s(182)), label, font=f_label, fill=GREY)

# version tag
vbb = d.textbbox((0, 0), "v1.0", font=f_ver)
d.text((s(W - 30) - (vbb[2] - vbb[0]), s(28)), "v1.0", font=f_ver, fill=(85, 85, 85))

final = img.resize((W * 2, H * 2), Image.LANCZOS)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banner.png")
final.save(out)
print("wrote", out, final.size)
