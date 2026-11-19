"""The ring light in LepiSense and AMI-mini photos: found in the photos themselves, night by night.

The ring light (its dark housing and the LED board inside) and the two screws beside it are in every
photo, and the detector keeps boxing them. They move a little whenever a unit is moved or knocked, so
one fixed mask doesn't fit a whole season. With `ring_light: auto` the pipeline:

1. reads 9 photos spread through each night, shrunk to 648 pixels wide;
2. in each, finds the largest dark, round blob, which is the housing. The threshold follows each
   photo's own contrast, so it works on grey, foggy nights too;
3. takes the night's ring as the place most of those photos agree on (stray finds are dropped). A night where it can't be seen uses the
   nearest night that it could;
4. removes only boxes on the ring itself:
       ring light     a big box centred on the housing (it, or most of it, boxed whole)
       light board    any box centred well inside the ring (parts of the LED board)
       screw          a small box on one of the two screws, 1.2 ring radii either side, level with it
   Insects sitting elsewhere on the ring, or anywhere else, are kept.

Each night's ring is written to <deployment>_ring_light.json, and <deployment>_ring_light_preview.jpg
shows the masks on up to 12 nights. Correct the JSON if a night is wrong and run again with
`--set ring_light=<that file>`. `cehbio mask rings --image <photos>` tries it on photos before a run.

These rules were set on the Farm 1 LepiSense units (2026: 182 of 185 nights found directly) and
checked by eye there. Look at the preview for your own units.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

WIDTH = 648                     # photos are shrunk to this width to look for the ring
PHOTOS_PER_NIGHT = 9
SCREW_OFFSET, SCREW_R = 1.2, 0.22         # in ring radii
RING_CENTRE, RING_MIN_SIZE, BOARD, SCREW_MAX_SIZE = 0.35, 0.4, 0.55, 0.45
DRAW_RING = 1.08                # the circle drawn on previews


def find_ring(image) -> tuple[float, float, float] | None:
    """(x, y, radius) of the ring housing in a PIL image, in its own pixels, or None."""
    import cv2
    W = image.width
    k = WIDTH / W
    g = np.asarray(image.convert("L").resize((WIDTH, max(1, round(image.height * k)))), dtype=np.float32)
    g = cv2.blur(g, (3, 3))
    bright, dark = np.percentile(g, 60), np.percentile(g, 0.5)
    if bright - dark < 25:                         # no contrast at all: fogged out
        return None
    mask = (g < dark + 0.45 * (bright - dark)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best = None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if min(h, w) < 40 or max(h, w) > 260 or not (0.75 < w / h < 1.33):
            continue                               # the housing is about 120-160 px across at this size
        if area / (h * w) < 0.25:
            continue
        score = area * (1 - abs(1 - w / h))
        if best is None or score > best[0]:
            best = (score, x + w / 2, y + h / 2, max(h, w) / 2)
    if best is None:
        return None
    _, x, y, r = best
    return x / k, y / k, r / k


def agree(a, b) -> bool:
    """Two finds of the same ring: centres within a tenth of its radius, sizes within 10%."""
    r = max(a[2], b[2])
    return abs(a[0] - b[0]) <= 0.1 * r and abs(a[1] - b[1]) <= 0.1 * r and abs(a[2] - b[2]) <= 0.1 * r


def night_ring(images) -> dict | None:
    """The ring for one night, from several of its photos. The ring doesn't move during a night, so the
    night's ring is where most photos agree; stray finds (half the housing seen through fog, a dark
    patch) agree with nothing and are dropped. With finds in two or more photos, at least two must agree."""
    finds = [f for f in (find_ring(im) for im in images) if f]
    if not finds:
        return None
    support = [[g for g in finds if agree(f, g)] for f in finds]
    best = max(support, key=len)
    if len(finds) >= 2 and len(best) < 2:
        return None
    x, y, r = np.median(np.array(best), axis=0)
    return {"x": round(float(x)), "y": round(float(y)), "r": round(float(r)), "photos_used": len(best),
            "photos_tried": len(images), "source": "found"}


def fill(rings: dict, nights: list[str]) -> dict:
    """Nights without a ring take the nearest night's."""
    import pandas as pd
    found = [n for n in nights if rings.get(n) and rings[n].get("source") == "found"] or \
        [n for n in nights if rings.get(n)]
    out = dict(rings)
    for n in nights:
        if not out.get(n) and found and n:
            near = min(found, key=lambda m: abs(pd.Timestamp(m) - pd.Timestamp(n)))
            out[n] = {**rings[near], "source": f"from {near}", "photos_used": 0}
    return out


