"""cehbio mask: make a mask (black = ignore, white = keep) for one camera set-up.

  suggest  from a test run's detections: anything detected in the same place in many photos (a ring
           light, the camera rig, a label) is almost certainly not an insect
  draw     click around the areas to ignore on one of your photos (needs a screen)
  show     check a mask by laying it over a photo
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


def _save(ignore: np.ndarray, out: Path) -> Path:
    from PIL import Image
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.where(ignore, 0, 255).astype(np.uint8)).save(out)
    return out


def preview(mask_path: Path, image_path: Path, out: Path) -> Path:
    """The photo with the ignored area tinted red."""
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    m = Image.open(mask_path).convert("L").resize(img.size, Image.NEAREST)
    a = np.asarray(img).astype(np.float32)
    ignore = np.asarray(m) < 128
    a[ignore] = a[ignore] * 0.45 + np.array([255, 0, 0]) * 0.55
    Image.fromarray(a.astype(np.uint8)).save(out, quality=85)
    return Path(out)


def suggest(detections: Path, image: Path, out: Path, min_fraction: float = 0.2, grow: int = 10) -> dict:
    """Ignore everywhere covered by a detection in at least `min_fraction` of the photos."""
    import pandas as pd
    from PIL import Image
    df = pd.read_parquet(detections)
    name_col = "source_key" if "source_key" in df else "image_path"
    df = df.dropna(subset=["x_min", "y_min", "x_max", "y_max"])
    W, H = Image.open(image).size
    scale = 512 / max(W, H)
    w, h = max(1, round(W * scale)), max(1, round(H * scale))
    heat = np.zeros((h, w), np.float32)
    n_images = df[name_col].nunique()
    for _, g in df.groupby(name_col):
        cover = np.zeros((h, w), bool)
        for x0, y0, x1, y1 in g[["x_min", "y_min", "x_max", "y_max"]].to_numpy(float):
            cover[int(y0 * scale):int(np.ceil(y1 * scale)) + 1, int(x0 * scale):int(np.ceil(x1 * scale)) + 1] = True
        heat += cover
    frac = heat / max(n_images, 1)
    ignore = frac >= min_fraction
    if grow and ignore.any():                        # grow the area a little so edges are covered
        from PIL import Image as I, ImageFilter
        ignore = np.asarray(I.fromarray(ignore.astype(np.uint8) * 255).filter(
            ImageFilter.MaxFilter(2 * max(1, round(grow * scale)) + 1))) > 0
    full = np.asarray(Image.fromarray(ignore.astype(np.uint8) * 255).resize((W, H), Image.NEAREST)) > 0
    out = _save(full, out)
    prev = preview(out, image, out.with_name(out.stem + "_preview.jpg"))
    return {"mask": str(out), "preview": str(prev), "photos": int(n_images),
            "ignored_fraction_of_image": round(float(full.mean()), 4)}


def draw(image: Path, out: Path) -> Path:
    """Click round each area to ignore; Enter adds it, u undoes the last one, w saves and closes."""
    import matplotlib.pyplot as plt
    from matplotlib.path import Path as MPath
    from matplotlib.widgets import PolygonSelector
    from PIL import Image
    img = Image.open(image).convert("RGB")
    W, H = img.size
    polygons: list[list[tuple[float, float]]] = []
    current: list = []
    fig, ax = plt.subplots(figsize=(12, 9))
    ax.imshow(img)
    ax.set_title("Click round an area to ignore, then Enter. u = undo last, w = save and close")
    patches: list = []

    def onselect(verts):
        current[:] = verts

    sel = PolygonSelector(ax, onselect)

    def on_key(e):
        if e.key == "enter" and len(current) >= 3:
            polygons.append(list(current))
            patches.append(ax.fill(*zip(*current), color="red", alpha=0.4)[0])
            sel.clear()
            current.clear()
            fig.canvas.draw_idle()
        elif e.key == "u" and polygons:
            polygons.pop()
            patches.pop().remove()
            fig.canvas.draw_idle()
        elif e.key == "w":
            plt.close(fig)

    fig.canvas.mpl_connect("key_press_event", on_key)
    plt.show()
    yy, xx = np.mgrid[0:H, 0:W]
    pts = np.column_stack([xx.ravel(), yy.ravel()])
    ignore = np.zeros(H * W, bool)
    for poly in polygons:
        ignore |= MPath(poly).contains_points(pts)
    out = _save(ignore.reshape(H, W), out)
    preview(out, image, out.with_name(out.stem + "_preview.jpg"))
    return out


def add_command(sub, common) -> None:
    m = sub.add_parser("mask", parents=[common], help="make a mask of areas to ignore (e.g. a ring light)",
                       description=__doc__, formatter_class=__import__("argparse").RawDescriptionHelpFormatter)
    ms = m.add_subparsers(dest="mask_cmd", required=True)
    s = ms.add_parser("suggest", help="from a test run's detections")
    s.add_argument("--detections", required=True, help="<deployment>_detections.parquet from a test run")
    s.add_argument("--image", required=True, help="one photo from the same camera set-up")
    s.add_argument("--out", required=True, help="mask to write, e.g. masks/site1.png")
    s.add_argument("--min-fraction", type=float, default=0.2,
                   help="ignore places detected in at least this fraction of photos (default 0.2)")
    d = ms.add_parser("draw", help="click round areas to ignore (needs a screen)")
    d.add_argument("--image", required=True)
    d.add_argument("--out", required=True)
    v = ms.add_parser("show", help="lay a mask over a photo")
    v.add_argument("--mask", required=True)
    v.add_argument("--image", required=True)
    v.add_argument("--out", required=True, help="preview .jpg to write")

    def run(args):
        if args.mask_cmd == "suggest":
            r = suggest(Path(args.detections), Path(args.image), Path(args.out), args.min_fraction)
            print(f"Mask: {r['mask']}  ({r['ignored_fraction_of_image']:.1%} of the image ignored, "
                  f"from {r['photos']} photos)\nCheck it: {r['preview']}\n"
                  f"Use it: cehbio run images ... --set mask={r['mask']}")
        elif args.mask_cmd == "draw":
            out = draw(Path(args.image), Path(args.out))
            print(f"Mask: {out}\nUse it: cehbio run images ... --set mask={out}")
        else:
            print(f"Preview: {preview(Path(args.mask), Path(args.image), Path(args.out))}")
    m.set_defaults(func=run)
