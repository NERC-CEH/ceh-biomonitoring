"""Audio clips: a WAV clip per selected unit and a spreadsheet for the expert's verdicts (birds, bats).

Birds: each clip is --clip-seconds long (default 30), centred on the event's strongest window.
Bats: each clip is the whole pass with --pad-seconds either side (default 1 s), at the recording's own
sample rate, ready for bat software (e.g. Kaleidoscope, BatSound, Audacity's spectrogram view).
The sheet says where in the clip the model detected the species.
Every clip also gets a spectrogram (spectrograms/), bat clips a copy slowed 10 times to listen to
(clips_slowed/), and index.html shows them all with a player (--no-spectrograms leaves them out).

Site-lists selections tell the expert the species and ask "is it right?". Model selections are BLIND by
default: the expert sees only the clip and writes what they hear; the model's labels go in a separate
key file (model_labels_KEY_do_not_send.csv), so they can't lead the answer (--no-blind to show them).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from ..media import Media, by_source

GROUPS = ["birds", "bats"]


def prepare(sel: pd.DataFrame, out: Path, settings=None, blind: bool | None = None, bucket: str | None = None,
            source_root: str | None = None, clip_seconds: float | None = None, pad_seconds: float = 1.0,
            spectrograms: bool = True, **_) -> dict:
    import soundfile as sf
    from .. import spectrogram as SP
    group = str(sel["group"].iloc[0])
    sel = sel[~sel["reserve"].fillna(False).astype(bool)]           # spares aren't needed for audio
    out = Path(out)
    clips = out / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    if blind is None:
        blind = (sel["purpose"] == "model").all()
    if clip_seconds is None and group == "birds":
        clip_seconds = 30.0
    rows, key = [], []
    with Media(settings, group, bucket, source_root) as media:
        for src_key, items in by_source(sel, group):
            try:
                src, err = media.get(items.iloc[0].to_dict()), None
            except Exception as e:  # noqa: BLE001 - one missing recording mustn't stop the set
                src, err = None, str(e)
            for p in items.sort_values(["site", "species", "rank"], na_position="last").itertuples():
                eng = str(getattr(p, "common_name", "") or "")
                eng = "" if eng in ("nan", "None") else eng
                label = "" if blind else f"_{eng or p.species}_{p.rank}"
                fname = re.sub(r"[^A-Za-z0-9-]+", "_", f"{p.selection_id}{label}").strip("_") + ".wav"
                row = {"clip_id": p.selection_id, "clip_file": f"clips/{fname}", "site": p.site, "period": p.period}
                if not blind:
                    row.update(species=p.species, english_name=eng, why=p.why, score=round(float(p.score), 3))
                row.update({"detected_in_clip": "", **({"what_you_hear": ""} if blind else
                                                          {"correct (Y/N/?)": "", "if not, what is it": ""}),
                            "notes": ""})
                try:
                    if src is None:
                        raise FileNotFoundError(err)
                    info = sf.info(str(src))
                    dur = info.frames / info.samplerate
                    if clip_seconds:                                  # fixed length, centred on the peak
                        length = min(clip_seconds, dur)
                        start = max(0.0, min(p.peak_s + p.window_s / 2 - length / 2, dur - length))
                    else:                                             # the whole pass, padded
                        start = max(0.0, p.start_s - pad_seconds)
                        length = min(dur, p.end_s + pad_seconds) - start
                    a, sr = None, info.samplerate
                    if not (clips / fname).exists():
                        a, sr = sf.read(str(src), start=int(start * info.samplerate),
                                        stop=int(min(dur, start + length) * info.samplerate))
                        sf.write(str(clips / fname), a, sr)
                    marks = [w - start for w, s in json.loads(p.windows) if start <= w < start + length]
                    spans = [f"{max(0.0, w - start):.2f}s" + ("" if blind else f" ({s})")
                             for w, s in json.loads(p.windows) if start <= w < start + length]
                    if spectrograms:
                        png = out / "spectrograms" / (Path(fname).stem + ".png")
                        slow = out / "clips_slowed" / fname
                        try:
                            if not png.exists() or (group == "bats" and not slow.exists()):
                                if a is None:
                                    a, sr = sf.read(str(clips / fname))
                                SP.save(a, sr, png, group, marks, row["clip_id"])
                                if group == "bats":
                                    slow.parent.mkdir(parents=True, exist_ok=True)
                                    sf.write(str(slow), a, max(1, int(sr) // SP.SLOW))
                            row["spectrogram"] = f"spectrograms/{png.name}"
                            if group == "bats":
                                row["slowed_file"] = f"clips_slowed/{fname}"
                        except Exception as e:  # noqa: BLE001 - the clip is still there without its picture
                            row["notes"] = f"no spectrogram: {e}"
                    row["detected_in_clip"] = "; ".join(spans[:20]) + (" ..." if len(spans) > 20 else "")
                    row["clip_start_in_recording_s"] = round(start, 2)
                    row["clip_seconds"] = round(length, 2)
                except Exception as e:  # noqa: BLE001
                    row["notes"] = f"could not cut: {type(e).__name__}: {e}"
                rows.append(row)
                key.append({"clip_id": p.selection_id, "species": p.species, "english_name": eng, "why": p.why,
                            "score": p.score, "score_type": p.score_type, "unit_id": p.unit_id,
                            "recording": p.source_key})
            if src is not None:
                media.done_with(src)
    sheet = pd.DataFrame(rows)
    name = "model_check" if blind else "validation"
    sheet.to_csv(out / f"{name}_sheet.csv", index=False)
    if spectrograms and rows:
        SP.page(rows, out / "index.html", f"{group.capitalize()}: {name.replace('_', ' ')} ({len(rows)} clips)",
                bool(blind), group)
    if blind:
        pd.DataFrame(key).to_csv(out / "model_labels_KEY_do_not_send.csv", index=False)
    bad = int(sheet["notes"].astype(str).str.startswith("could not").sum()) if len(sheet) else 0
    return {"items": len(sheet), "problems": bad, "sheet": str(out / f"{name}_sheet.csv"), "blind": bool(blind),
            **({"page": str(out / "index.html")} if spectrograms and rows else {})}
