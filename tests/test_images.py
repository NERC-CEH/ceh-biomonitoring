"""Images pipeline: everything that runs without the models (no PyTorch needed)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from ceh_biomonitoring import chunks, devices, modelstore, pipelines
from ceh_biomonitoring.pipelines.images import (image_datetime, model_list, recording_session,
                                                species_model_for)
from ceh_biomonitoring.pipelines.images import filters as F
from ceh_biomonitoring.pipelines.images import tracking as T


def test_nights_and_dates():
    assert recording_session(datetime(2026, 8, 6, 2, 53)) == "2026-08-05"     # before noon: previous night
    assert recording_session(datetime(2026, 8, 6, 21, 0)) == "2026-08-06"
    assert image_datetime("ami-mini-20250428T210338.jpg") == datetime(2025, 4, 28, 21, 3, 38)
    assert image_datetime("dep1/snapshot_images/20240725204340-snapshot.jpg") == datetime(2024, 7, 25, 20, 43, 40)
    lep = devices.get("lepisense")
    assert image_datetime("site/123456789012345-20260806T025318.jpg", lep) == datetime(2026, 8, 6, 2, 53, 18)


def test_whole_nights_go_in_one_chunk_in_time_order():
    p = pipelines.get("images")
    keys = ["20240725230000-snapshot.jpg", "20240726020000-snapshot.jpg", "20240725210000-snapshot.jpg",
            "20240726220000-snapshot.jpg", "no-date.jpg"]
    groups = p.group_files(keys)
    assert groups == [["20240725210000-snapshot.jpg", "20240725230000-snapshot.jpg", "20240726020000-snapshot.jpg"],
                      ["20240726220000-snapshot.jpg"], ["no-date.jpg"]]
    assert chunks.pack(groups, 3) == [groups[0], groups[1] + groups[2]]
    assert chunks.pack([["a"] * 5], 2) == [["a", "a"], ["a", "a"], ["a"]]          # only a huge night is split


def test_region_picks_species_model():
    assert species_model_for("UK") == "moth-species-uk-v3"
    assert species_model_for("costa rica") == "moth-species-costa-rica-v3"
    with pytest.raises(SystemExit):
        species_model_for("atlantis")
    ml = model_list()
    for name, m in ml["models"].items():                       # every file is pinned by a checksum
        for f in m["files"].values():
            assert len(f["sha256"]) == 64 and f["bytes"] > 0, name
        if m["stage"] == "species":
            assert set(m["files"]) == {"weights", "labels"} and m["files"]["weights"]["asset"].startswith(name)


def test_costs_match_amber_inferences():
    a = {"embedding": np.array([1.0, 0.0]), "box": [0, 0, 9, 9], "image_size": (100, 100), "crop": "crop_1"}
    b = {"embedding": np.array([1.0, 0.0]), "box": [0, 0, 9, 9], "image_size": (100, 100), "crop": "crop_1"}
    c = T.cost(a, b)
    assert c["total_cost"] == pytest.approx(0.0)
    far = {**b, "box": [80, 80, 89, 89], "embedding": np.array([0.0, 1.0])}
    c = T.cost(a, far)
    assert c["cnn_cost"] == pytest.approx(1.0) and c["iou_cost"] == 1.0
    assert c["dist_ratio_cost"] == pytest.approx(np.hypot(80, 80) / np.hypot(100, 100))
    m = T.best_match([a, {**far, "crop": "crop_2"}], "prev.jpg", b, "crop_1")
    assert m["best_match_crop"] == "crop_1" and m["previous_image"] == "prev.jpg"
    assert T.best_match([], None, b, "crop_3")["best_match_crop"] == T.NO_PREVIOUS
    assert "No embedding" in T.best_match([a], "prev.jpg", None, "crop_4")["best_match_crop"]


def test_tracks_link_across_photos():
    rows = pd.DataFrame([
        {"image_path": "d/1.jpg", "image_datetime": "2026-01-01 21:00:00", "crop_status": "crop_1",
         "previous_image": None, "best_match_crop": T.NO_PREVIOUS, "total_cost": None, "class_name": "moth"},
        {"image_path": "d/2.jpg", "image_datetime": "2026-01-01 21:02:00", "crop_status": "crop_1",
         "previous_image": "1.jpg", "best_match_crop": "crop_1", "total_cost": 0.4, "class_name": "moth"},
        {"image_path": "d/3.jpg", "image_datetime": "2026-01-01 21:04:00", "crop_status": "crop_1",
         "previous_image": "2.jpg", "best_match_crop": "crop_1", "total_cost": 1.6, "class_name": "moth"},
        {"image_path": "d/4.jpg", "image_datetime": "2026-01-01 21:06:00", "crop_status": T.NO_DETECTION},
    ])
    ready, tracks = T.build_tracks(rows, 1.0)
    ids = ready.set_index("image_path")["track_id"]
    assert ids["d/1.jpg"] == ids["d/2.jpg"] != ids["d/3.jpg"] and pd.isna(ids["d/4.jpg"])
    assert list(ready["tracking_decision"]) == ["new_track_missing_tracking", "linked_to_previous_track",
                                                "new_track_cost_above_threshold", "no_detection"]
    assert len(tracks) == 2 and tracks["track_length_images"].max() == 2


def test_filter_rules(tmp_path):
    f = tmp_path / "f.yml"
    f.write_text("""filters:
  - {name: gecko, when: {relative_area_min: 0.02, aspect_min: 2.5}}
  - {name: rig, action: remove, when: {filename_matches: "^ami-mini-", zone: [0.36, 0.18, 0.66, 0.50]}}
  - {name: leaf, stage: order, when: {order_name: [Vegetation]}}
