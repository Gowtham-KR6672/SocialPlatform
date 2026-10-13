"""Regenerate the Android and iOS app icons, splash screens and the Play Store icon.

Sources in resources/:
  icon-1024.png  square app icon, no transparency (iOS and Android round the corners themselves)
  mark.png       the "S" on a transparent background (Android adaptive icon foreground)
  wordmark.png   the SOLO wordmark on a transparent background (splash screens)

Run from the mobile/ folder:  python resources/make_icons.py"""
import glob, os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CREAM = (254, 248, 236, 255)    # icon background; same as android/.../values/ic_launcher_background.xml


def art(name):
    im = Image.open(os.path.join(HERE, name)).convert("RGBA")
    return im.crop(im.getbbox())                        # trim transparent margins


icon = Image.open(os.path.join(HERE, "icon-1024.png")).convert("RGB")
mark, word = art("mark.png"), art("wordmark.png")


def placed(img, size, frac, bg):
    """Canvas with img centred, its longest side = frac of the canvas's shorter side."""
    w, h = size
    im = Image.new("RGBA", size, bg)
    s = frac * min(w, h) / max(img.size)
    lg = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
    im.alpha_composite(lg, ((w - lg.width) // 2, (h - lg.height) // 2))
    return im


def shaped(px, round_):
    """The square icon with a circle or rounded-square mask (older Android launchers)."""
    big = px * 4
    mask = Image.new("L", (big, big), 0)
    if round_:
        ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    else:
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.2), fill=255)
    im = icon.resize((px, px), Image.LANCZOS).convert("RGBA")
    im.putalpha(mask.resize((px, px), Image.LANCZOS))
    return im


res = os.path.join(ROOT, "android", "app", "src", "main", "res")
for d, px in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
    folder = os.path.join(res, f"mipmap-{d}")
    shaped(px, False).save(os.path.join(folder, "ic_launcher.png"))
    shaped(px, True).save(os.path.join(folder, "ic_launcher_round.png"))
    # adaptive icon foreground: 108dp canvas, the S inside the 66dp safe zone
    fg = round(px * 108 / 48)
    placed(mark, (fg, fg), 0.47, (0, 0, 0, 0)).save(os.path.join(folder, "ic_launcher_foreground.png"))

for path in glob.glob(os.path.join(res, "drawable*", "splash.png")):
    w, h = Image.open(path).size
    placed(word, (w, h), 0.5 if w < h else 0.42, CREAM).convert("RGB").save(path)

ios = os.path.join(ROOT, "ios", "App", "App", "Assets.xcassets")
icon.save(os.path.join(ios, "AppIcon.appiconset", "AppIcon-512@2x.png"))   # App Store requires no transparency
for path in glob.glob(os.path.join(ios, "Splash.imageset", "*.png")):
    w, h = Image.open(path).size
    placed(word, (w, h), 0.22, CREAM).convert("RGB").save(path)

icon.resize((512, 512), Image.LANCZOS).save(os.path.join(HERE, "store", "play-icon-512.png"))
print("icons and splash screens written")
