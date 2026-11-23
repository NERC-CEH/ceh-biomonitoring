"""cehbio video: a light trap's night as a video, with the boxes, names and tracks the pipeline found.

  cehbio video --project farm1 --deployment trap-1                 the busiest night
  cehbio video --project farm1 --deployment trap-1 --night 2026-05-11 --individuals 5

Makes, in <results>/images/<project>/<deployment>/videos/:

  <deployment>_<night>.mp4                 every photo of the night in order: each insect boxed, moths named
                                           with the model's score, other insects by their order, and a trail
                                           showing where each tracked insect has been
  <deployment>_<night>_<track>.mp4         (--individuals N) the N insects seen on most photos, each followed
                                           close up from photo to photo

The photos come from wherever they are: the folder the pipeline read (if it's on this computer),
--source-root (one or more folders of copies, e.g. a hard drive), or the object store (--bucket, or the
bucket in the results). Every frame says the names are suggestions, not checked identifications.
"""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd

from . import draw as D

SPECIES, SCORE = "regional_species_rank_1_name", "regional_species_rank_1_confidence"
COLUMNS = ["image_path", "source_key", "image_datetime", "deployment_id", "bucket_name", "x_min", "y_min", "x_max",
           "y_max", "class_name", "order_name", "order_confidence", SPECIES, SCORE, "track_id", "masked", "masked_as"]


# ------------------------------------------------------------------ reading a run
def load(settings, project: str, deployment: str) -> tuple[pd.DataFrame, pd.DataFrame, Path]:
    """(photos: one row per photo with its time and night, boxes: one row per box, the run folder)."""
    from .. import layout
    from ..reporting.data import _file_times, night_of
    rp = layout.run_paths(settings, "images", project, deployment)
    f_files = rp.root / f"{deployment}_files.csv"
    if not f_files.exists():
        raise SystemExit(f"No results for {deployment} in {rp.root} (no {f_files.name}). `cehbio status` lists runs.")
    files = pd.read_csv(f_files, low_memory=False)
    res = next((p for p in (rp.root / f"{deployment}_analysis_ready.parquet", rp.root / f"{deployment}_detections.parquet")
                if p.exists()), None)
    boxes = pd.DataFrame(columns=COLUMNS)
    if res is not None:
        import pyarrow.parquet as pq
        have = set(pq.read_schema(res).names)
        boxes = pd.read_parquet(res, columns=[c for c in COLUMNS if c in have])
    files["when"] = _file_times(files, boxes)
    files["night"] = night_of(files["when"])
    files = files[files["when"].notna()].sort_values("when").reset_index(drop=True)
    files["name"] = files["source_key"].astype(str).map(lambda k: Path(k.replace("\\", "/")).name)
    if len(boxes):
        for c in ("x_min", "y_min", "x_max", "y_max"):
            boxes[c] = pd.to_numeric(boxes[c], errors="coerce")
        ok = boxes[["x_min", "y_min", "x_max", "y_max"]].notna().all(axis=1) & (boxes["x_max"] > boxes["x_min"])
        rig = pd.Series(False, index=boxes.index)
        if "masked_as" in boxes:
            rig |= boxes["masked_as"].notna() & boxes["masked_as"].astype(str).str.strip().ne("")
        if "masked" in boxes:
            rig |= boxes["masked"].astype(str).str.lower().isin(["true", "1", "1.0"])
        boxes = boxes[ok & ~rig].copy()
        path = boxes["image_path"] if "image_path" in boxes else boxes["source_key"]
        boxes["name"] = path.astype(str).map(lambda k: Path(k.replace("\\", "/")).name)
        boxes["track_id"] = boxes.get("track_id", pd.Series(pd.NA, index=boxes.index)).astype("string").fillna("")
    return files, boxes, rp.root


def nights_by_activity(files: pd.DataFrame, boxes: pd.DataFrame) -> list[str]:
    """Nights, busiest first (most distinct tracked insects)."""
    if not len(boxes):
        return files["night"].value_counts().index.tolist()
    b = boxes.merge(files[["name", "night"]], on="name", how="inner")
    key = np.where(b["track_id"].ne(""), b["track_id"], b.index.astype(str))
    return b.assign(k=key).groupby("night")["k"].nunique().sort_values(ascending=False, kind="stable").index.tolist()


def _box_text(r, min_score: float, labels: str) -> tuple[str, str]:
    """(text, colour) for one box."""
    sp = r.get(SPECIES)
    if isinstance(sp, str) and sp.strip():
        colour = D.colour_for(r["track_id"] or r.name)
        score = r.get(SCORE)
        if labels == "none":
            return "", colour
        if pd.notna(score) and float(score) < min_score:
            return "moth", colour
        return f"{sp}" + (f" {float(score):.2f}" if pd.notna(score) else ""), colour
    order = str(r.get("order_name") or "").strip()
    return ("" if labels == "none" else (order or "insect")), D.OTHER_INSECT


