"""Night videos and soundscapes, from made-up photos and recordings (needs the videos extra)."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

av = pytest.importorskip("av")
sf = pytest.importorskip("soundfile")
PIL = pytest.importorskip("PIL")

from ceh_biomonitoring import chunks, layout  # noqa: E402
from ceh_biomonitoring.settings import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CEHBIO_CONFIG_DIR", str(tmp_path / "cfg"))
    return Settings.load(profile="local", overrides={"outputs_root": str(tmp_path / "out"), "tmp_root": str(tmp_path / "tmp")},
                         settings_file=tmp_path / "none.yml")


def _photos(settings, tmp_path, dep="trap-1"):
    from PIL import Image, ImageDraw
    rp = layout.new_paths(settings.outputs_root, "images", "farm", dep)
    chunks.write_json(rp.manifest, {"n_chunks": 1})
    card = tmp_path / "card"
    card.mkdir()
    files, rows = [], []
    start = datetime(2026, 5, 11, 21, 30)
    for k in range(12):
        when = start + timedelta(minutes=10 * k)
        name = f"01-{when:%Y%m%d%H%M%S}-snapshot.jpg"
        im = Image.new("RGB", (800, 600), (235, 235, 225))
        d = ImageDraw.Draw(im)
        x = 100 + 30 * k                                  # one moth walking across the sheet
        d.ellipse([x, 200, x + 50, 240], fill=(120, 90, 60))
        d.ellipse([500, 400, 530, 420], fill=(30, 30, 30))   # a fly sitting still
        im.save(card / name)
        files.append({"source_key": str(card / name), "filename": name, "status": "detections"})
        rows.append({"image_path": str(card / name), "image_datetime": f"{when:%Y-%m-%d %H:%M:%S}", "deployment_id": dep,
                     "x_min": x, "y_min": 200, "x_max": x + 50, "y_max": 240, "class_name": "moth",
                     "order_name": "Lepidoptera Macros", "regional_species_rank_1_name": "Noctua pronuba",
                     "regional_species_rank_1_confidence": 0.8, "track_id": "Track_000001"})
        rows.append({"image_path": str(card / name), "image_datetime": f"{when:%Y-%m-%d %H:%M:%S}", "deployment_id": dep,
                     "x_min": 500, "y_min": 400, "x_max": 530, "y_max": 420, "class_name": "nonmoth",
                     "order_name": "Diptera Brachycera", "regional_species_rank_1_name": None,
                     "regional_species_rank_1_confidence": None, "track_id": "Track_000002"})
    pd.DataFrame(files).to_csv(rp.root / f"{dep}_files.csv", index=False)
    pd.DataFrame(rows).to_parquet(rp.root / f"{dep}_analysis_ready.parquet", index=False)
    return rp


def _frames(path):
    with av.open(str(path)) as c:
        v = c.streams.video[0]
        n = sum(1 for _ in c.decode(video=0))
        return n, v.codec_context.name, [s.type for s in c.streams]


def test_a_night_and_one_insect(settings, tmp_path):
    from ceh_biomonitoring.videos import night
    rp = _photos(settings, tmp_path)
    out = night.make(settings, "farm", "trap-1", individuals=1, fps=4)
    names = [p.name for p in out]
    assert names == ["trap-1_2026-05-11.mp4", "trap-1_2026-05-11_Track_000001.mp4"]
    assert all(p.parent == rp.root / "videos" for p in out)
    n, codec, kinds = _frames(out[0])
    assert n == 12 and codec == "h264" and kinds == ["video"]
    assert _frames(out[1])[0] == 12


def test_photos_that_cant_be_found_are_said(settings, tmp_path):
    from ceh_biomonitoring.videos import night
    _photos(settings, tmp_path)
    import shutil
    shutil.rmtree(tmp_path / "card")
    assert night.make(settings, "farm", "trap-1") == []


def _recordings(settings, tmp_path, pipeline="birds", dep="wood-1"):
    rp = layout.new_paths(settings.outputs_root, pipeline, "woods", dep)
    chunks.write_json(rp.manifest, {"n_chunks": 1})
    folder = tmp_path / "rec"
    folder.mkdir()
    sr = 48000 if pipeline == "birds" else 256000
    rows = []
    for h in (5, 6):
        name = f"20260511_{h:02d}0000.WAV"
        t = np.arange(sr * 30) / sr
        a = 0.01 * np.random.default_rng(h).standard_normal(len(t))
        f0 = 3000 if pipeline == "birds" else 45000
        a[(t > 10) & (t < 12)] += 0.3 * np.sin(2 * np.pi * f0 * t[(t > 10) & (t < 12)])
        sf.write(folder / name, a.astype(np.float32), sr)
        sp = "Turdus merula" if h == 5 else "Erithacus rubecula"
        row = {"source_key": str(folder / name), "filename": name, "start_time": 9.0, "end_time": 12.0, "species_name": sp}
        if pipeline == "birds":
            row.update(confidence=0.9, common_name="Eurasian Blackbird" if h == 5 else "European Robin")
        else:
            row.update(start_time=10.0, end_time=10.01, class_probability=0.8, low_freq=40000.0, high_freq=50000.0)
        rows.append(row)
    pd.DataFrame(rows).to_parquet(rp.root / f"{dep}_detections.parquet", index=False)
    return rp


def test_bird_soundscape_has_sound_and_a_day_overview(settings, tmp_path):
    from ceh_biomonitoring.videos import soundscape
    _recordings(settings, tmp_path)
    out = soundscape.make(settings, "birds", "woods", "wood-1")
    video, png = out
    n, codec, kinds = _frames(video)
    assert kinds == ["video", "audio"] and codec == "h264"
    assert 20 * 20 * 0.9 < n < 21 * 20 * 1.1               # two 10 s highlights at 20 frames a second, plus gaps
    assert png.suffix == ".png" and png.stat().st_size > 10_000


def test_bats_are_slowed_ten_times(settings, tmp_path):
    from ceh_biomonitoring.videos import soundscape
    _recordings(settings, tmp_path, "bats")
    out = soundscape.make(settings, "bats", "woods", "wood-1", day="2026-05-10")
    with av.open(str(out[0])) as c:
        assert 19 < float(c.duration) / 1e6 < 22            # two 1 s passes become about 20 s
