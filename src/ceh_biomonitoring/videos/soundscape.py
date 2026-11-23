"""cehbio soundscape: a day of bird song (or a night of bats) to watch and listen to.

  cehbio soundscape birds --project my-woods --deployment wood-1                  the busiest day
  cehbio soundscape bats --project my-woods --deployment wood-1 --night 2026-05-11
  cehbio soundscape birds --project my-woods --deployment wood-1 --recording 20260511_050000.WAV

Makes, in <results>/<pipeline>/<project>/<deployment>/videos/:

  <deployment>_<day>_soundscape.mp4   the day's highlights: the best moment for each species the model
                                      found (up to --highlights, in time order), each a short clip with its
                                      sound and a moving spectrogram (time across, pitch up, louder =
                                      brighter), the detections marked and named with their scores
  <deployment>_<day>_overview.png     (birds; bats with --overview) the whole day at a glance: sound across
                                      the day, low to high pitch, with a dot for each detection, by species
  --recording: one whole recording (up to --max-seconds) with everything found in it, instead of highlights

Bats are slowed down ten times, so their calls can be heard (a 45 kHz call becomes 4.5 kHz): one second of
recording becomes ten seconds of video. Recordings come from wherever they are: the folder the pipeline
read, --source-root, or the object store (--bucket). The names are suggestions, not checked identifications.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import draw as D

RANGES = {"bats": (10_000, 130_000), "birds": (0, 12_000)}
SLOW = {"bats": 10, "birds": 1}
CLIP_S = {"birds": 10.0, "bats": 1.0}        # recording seconds per highlight
W, SPEC_H, TOP, BOTTOM, LEFT = 1280, 520, 40, 64, 56


def _lut():
    from matplotlib import colormaps
    return (colormaps["magma"](np.linspace(0, 1, 256))[:, :3] * 255).astype(np.uint8)


def load(settings, pipeline: str, project: str, deployment: str):
    """(detections, events, run folder): events are the units an expert checks (birds: calling events; bats: passes)."""
    from .. import layout
    from ..validation import units as U
    rp = layout.run_paths(settings, pipeline, project, deployment)
    f = rp.root / f"{deployment}_detections.parquet"
    if not f.exists():
        raise SystemExit(f"No results for {deployment} in {rp.root}. `cehbio status` lists runs.")
    det = pd.read_parquet(f)
    det["results"] = str(f)
    if "deployment_id" not in det:
        det["deployment_id"] = deployment
    ev = U.audio_units(det.copy(), pipeline)
    ev = ev[ev["period"].astype(str) != "unknown"].copy()
    ev["period"] = ev["period"].astype(str)
    ev["species"] = ev["species"].astype(str)
    return det, ev, rp.root


def _read(media, row, start: float, end: float, deployment: str):
    import soundfile as sf
    path = media.get({"source_key": row["source_key"], "deployment_id": deployment, "bucket": row.get("bucket_name")})
    with sf.SoundFile(str(path)) as f:
        sr = f.samplerate
        a0, a1 = max(0, int(start * sr)), min(f.frames, int(end * sr))
        f.seek(a0)
        a = f.read(max(0, a1 - a0), dtype="float32", always_2d=True).mean(axis=1)
    media.done_with(path)
    return a, sr, a0 / sr


def _spec_image(a: np.ndarray, sr: int, group: str, width: int, height: int):
    """The clip's spectrogram as an RGB array (height x width), and the frequency range shown."""
    from ..validation.spectrogram import spectrogram_db
    nfft = 1024 if group == "birds" else 512
    hop = max(1, (len(a) - nfft) // max(1, width - 1)) if len(a) > nfft else 1
    db, freqs, _ = spectrogram_db(a, sr, nfft, hop)
    lo, hi = RANGES[group][0], min(RANGES[group][1], sr / 2)
    keep = (freqs >= lo) & (freqs <= hi)
    db = db[keep][::-1]
    if not db.size:
        return np.zeros((height, width, 3), np.uint8), (lo, hi)
    v0, v1 = np.percentile(db, 20), np.percentile(db, 99.7)
    idx = np.clip((db - v0) / max(1e-6, v1 - v0) * 255, 0, 255).astype(np.uint8)
    from PIL import Image
    rgb = Image.fromarray(_lut()[idx]).resize((width, height), Image.BILINEAR)
    return np.asarray(rgb), (lo, hi)


def _fade(a: np.ndarray, sr: int, ms: int = 20) -> np.ndarray:
    n = min(len(a) // 2, int(sr * ms / 1000))
    if n > 0:
        ramp = np.linspace(0, 1, n, dtype=np.float32)
        a = a.copy()
        a[:n] *= ramp
        a[-n:] *= ramp[::-1]
    return a


def _base_frame(spec: np.ndarray, rng, clip_start: float, clip_len: float, title: str, right: str, marks: list[dict],
                group: str):
    """The still part of a clip's frames: spectrogram, axes, detections, header and footer."""
    from PIL import Image, ImageDraw
    H = TOP + SPEC_H + BOTTOM
    im = Image.new("RGB", (W, H), D.NAVY)
    im.paste(Image.fromarray(spec), (LEFT, TOP))
    d = ImageDraw.Draw(im, "RGBA")
    f = D.font(13)
    sw = W - LEFT
    lo, hi = rng
    for khz in np.linspace(lo, hi, 5):                 # pitch axis, kHz
        y = TOP + SPEC_H - (khz - lo) / (hi - lo) * SPEC_H
        d.text((4, min(max(y - 7, TOP), TOP + SPEC_H - 14)), f"{khz / 1000:.0f} kHz", font=f, fill="white")
    step = next(x for x in (0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300) if clip_len / x <= 8)
    dec = 2 if step < 0.1 else (1 if step < 1 else 0)
    t = np.ceil(clip_start / step) * step
    while t <= clip_start + clip_len + 1e-9:           # time axis: seconds into the recording, at round numbers
        x = LEFT + (t - clip_start) / clip_len * sw
        d.line([x, TOP + SPEC_H, x, TOP + SPEC_H + 5], fill="white")
        d.text((x + 2, TOP + SPEC_H + 5), f"{t:.{dec}f} s", font=f, fill="white")
        t += step
    for m in marks:                                    # what the model found here
        x0 = LEFT + max(0.0, (m["start"] - clip_start) / clip_len) * sw
        x1 = LEFT + min(1.0, (m["end"] - clip_start) / clip_len) * sw
        if x1 <= LEFT or x0 >= W:
            continue
        colour = D.colour_for(m["species"])
        if m.get("low") and m.get("high"):
            y0 = TOP + SPEC_H - (min(m["high"], hi) - lo) / (hi - lo) * SPEC_H
            y1 = TOP + SPEC_H - (max(m["low"], lo) - lo) / (hi - lo) * SPEC_H
        else:
            y0, y1 = TOP + 2, TOP + SPEC_H - 2
        d.rectangle([x0, y0, x1, y1], outline=colour, width=2)
        D.label(d, (x0 + 2, max(TOP + 2, y0 + 2)), m["text"], colour, size=14, above=False)
    D.bar(d, W, 0, TOP, title, right, size=17)
    note = D.CAVEAT + ("  ·  slowed down 10 times" if group == "bats" else "")
    D.bar(d, W, H - 30, 30, note, "UKCEH ceh-biomonitoring", size=13)
    return np.asarray(im).copy()


def _marks(det: pd.DataFrame, key: str, start: float, end: float, group: str) -> list[dict]:
    score = next((c for c in ("confidence", "logit", "class_probability") if c in det), None)
    g = det[(det["source_key"].astype(str) == key) & (det["end_time"] > start) & (det["start_time"] < end)]
    out = []
    for _, r in g.iterrows():
        name = str(r["species_name"])
        cn = r.get("common_name")
        text = (f"{cn} " if isinstance(cn, str) and cn else "") + name + (f" {float(r[score]):.2f}" if score and pd.notna(r[score]) else "")
        out.append({"start": float(r["start_time"]), "end": float(r["end_time"]), "species": name, "text": text,
                    "low": r.get("low_freq") if pd.notna(r.get("low_freq", np.nan)) else None,
                    "high": r.get("high_freq") if pd.notna(r.get("high_freq", np.nan)) else None})
    return out


def _render(clips: list[dict], out: Path, group: str, fps: int = 20) -> Path:
    """Clips (audio, sr, still frame, recording seconds) -> one video with sound, a playhead moving across."""
    from .encode import Video
    slow = SLOW[group]
    sr = clips[0]["sr"]
    gap = np.zeros(int(0.4 * sr / slow), np.float32)      # 0.4 s of silence between clips, as heard
    parts, frames_plan = [], []
    for c in clips:
        a = c["audio"]
        if c["sr"] != sr:                               # different rates: brought to the first clip's
            a = np.interp(np.linspace(0, len(a) - 1, int(len(a) * sr / c["sr"])), np.arange(len(a)), a).astype(np.float32)
        a = _fade(a, sr)
        parts += [a, gap]
        play_s = len(a) / sr * slow
        n = max(1, int(round(play_s * fps)))
        frames_plan.append((c["frame"], n, int(round(len(gap) / sr * slow * fps))))
    audio = np.concatenate(parts)
    peak = float(np.max(np.abs(audio))) or 1.0
    audio = audio / peak * 0.9
    frame0 = frames_plan[0][0]
    rate = int(sr / slow)                               # slowed by playing at a lower rate
    if rate not in (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000):   # rates the sound encoder takes
        n_out = int(len(audio) * 48000 / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n_out), np.arange(len(audio)), audio).astype(np.float32)
        rate = 48000
    with Video(out, frame0.shape[1], frame0.shape[0], fps, audio=audio, audio_rate=rate) as v:
        for still, n, n_gap in frames_plan:
            for k in range(n):
                f = still.copy()
                x = LEFT + int((k + 0.5) / n * (W - LEFT))
                f[TOP:TOP + SPEC_H, max(LEFT, x - 1):x + 1] = 255
                v.add(f)
            for _ in range(n_gap):
                v.add(still)
    return out


def _overview(settings, det, ev, day: str, group: str, media, out: Path, deployment: str) -> Path | None:
    """The whole day: a few seconds of sound every half minute of each recording, as one picture."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import soundfile as sf

    from ..validation.spectrogram import spectrogram_db
    recs = ev[ev["period"] == day][["source_key", "when"]].drop_duplicates("source_key")
    files = det.drop_duplicates("source_key")[["source_key"]].merge(
        ev[["source_key", "when"]].drop_duplicates("source_key"), on="source_key", how="left")
    files = files[files["source_key"].isin(set(recs["source_key"]))].sort_values("when")
    cols, xs = [], []
    for r in files.itertuples():
        try:
            path = media.get({"source_key": r.source_key, "deployment_id": deployment})
        except Exception:  # noqa: BLE001
            continue
        with sf.SoundFile(str(path)) as f:
            sr, n = f.samplerate, f.frames
            for t0 in np.arange(0, n / sr, 30.0):
                f.seek(int(t0 * sr))
                a = f.read(int(min(2.0, n / sr - t0) * sr), dtype="float32", always_2d=True).mean(axis=1)
                if len(a) < 1024:
                    continue
                db, freqs, _ = spectrogram_db(a, sr, 1024 if group == "birds" else 512, 512)
                lo, hi = RANGES[group][0], min(RANGES[group][1], sr / 2)
                keep = (freqs >= lo) & (freqs <= hi)
                cols.append(db[keep].mean(axis=1))
                xs.append(pd.Timestamp(r.when) + pd.Timedelta(seconds=float(t0)))
        media.done_with(path)
    if not cols:
        return None
    m = np.array([np.interp(np.linspace(0, 1, 160), np.linspace(0, 1, len(c)), c) for c in cols]).T
    fig, ax = plt.subplots(figsize=(14, 5), dpi=110)
    t = mdates_num = matplotlib.dates.date2num(pd.to_datetime(xs).to_pydatetime())
    v0, v1 = np.percentile(m, 5), np.percentile(m, 99.5)
    ax.pcolormesh(t, np.linspace(RANGES[group][0], min(RANGES[group][1], sr / 2), 160) / 1000, m, cmap="magma",
                  vmin=v0, vmax=v1, shading="nearest")
    e = ev[ev["period"] == day].copy()
    e["t"] = matplotlib.dates.date2num((pd.to_datetime(e["when"]) + pd.to_timedelta(e["peak_s"], unit="s")).dt.to_pydatetime())
    top = e["species"].value_counts().index[:8].tolist()
    ytop = min(RANGES[group][1], sr / 2) / 1000
    for i, sp in enumerate(top):
        g = e[e["species"] == sp]
        ax.scatter(g["t"], np.full(len(g), ytop * (0.97 - 0.035 * i)), s=14, color=D.colour_for(sp), label=f"{sp} ({len(g)})",
                   edgecolors="black", linewidths=0.3, zorder=3)
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%H:%M"))
    ax.set_ylabel("pitch (kHz)")
    ax.set_title(f"{deployment}, {day}: the sound through the {'day' if group == 'birds' else 'night'}, with what the "
                 f"model suggested (not checked)", fontsize=11, loc="left")
    if top:
        ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8, frameon=False, title="commonest suggestions")
    del mdates_num
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out


def make(settings, pipeline, project, deployment, day=None, recording=None, highlights=12, length=None,
         min_score=None, overview=None, max_seconds=300, source_root=None, bucket=None, out=None) -> list[Path]:
    from ..validation.media import Media
    det, ev, root = load(settings, pipeline, project, deployment)
    if ev.empty:
        raise SystemExit(f"Nothing was detected in {deployment}'s recordings, so there's nothing to show.")
    out_dir = Path(out) if out else root / "videos"
    clip_s = float(length) / SLOW[pipeline] if length else CLIP_S[pipeline]
    written = []
    with Media(settings, pipeline, bucket, source_root) as m:
        if recording:
            keys = det["source_key"].astype(str)
            hit = keys[keys.map(lambda k: Path(k.replace("\\", "/")).name.lower() == Path(recording).name.lower())]
            if hit.empty:
                raise SystemExit(f"No recording called {recording} in {deployment}'s results.")
            key = hit.iloc[0]
            row = det[keys == key].iloc[0].to_dict()
            a, sr, s0 = _read(m, row, 0, max_seconds, deployment)
            clip_len = len(a) / sr
            spec, rng = _spec_image(a, sr, pipeline, W - LEFT, SPEC_H)
            frame = _base_frame(spec, rng, s0, clip_len, f"{deployment}  ·  {Path(key).name}",
                                f"{clip_len:.0f} s", _marks(det, key, s0, s0 + clip_len, pipeline), pipeline)
            o = _render([{"audio": a, "sr": sr, "frame": frame}], out_dir / f"{deployment}_{Path(key).stem}_soundscape.mp4",
                        pipeline)
            print(f"  {o.name}")
            return [o]
        days = ev.groupby("period")["species"].nunique().sort_values(ascending=False, kind="stable")
        if day is None:
            day = days.index[0]
            print(f"The {'day' if pipeline == 'birds' else 'night'} with most species is {day} (choose another with "
                  f"--{'date' if pipeline == 'birds' else 'night'}).")
        elif day not in days.index:
            raise SystemExit(f"Nothing detected on {day}. With detections: {', '.join(sorted(days.index))}")
        e = ev[ev["period"] == day]
        if min_score is not None:
            e = e[e["score"] >= min_score]
        best = (e.sort_values("score", ascending=False, kind="stable").drop_duplicates("species")
                .head(highlights).sort_values(["when", "peak_s"], kind="stable"))
        clips = []
        for r in best.itertuples():
            mid = float(r.peak_s) + float(r.window_s or 0) / 2
            start = max(0.0, mid - clip_s / 2)
            try:
                a, sr, s0 = _read(m, {"source_key": r.source_key, "bucket_name": getattr(r, "bucket", None)},
                                  start, start + clip_s, deployment)
            except Exception as ex:  # noqa: BLE001
                print(f"  skipped {r.species}: {ex}")
                continue
            spec, rng = _spec_image(a, sr, pipeline, W - LEFT, SPEC_H)
            when = pd.Timestamp(r.when) + pd.Timedelta(seconds=s0)
            cn = getattr(r, "common_name", None)
            title = f"{deployment}  ·  {when:%Y-%m-%d %H:%M:%S}  ·  " + (f"{cn} ({r.species})" if isinstance(cn, str) and cn else r.species)
            clips.append({"audio": a, "sr": sr, "frame": _base_frame(
                spec, rng, s0, len(a) / sr, title, f"score {r.score:.2f}",
                _marks(det, r.source_key, s0, s0 + len(a) / sr, pipeline), pipeline)})
        if not clips:
            raise SystemExit("None of the recordings could be found: give --source-root or --bucket.")
        o = _render(clips, out_dir / f"{deployment}_{day}_soundscape.mp4", pipeline)
        print(f"  {o.name}: {len(clips)} highlights")
        written.append(o)
        if overview if overview is not None else pipeline == "birds":
            p = _overview(settings, det, ev, day, pipeline, m, out_dir / f"{deployment}_{day}_overview.png", deployment)
            if p:
                print(f"  {p.name}")
                written.append(p)
    print(f"In {out_dir}")
    return written


def add_command(sub, common) -> None:
    import argparse
    p = sub.add_parser("soundscape", parents=[common], help="a day of birds (or night of bats) to watch and listen to",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pipeline", choices=["birds", "bats"])
    p.add_argument("--project", required=True)
    p.add_argument("--deployment", required=True)
    p.add_argument("--date", "--night", dest="day", help="the day (birds) or night (bats), e.g. 2026-05-11 (default: most species)")
    p.add_argument("--recording", help="one whole recording instead of highlights (its file name)")
    p.add_argument("--highlights", type=int, default=12, help="how many species' best moments (default 12)")
    p.add_argument("--length", type=float, help="seconds of video per highlight (default 10)")
    p.add_argument("--min-score", type=float, help="only detections at or above this score")
    p.add_argument("--overview", action="store_true", default=None, help="also the whole-day picture (always for birds)")
    p.add_argument("--no-overview", dest="overview", action="store_false", help="no whole-day picture")
    p.add_argument("--max-seconds", type=float, default=300, help="--recording: at most this much (default 300)")
    p.add_argument("--source-root", nargs="+", help="folder(s) with copies of the recordings")
    p.add_argument("--bucket", help="object-store bucket with the recordings")
    p.add_argument("--out", help="folder for the videos (default: the deployment's videos/ folder)")

    def go(a):
        from ..settings import Settings
        make(Settings.load(getattr(a, "profile", None)), a.pipeline, a.project, a.deployment, a.day, a.recording,
             a.highlights, a.length, a.min_score, a.overview, a.max_seconds, a.source_root, a.bucket, a.out)
    p.set_defaults(func=go)