def load(spec: str) -> dict:
    """A ring-light file: {night: {x, y, r}}, or one ring for every night: {"x":, "y":, "r":}."""
    data = json.loads(Path(spec).expanduser().read_text())
    if {"x", "y", "r"} <= set(data):
        return {"*": {**data, "source": "given"}}
    return {k: {**v, "source": v.get("source", "given")} for k, v in data.items() if isinstance(v, dict)}


def for_night(rings: dict, night: str) -> dict | None:
    return rings.get(night) or rings.get("*")


def part(box, ring: dict | None) -> str | None:
    """Which part of the ring a box is on: 'ring light', 'light board', 'screw', or None (keep it)."""
    if not ring:
        return None
    x0, y0, x1, y1 = box
    x, y, R = ring["x"], ring["y"], ring["r"]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    size = max(x1 - x0, y1 - y0)
    dist = ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
    if dist <= RING_CENTRE * R and size >= RING_MIN_SIZE * R:
        return "ring light"
    if dist <= BOARD * R:
        return "light board"
    for sx in (x - SCREW_OFFSET * R, x + SCREW_OFFSET * R):
        if (cx - sx) ** 2 + (cy - y) ** 2 <= (SCREW_R * R) ** 2 and size <= SCREW_MAX_SIZE * R:
            return "screw"
    return None


# ------------------------------------------------------------------ previews
def tile(image, ring: dict | None, kept: list, masked: list, label: str, width: int = WIDTH):
    """A small copy of the photo with the ring, the screws and the boxes drawn on:
    red = removed as part of the ring, green = kept."""
    from PIL import ImageDraw
    im = image.convert("RGB").copy()
    d = ImageDraw.Draw(im, "RGBA")
    lw = max(2, im.width // 400)
    if ring:
        x, y, R = ring["x"], ring["y"], ring["r"]
        for cx, cy, rr in ((x, y, DRAW_RING * R), (x - SCREW_OFFSET * R, y, SCREW_R * R),
                           (x + SCREW_OFFSET * R, y, SCREW_R * R)):
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(255, 0, 0, 60), outline=(255, 0, 0, 255), width=lw)
    for boxes, colour in ((masked, (255, 0, 0, 255)), (kept, (0, 200, 0, 255))):
        for b in boxes:
            d.rectangle(list(b), outline=colour, width=lw * 2)
    im = im.resize((width, max(1, round(im.height * width / im.width))))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, width, 18], fill="black")
    d.text((4, 3), label, fill="yellow")
    return im


def sheet(tiles: list, cols: int = 4):
    from PIL import Image
    w, h = tiles[0].size
    out = Image.new("RGB", (w * cols, h * ((len(tiles) + cols - 1) // cols)), "white")
    for i, t in enumerate(tiles):
        out.paste(t.resize((w, h)), ((i % cols) * w, (i // cols) * h))
    return out


def after_combine(ddir: Path, deployment: str) -> dict:
    """Join the parts' ring files and previews into <deployment>_ring_light.json and _preview.jpg."""
    from PIL import Image
    parts = sorted(ddir.glob("working/chunks/*_keep/ring_light/rings.json")) or \
        sorted(ddir.glob("chunks/*_keep/ring_light/rings.json"))
    if not parts:
        return {}
    rings: dict = {}
    for p in parts:
        rings.update(json.loads(p.read_text()))
    rings = dict(sorted(rings.items()))
    (ddir / f"{deployment}_ring_light.json").write_text(json.dumps(rings, indent=1))
    tiles = sorted(t for p in parts for t in p.parent.glob("*.jpg"))
    if tiles:
        pick = [tiles[i] for i in np.linspace(0, len(tiles) - 1, min(12, len(tiles))).round().astype(int)]
        sheet([Image.open(t) for t in dict.fromkeys(pick)]).save(ddir / f"{deployment}_ring_light_preview.jpg",
                                                                 quality=80)
    found = sum(1 for r in rings.values() if r.get("source") == "found")
    return {"ring_light": {"nights": len(rings), "found_directly": found,
                           "file": f"{deployment}_ring_light.json",
                           "preview": f"{deployment}_ring_light_preview.jpg" if tiles else None}}
