"""Spectrograms and a page to listen from, for the audio clips sent to experts.

Each clip gets a spectrogram (.png): time across, frequency up, louder = brighter. A small mark along
the top shows each place the model detected something; it never says what, so blind sheets stay blind.
Bats: 10-130 kHz (or up to half the sample rate), plus a copy of the clip slowed 10 times (clips_slowed/),
so the calls can be heard (40 kHz becomes 4 kHz). Birds: 0-12 kHz.

index.html shows every clip with its spectrogram and a player, in the sheet's order, so an expert can
work through them in a web browser and write their answers in the sheet.
"""
from __future__ import annotations

import html
from pathlib import Path

import numpy as np

RANGES = {"bats": (10_000, 130_000), "birds": (0, 12_000)}
SLOW = 10                          # bats: slowed copies play at a tenth of the speed


def spectrogram_db(a: np.ndarray, sr: int, nfft: int, hop: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(dB power [freq, time], frequencies Hz, times s) with a Hann window. Numpy only."""
    a = np.asarray(a, dtype=np.float32)
    if a.ndim > 1:
        a = a.mean(axis=1)
    if len(a) < nfft:
        a = np.pad(a, (0, nfft - len(a)))
    n = 1 + (len(a) - nfft) // hop
    idx = np.arange(nfft)[None, :] + hop * np.arange(n)[:, None]
    frames = a[idx] * np.hanning(nfft).astype(np.float32)
    p = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    db = 10 * np.log10(p.T + 1e-12)
    return db, np.fft.rfftfreq(nfft, 1 / sr), (np.arange(n) * hop + nfft / 2) / sr


def save(a: np.ndarray, sr: int, out: Path, group: str, marks: list[float] = (), title: str = "") -> Path:
    """A spectrogram of one clip, as a .png."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    lo, hi = RANGES.get(group, (0, sr / 2))
    hi = min(hi, sr / 2)
    nfft = 512 if group == "bats" or sr < 32_000 else 1024        # bats ~1.5 ms frames; birds ~20 ms
    db, f, t = spectrogram_db(a, sr, nfft, max(1, nfft // 4))
    keep = (f >= lo) & (f <= hi)
    db, f = db[keep], f[keep]
    if db.size == 0:
        raise ValueError(f"nothing between {lo / 1000:g} and {hi / 1000:g} kHz at {sr} Hz")
    db = db - np.median(db, axis=1, keepdims=True)    # each frequency's background level to zero (hiss, hum)
    dur = len(a) / sr
    width_in = min(24, max(6, dur * (6 if group == "bats" else 0.5)))
    px = int(width_in * 100 * 0.85)                    # about the plot's width in pixels
    if db.shape[1] > px:                               # shrink by keeping the loudest of each group of
        k = int(np.ceil(db.shape[1] / px))             # columns, so a 5 ms bat call isn't dropped
        n = db.shape[1] // k * k
        db = db[:, :n].reshape(db.shape[0], -1, k).max(axis=2)
    top = max(20.0, float(np.percentile(db, 99.9)))
    fig, ax = plt.subplots(figsize=(width_in, 3.2), dpi=100)
    ax.imshow(db, origin="lower", aspect="auto", cmap="magma", vmin=0, vmax=top,
              extent=[0, dur, f[0] / 1000, f[-1] / 1000], interpolation="nearest")
    for m in marks:
        ax.axvline(m, ymin=0.96, ymax=1.0, color="cyan", lw=2)
    ax.set_xlabel("seconds")
    ax.set_ylabel("kHz")
    if title:
        ax.set_title(title, fontsize=9, loc="left")
    fig.tight_layout()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out


def page(rows: list[dict], out: Path, title: str, blind: bool, group: str) -> Path:
    """index.html: every clip, with its spectrogram and a player."""
    e = html.escape
    show = ["site", "period"] + ([] if blind else ["species", "english_name", "score"]) + ["detected_in_clip"]
    parts = [f"<!doctype html><meta charset='utf-8'><title>{e(title)}</title>",
             "<style>body{font-family:Arial,sans-serif;margin:16px;max-width:1400px}"
             "section{border-top:1px solid #ccc;padding:12px 0}img{max-width:100%}"
             "dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:6px 0}"
             "dt{color:#555}audio{margin:4px 12px 4px 0}</style>",
             f"<h1>{e(title)}</h1>",
             f"<p>{len(rows)} clips. Listen, look, and write your answer for each clip ID in the sheet"
             + (" (what you hear: the model's guesses are not shown)" if blind else " (is the species right? Y, N or ?)")
             + ". Marks along the top of a spectrogram show where the model detected something."
             + (" Bat calls are too high to hear: play the <b>slowed</b> copy (10 times slower, "
                "so 40 kHz sounds at 4 kHz)." if group == "bats" else "") + "</p>"]
    for r in rows:
        parts.append(f"<section><h2>{e(str(r['clip_id']))}</h2><dl>"
                     + "".join(f"<dt>{e(k.replace('_', ' '))}</dt><dd>{e(str(r.get(k, '')))}</dd>"
                               for k in show if str(r.get(k, "")) not in ("", "nan"))
                     + "</dl>")
        if r.get("clip_file"):
            parts.append(f"<audio controls preload='none' src='{e(r['clip_file'])}'></audio>")
        if r.get("slowed_file"):
            parts.append(f"slowed: <audio controls preload='none' src='{e(r['slowed_file'])}'></audio>")
        if r.get("spectrogram"):
            parts.append(f"<div><img loading='lazy' src='{e(r['spectrogram'])}' alt='spectrogram'></div>")
        if str(r.get("notes", "")).startswith("could not"):
            parts.append(f"<p><b>{e(str(r['notes']))}</b></p>")
        parts.append("</section>")
    out = Path(out)
    out.write_text("\n".join(parts), encoding="utf-8")
    return out
