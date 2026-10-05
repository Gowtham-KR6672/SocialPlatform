"""Regenerate the Android and iOS app icons and splash screens from resources/logo-1024.png.
Run from the mobile/ folder:  python resources/make_icons.py"""
import glob, os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
logo = Image.open(os.path.join(HERE, "logo-1024.png")).convert("RGBA")
logo = logo.crop(logo.getbbox())                      # trim transparent margins
SPLASH_BG = (247, 245, 254, 255)                      # same lavender as the site's login page


def placed(size, frac, bg):
    """Square canvas with the logo centred, its longest side = frac of the canvas."""
    w, h = size
    im = Image.new("RGBA", size, bg)
    s = frac * min(w, h) / max(logo.size)
    lg = logo.resize((max(1, int(logo.width * s)), max(1, int(logo.height * s))), Image.LANCZOS)
    im.alpha_composite(lg, ((w - lg.width) // 2, (h - lg.height) // 2))
    return im


res = os.path.join(ROOT, "android", "app", "src", "main", "res")
for d, px in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
    folder = os.path.join(res, f"mipmap-{d}")
    placed((px, px), 0.78, (255, 255, 255, 255)).convert("RGB").save(os.path.join(folder, "ic_launcher.png"))
    # round icon: same art, circular mask
    rnd = placed((px, px), 0.70, (255, 255, 255, 255))
    mask = Image.new("L", (px * 4, px * 4), 0)
    from PIL import ImageDraw
    ImageDraw.Draw(mask).ellipse((0, 0, px * 4 - 1, px * 4 - 1), fill=255)
    rnd.putalpha(mask.resize((px, px), Image.LANCZOS))
    rnd.save(os.path.join(folder, "ic_launcher_round.png"))
    # adaptive icon foreground: 108dp canvas, art inside the 66dp safe zone
    fg = round(px * 108 / 48)
    placed((fg, fg), 0.56, (0, 0, 0, 0)).save(os.path.join(folder, "ic_launcher_foreground.png"))

for path in glob.glob(os.path.join(res, "drawable*", "splash.png")):
    w, h = Image.open(path).size
    placed((w, h), 0.42 if w < h else 0.36, SPLASH_BG).convert("RGB").save(path)

ios = os.path.join(ROOT, "ios", "App", "App", "Assets.xcassets")
placed((1024, 1024), 0.80, (255, 255, 255, 255)).convert("RGB").save(
    os.path.join(ios, "AppIcon.appiconset", "AppIcon-512@2x.png"))       # App Store requires no transparency
for path in glob.glob(os.path.join(ios, "Splash.imageset", "*.png")):
    w, h = Image.open(path).size
    placed((w, h), 0.26, SPLASH_BG).convert("RGB").save(path)
print("icons and splash screens written")