# ------------------------------------------------------------------ the night
def night_video(settings, project, deployment, night, files, boxes, media, out_dir: Path, fps: float = 4,
                width: int = 1280, trail: int = 8, min_score: float = 0.0, labels: str = "species") -> Path | None:
    from PIL import Image, ImageDraw

    from .encode import Video
    photos = files[files["night"] == night]
    if photos.empty:
        print(f"  {night}: no photos")
        return None
    by_photo = {k: g for k, g in boxes.groupby("name")} if len(boxes) else {}
    out = out_dir / f"{deployment}_{night}.mp4"
    history: dict[str, deque] = defaultdict(lambda: deque(maxlen=max(1, trail)))
    last_seen: dict[str, int] = {}
    video, missing, size = None, 0, None
    try:
        for i, p in enumerate(photos.itertuples()):
            try:
                path = media.get({"image_path": p.source_key, "source_key": p.source_key, "deployment_id": deployment,
                                  "bucket": getattr(p, "bucket_name", None)})
                im = Image.open(path).convert("RGB")
                media.done_with(path)
            except Exception:  # noqa: BLE001 - a photo that can't be had is skipped, and counted
                missing += 1
                continue
            scale = min(1.0, width / im.width)
            if scale < 1:
                im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            if size is None:
                size = (im.width - im.width % 2, im.height + 72)
                video = Video(out, size[0], size[1], fps).__enter__()
            if (im.width, im.height + 72) != size:
                im = im.resize((size[0], size[1] - 72))
            canvas = Image.new("RGB", size, D.NAVY)
            canvas.paste(im, (0, 40))
            d = ImageDraw.Draw(canvas, "RGBA")
            g = by_photo.get(p.name)
            n_insects = 0 if g is None else len(g)
            if g is not None:
                for _, r in g.iterrows():
                    x0, y0, x1, y1 = (r["x_min"] * scale, r["y_min"] * scale + 40, r["x_max"] * scale, r["y_max"] * scale + 40)
                    text, colour = _box_text(r, min_score, labels)
                    tid = r["track_id"]
                    if tid and trail > 0:
                        history[tid].append(((x0 + x1) / 2, (y0 + y1) / 2))
                        last_seen[tid] = i
                    d.rectangle([x0, y0, x1, y1], outline=colour, width=3)
                    if text:
                        D.label(d, (x0, y0), text, colour, size=15)
            for tid, pts in history.items():                 # trails of insects seen recently
                if len(pts) > 1 and i - last_seen.get(tid, -99) <= trail:
                    d.line(list(pts), fill=D.colour_for(tid), width=2)
            D.bar(d, size[0], 0, 40, f"{deployment}  ·  night of {night}",
                  f"{pd.Timestamp(p.when):%H:%M:%S}  ·  {n_insects} insect{'s' if n_insects != 1 else ''}")
            D.bar(d, size[0], size[1] - 32, 32, D.CAVEAT, "UKCEH ceh-biomonitoring", size=14)
            video.add(np.asarray(canvas))
    finally:
        if video is not None:
            video.__exit__(None, None, None)
    if video is None:
        print(f"  {night}: none of the {len(photos)} photos could be found (give --source-root or --bucket)")
        return None
    print(f"  {out.name}: {video.frames} photos" + (f" ({missing} couldn't be found)" if missing else ""))
    return out


