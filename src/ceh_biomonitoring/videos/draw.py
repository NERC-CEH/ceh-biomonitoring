"""Drawing on frames: text, labelled boxes and track trails, in the toolkit's colours (Arial where the
computer has it)."""
from __future__ import annotations

import hashlib
from functools import lru_cache

from PIL import ImageDraw, ImageFont

# the reports' colours (reporting/html.py STYLE), brightest first so boxes stand out on photos
TRACK_COLOURS = ["#f4c03d", "#67ccea", "#e76124", "#4db264", "#cfbcd5", "#477AE2", "#ffffff", "#ff8fa3"]
OTHER_INSECT = "#bdbdbd"
NAVY = "#133b64"
CAVEAT = "Names are suggestions from computer models, not checked by an expert"


@lru_cache(maxsize=16)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = ["arialbd.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf"]
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    try:
        from matplotlib import font_manager
        return ImageFont.truetype(font_manager.findfont("DejaVu Sans" + (":bold" if bold else "")), size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def colour_for(key: str) -> str:
    """The same track always gets the same colour."""
    return TRACK_COLOURS[int(hashlib.md5(str(key).encode()).hexdigest(), 16) % len(TRACK_COLOURS)]


def label(d: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, colour: str, size: int = 16,
          above: bool = True) -> None:
    """Text on a dark tab, so it reads on any photo."""
    f = font(size)
    x, y = xy
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    w, h = r - l + 8, b - t + 6
    y0 = y - h if above else y
    if y0 < 0:
        y0 = y
    d.rectangle([x, y0, x + w, y0 + h], fill=(0, 0, 0, 190))
    d.text((x + 4, y0 + 3 - t), text, font=f, fill=colour)


def bar(d: ImageDraw.ImageDraw, width: int, y: int, height: int, left: str, right: str = "", size: int = 18) -> None:
    d.rectangle([0, y, width, y + height], fill=NAVY)
    f = font(size)
    d.text((12, y + (height - size) // 2 - 1), left, font=f, fill="white")
    if right:
        w = d.textlength(right, font=f)
        d.text((width - 12 - w, y + (height - size) // 2 - 1), right, font=f, fill="white")