""")
    rules = F.load_rules(str(f))
    gecko = {"x_min": 0, "y_min": 0, "x_max": 300, "y_max": 100, "box_score": 0.9, "filename": "x.jpg"}
    assert F.apply(rules, "detection", gecko, 1000, 1000) == (False, ["gecko"])
    rig = {"x_min": 480, "y_min": 300, "x_max": 520, "y_max": 340, "box_score": 0.9, "filename": "ami-mini-1.jpg"}
    assert F.apply(rules, "detection", rig, 1000, 1000) == (True, ["rig"])
    assert F.apply(rules, "order", {**rig, "order_name": "Vegetation"}, 1000, 1000) == (False, ["leaf"])
    bad = tmp_path / "bad.yml"
    bad.write_text("filters:\n  - {name: x, when: {order_name: [Araneae]}}\n")      # order rule at detection stage
    with pytest.raises(SystemExit):
        F.load_rules(str(bad))


def test_mask(tmp_path):
    from PIL import Image
    a = np.full((100, 200), 255, np.uint8)
    a[:, :50] = 0                                              # left quarter: ignore
    Image.fromarray(a).save(tmp_path / "m.png")
    m = F.Mask(str(tmp_path / "m.png"))
    assert m.ignored((0, 0, 40, 40), 400, 200)                 # mask is rescaled to the photo
    assert not m.ignored((300, 0, 340, 40), 400, 200)
    assert m.ignored((60, 0, 120, 40), 400, 200)               # 2/3 of the box is in the black area
    assert not F.Mask(str(tmp_path / "m.png"), overlap=0.9).ignored((60, 0, 120, 40), 400, 200)


def test_mask_suggest(tmp_path):
    from PIL import Image
    from ceh_biomonitoring.pipelines.images import masktool
    Image.new("RGB", (400, 300)).save(tmp_path / "photo.jpg")
    det = pd.DataFrame([{"source_key": f"{i}.jpg", "x_min": 10, "y_min": 10, "x_max": 60, "y_max": 60}
                        for i in range(10)] + [{"source_key": "0.jpg", "x_min": 300, "y_min": 200,
                                                "x_max": 320, "y_max": 220}])
    det.to_parquet(tmp_path / "det.parquet")
    r = masktool.suggest(tmp_path / "det.parquet", tmp_path / "photo.jpg", tmp_path / "mask.png", 0.5)
    m = F.Mask(r["mask"])
    assert m.ignored((15, 15, 55, 55), 400, 300) and not m.ignored((300, 200, 320, 220), 400, 300)
    assert (tmp_path / "mask_preview.jpg").exists()


def test_modelstore_finds_local_copy_and_checks_it(tmp_path, monkeypatch):
    from ceh_biomonitoring.settings import Settings
    team = tmp_path / "team_models" / "species" / "weights"
    team.mkdir(parents=True)
    (team / "w.pt").write_bytes(b"weights")
    good = hashlib.sha256(b"weights").hexdigest()
    s = Settings.load(profile="local", settings_file=tmp_path / "none.yml",
                      overrides={"models": {"cache_dir": str(tmp_path / "cache"),
                                            "search_dirs": [str(tmp_path / "team_models")]}})
    ml = {"models": {"m": {"files": {"weights": {"name": "w.pt", "bytes": 7, "sha256": good}}}}}
    assert modelstore.fetch(s, ml, "m", "weights") == team / "w.pt"
    modelstore._INDEX.clear()
    ml["models"]["m"]["files"]["weights"]["sha256"] = "0" * 64              # wrong file: not used, not downloadable
    assert modelstore.fetch(s, ml, "m", "weights") is None
    with pytest.raises(SystemExit):
        modelstore.fetch(s, ml, "nope", "weights")


def test_after_combine_builds_analysis_ready_and_tracks(tmp_path):
    p = pipelines.get("images")
    det = pd.DataFrame([
        {"source_key": "d/1.jpg", "image_path": "d/1.jpg", "image_datetime": "2026-01-01 21:00:00",
         "crop_status": "crop_1", "class_name": "moth", "previous_image": None,
         "best_match_crop": T.NO_PREVIOUS, "total_cost": None},
        {"source_key": "d/2.jpg", "image_path": "d/2.jpg", "image_datetime": "2026-01-01 21:02:00",
         "crop_status": "crop_1", "class_name": "moth", "previous_image": "1.jpg",
         "best_match_crop": "crop_1", "total_cost": 0.2}])
    files = pd.DataFrame([{"source_key": "d/3.jpg", "status": "no_detections",
                           "image_datetime": "2026-01-01 21:04:00"}])
    qa = p.after_combine(tmp_path, "dep1", det, files, p.params())
    assert qa["n_crops"] == 2 and qa["n_tracks"] == 1
    ready = pd.read_parquet(tmp_path / "dep1_analysis_ready.parquet")
    assert len(ready) == 3 and (ready["crop_status"] == T.NO_DETECTION).sum() == 1
    assert (tmp_path / "dep1_tracks.parquet").exists()


def test_newest_model_is_the_default():
    from ceh_biomonitoring.pipelines.images import latest, resolve
    assert latest("detector") == "insect-detector-flatbug-m-v2"
    assert latest("order") == "insect-order-v2" and latest("binary") == "moth-vs-nonmoth-v2"
    assert resolve("latest", "order") == "insect-order-v2" and resolve("insect-order-v1", "order") == "insect-order-v1"
    ml = {"models": {"a-v1": {"stage": "species", "region": "x", "released": "2024-01-01"},
                     "a-v10": {"stage": "species", "region": "x", "released": "2026-01-01"},
                     "a-v9": {"stage": "species", "region": "x", "released": "2025-01-01"}}}
    assert species_model_for("x", ml) == "a-v10"                 # by release date, not by name
    for m in model_list()["models"].values():
        if m["stage"] == "species":
            assert m["licence"].startswith("CC BY-NC 4.0")


def test_outline_measurements():
    from ceh_biomonitoring.pipelines.images import outline
    rect = [(0, 0), (40, 0), (40, 10), (0, 10)]
    m = outline.measure(rect)
    assert m["outline_area_px"] == pytest.approx(400) and m["outline_length_px"] == pytest.approx(40)
    assert m["outline_width_px"] == pytest.approx(10)
    c, s_ = np.cos(np.pi / 6), np.sin(np.pi / 6)                 # same insect, turned 30 degrees
    rot = [(x * c - y * s_, x * s_ + y * c) for x, y in rect]
    m2 = outline.measure(rot)
    assert m2["outline_length_px"] == pytest.approx(40) and m2["outline_width_px"] == pytest.approx(10)
    cols = outline.columns(rect, pixels_per_mm=10)
    assert cols["outline_length_mm"] == pytest.approx(4) and cols["outline_area_mm2"] == pytest.approx(4)
    assert json.loads(cols["outline"])[1] == [40, 0]


def test_flatbug_outline_layout_is_read_correctly():
    torch = pytest.importorskip("torch")
    from ceh_biomonitoring.pipelines.images import nets

    class Fake:
        def __call__(self, path):
            class R:
                json_data = {"boxes": [[10, 20, 50, 40]], "confs": [0.9], "classes": [0],
                             "contours": [torch.tensor([[10.0, 50, 50, 10], [20.0, 20, 40, 40]])]}
            return R()
    (row,) = nets.detect_flatbug(Fake(), "x.jpg")
    assert row[6] == [[10, 20], [50, 20], [50, 40], [10, 40]]