# ------------------------------------------------------------------ one insect, close up
def individual_videos(deployment, night, files, boxes, media, out_dir: Path, n: int = 5, fps: float = 2,
                      side: int = 480, min_photos: int = 3, tracks: list[str] | None = None) -> list[Path]:
    from PIL import Image, ImageDraw

    from .encode import Video
    b = boxes.merge(files[["name", "night", "when", "source_key"]], on="name", how="inner")
    b = b[(b["night"] == night) & b["track_id"].ne("")]
    if tracks:
        pick = [t for t in tracks if t in set(b["track_id"])]
    else:
        counts = b.groupby("track_id")["name"].nunique()
        pick = counts[counts >= min_photos].sort_values(ascending=False, kind="stable").head(n).index.tolist()
    written = []
    for tid in pick:
        g = b[b["track_id"] == tid].sort_values("when")
        sp = g[SPECIES].dropna() if SPECIES in g else pd.Series(dtype=str)
        name = sp.mode().iloc[0] if len(sp) else (g["order_name"].dropna().mode().iloc[0]
                                                  if "order_name" in g and g["order_name"].notna().any() else "insect")
        out = out_dir / f"{deployment}_{night}_{tid}.mp4"
        head = (f"{name}  ·  {pd.Timestamp(g['when'].min()):%H:%M} to {pd.Timestamp(g['when'].max()):%H:%M}"
                f"  ·  {g['name'].nunique()} photos")
        with Video(out, side, side + 72, fps) as v:
            for _, r in g.iterrows():
                try:
                    path = media.get({"image_path": r["source_key"], "source_key": r["source_key"],
                                      "deployment_id": deployment, "bucket": r.get("bucket_name")})
                    im = Image.open(path).convert("RGB")
                    media.done_with(path)
                except Exception:  # noqa: BLE001
                    continue
                w, h = r["x_max"] - r["x_min"], r["y_max"] - r["y_min"]
                half = max(w, h) * 0.9 + 20
                cx, cy = (r["x_min"] + r["x_max"]) / 2, (r["y_min"] + r["y_max"]) / 2
                crop = im.crop((cx - half, cy - half, cx + half, cy + half)).resize((side, side), Image.LANCZOS)
                k = side / (2 * half)
                canvas = Image.new("RGB", (side, side + 72), D.NAVY)
                canvas.paste(crop, (0, 40))
                d = ImageDraw.Draw(canvas, "RGBA")
                bx0, by0 = (r["x_min"] - (cx - half)) * k, (r["y_min"] - (cy - half)) * k + 40
                colour = D.colour_for(tid)
                d.rectangle([bx0, by0, bx0 + w * k, by0 + h * k], outline=colour, width=3)
                text, _ = _box_text(r, 0.0, "species")
                D.label(d, (6, 46), f"{pd.Timestamp(r['when']):%H:%M:%S}  {text}", colour, size=15, above=False)
                D.bar(d, side, 0, 40, head, size=15)
                D.bar(d, side, side + 40, 32, "Suggested names, not checked", tid, size=13)
                v.add(np.asarray(canvas))
        print(f"  {out.name}: {g['name'].nunique()} photos of {name}")
        written.append(out)
    return written


def make(settings, project, deployment, nights=None, all_nights=False, individuals=0, tracks=None, fps=4.0,
         width=1280, trail=8, min_score=0.0, labels="species", source_root=None, bucket=None, out=None) -> list[Path]:
    from ..validation.media import Media
    files, boxes, root = load(settings, project, deployment)
    order = nights_by_activity(files, boxes)
    if nights:
        bad = [n for n in nights if n not in set(files["night"])]
        if bad:
            raise SystemExit(f"No photos on night(s) {', '.join(bad)}. Nights with photos: {', '.join(sorted(set(files['night'])))}")
        chosen = list(nights)
    elif all_nights:
        chosen = sorted(set(files["night"]))
    else:
        chosen = order[:1]
        print(f"The busiest night is {chosen[0]} (choose others with --night, or --all-nights).")
    out_dir = Path(out) if out else root / "videos"
    written = []
    with Media(settings, "images", bucket, source_root) as m:
        for n in chosen:
            v = night_video(settings, project, deployment, n, files, boxes, m, out_dir, fps, width, trail, min_score, labels)
            if v:
                written.append(v)
            if individuals or tracks:
                written += individual_videos(deployment, n, files, boxes, m, out_dir, individuals or 0, tracks=tracks)
    if written:
        print(f"Videos in {out_dir}")
    return written


def add_command(sub, common) -> None:
    import argparse
    p = sub.add_parser("video", parents=[common], help="a light trap's night as a video, with boxes, names and tracks",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True)
    p.add_argument("--deployment", required=True)
    p.add_argument("--night", nargs="+", help="night(s), named by the evening they start, e.g. 2026-05-11 (default: the busiest)")
    p.add_argument("--all-nights", action="store_true", help="one video per night")
    p.add_argument("--individuals", type=int, default=0, help="also follow the N insects seen on most photos, close up")
    p.add_argument("--track", nargs="+", help="follow these tracks close up (e.g. Track_000123)")
    p.add_argument("--fps", type=float, default=4, help="photos per second (default 4)")
    p.add_argument("--width", type=int, default=1280, help="video width in pixels (default 1280)")
    p.add_argument("--trail", type=int, default=8, help="photos of trail behind each tracked insect (0: none)")
    p.add_argument("--min-score", type=float, default=0.0, help="name moths only at or above this score")
    p.add_argument("--labels", choices=["species", "none"], default="species", help="names on the boxes, or none")
    p.add_argument("--source-root", nargs="+", help="folder(s) with copies of the photos")
    p.add_argument("--bucket", help="object-store bucket with the photos")
    p.add_argument("--out", help="folder for the videos (default: the deployment's videos/ folder)")

    def go(a):
        from ..settings import Settings
        make(Settings.load(getattr(a, "profile", None)), a.project, a.deployment, a.night, a.all_nights, a.individuals,
             a.track, a.fps, a.width, a.trail, a.min_score, a.labels, a.source_root, a.bucket, a.out)
    p.set_defaults(func=go)
