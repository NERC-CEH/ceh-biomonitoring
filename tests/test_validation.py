"""Manual validation: units, sampling (site-lists, model, all), platforms and collecting answers, on
made-up results (no models, no object store)."""
import json

import numpy as np
import pandas as pd
import pytest

from ceh_biomonitoring.validation import sampling as S
from ceh_biomonitoring.validation import units as U


# ------------------------------------------------------------------ made-up results
def bird_det():
    rows = []

    def add(day, hour, sp, starts, score, unlikely=False):
        key = f"/data/wood-1/2026{day}_{hour:02d}0000.wav"
        for s in starts:
            rows.append({"source_key": key, "filename": key.split("/")[-1], "start_time": float(s),
                         "end_time": float(s + 3), "species_name": sp, "confidence": score + s / 1000,
                         "deployment_id": "wood-1", "country_folder": "gbr", "unlikely_this_month": unlikely})
    add("0501", 5, "Sylvia atricapilla", [0, 3, 6], 0.6)          # one event (gaps < 60 s)
    add("0501", 5, "Sylvia atricapilla", [300, 303], 0.5)         # a second event (gap 291 s)
    add("0502", 5, "Sylvia atricapilla", [10], 0.9)               # best event, another day
    add("0503", 5, "Turdus merula", [0, 120], 0.7)                # two events
    add("0503", 5, "Botaurus stellaris", [50], 0.4, unlikely=True)
    return pd.DataFrame(rows).assign(results="r")


def bird_units():
    return U.audio_units(bird_det(), "birds")


def image_rows():
    rows = []

    def add(dep, img, track, cls, order, sp, conf, when="2026-06-01 23:00:00", odd=False):
        rows.append({"deployment_id": dep, "deployment_name": f"{dep} name", "image_path": img, "x_min": 10 + len(rows),
                     "y_min": 10, "x_max": 40 + len(rows), "y_max": 40, "class_name": cls, "order_name": order,
                     U.SPECIES: sp, U.SCORE: conf, "track_id": track, "image_datetime": when, "bucket_name": "sgp",
                     "rank_1_unlikely_this_month": odd})
    for i in range(10):                                   # one moth followed over 10 photos = ONE unit
        add("dep1", f"a{i}.jpg", "t1", "moth", "Lepidoptera", "Noctua pronuba", 0.5 + i / 100)
    for i in range(6):                                    # six separate moths on six nights
        add("dep1", f"b{i}.jpg", f"t{i + 2}", "moth", "Lepidoptera", "Noctua pronuba", i / 10,
            when=f"2026-06-0{i + 1} 22:00:00")
    add("dep2", "c.jpg", None, "moth", "Lepidoptera", "Noctua pronuba", 0.9)
    add("dep2", "d.jpg", "x", "moth", "Lepidoptera", "Biston betularia", 0.4, odd=True)
    for i in range(4):
        add("dep1", f"e{i}.jpg", f"n{i}", "nonmoth", "Diptera", None, None)
    return pd.DataFrame(rows).assign(results="r")


# ------------------------------------------------------------------ shared rules
def test_score_spread_covers_the_range_not_just_the_top():
    picked = sorted(S.score_spread(pd.DataFrame({"score": np.arange(100)}), 3)["score"])
    assert picked[0] < 20 and 40 < picked[1] < 60 and picked[2] > 80


def test_spread_covers_scores_and_nights():
    df = pd.DataFrame({"score": list(range(60)), "period": ["n1", "n1", "n2", "n1", "n1", "n3"] * 10})
    got = S.spread(df, 3)
    assert set(got.period) == {"n1", "n2", "n3"}
    assert got.score.min() < 20 and got.score.max() >= 40


def test_spread_reaches_across_the_season():
    days = pd.to_datetime(["2026-06-01"] * 30 + ["2026-06-02"] * 30 + ["2026-07-15"] * 5 + ["2026-09-20"] * 5)
    df = pd.DataFrame({"score": np.random.default_rng(1).random(70), "period": days.date.astype(str)})
    got = pd.to_datetime(S.spread(df, 4).period)
    assert got.dt.month.nunique() >= 3                                 # June, July and September, not all June


def test_model_groups_never_mix_countries():
    with pytest.raises(SystemExit):
        S.model_groups(pd.DataFrame({"bucket_name": ["sgp", "cri", None]}))      # one row says nothing: refuse
    assert S.model_groups(pd.DataFrame({"country": ["Singapore", "Costa Rica"]}))["model_group"].nunique() == 2
    assert S.model_groups(pd.DataFrame({"x": [1, 2]}), country="Anguilla")["model_group"].tolist() == ["Anguilla"] * 2
    with pytest.raises(SystemExit):
        S.model_groups(pd.DataFrame({"country": ["Singapore"]}), country="Costa Rica")   # disagreement: stop
    assert S.model_groups(pd.DataFrame({"bucket_name": ["sgp"]}), country="Singapore")["country"].tolist() == ["Singapore"]
    assert S.model_groups(pd.DataFrame({"country_folder": ["local", "gbr"], "bucket_name": [None, None]}).iloc[1:]
                          )["country"].tolist() == ["gbr"]


def test_across_sites_gives_every_site_one_first():
    g = pd.DataFrame({"site": ["a"] * 50 + ["b"] * 3 + ["c"] * 1, "score": range(54)})
    got = S.across_sites(g, 5)["site"].value_counts()
    assert set(got.index) == {"a", "b", "c"} and got.sum() == 5


# ------------------------------------------------------------------ audio units and sampling
def test_bird_events_join_close_detections_only():
    u = bird_units()
    bc = u[u.species == "Sylvia atricapilla"]
    assert len(bc) == 3                                                # 3 events, not 6 detections
    assert set(bc.period) == {"2026-05-01", "2026-05-02"}
    assert u.loc[u.species == "Botaurus stellaris", "unlikely"].all()
    assert u.unit_id.is_unique


def test_bat_passes_use_a_short_gap():
    det = pd.DataFrame({"source_key": ["20260601_220000.wav"] * 4, "filename": ["x"] * 4,
                        "start_time": [0.0, 0.1, 0.2, 5.0], "end_time": [0.01, 0.11, 0.21, 5.01],
                        "species_name": ["Pipistrellus pipistrellus"] * 4, "class_probability": [0.9, 0.8, 0.7, 0.6],
                        "detection_probability": [0.9] * 4, "deployment_id": ["d"] * 4, "results": ["r"] * 4})
    assert len(U.audio_units(det, "bats")) == 2                        # 5 s of quiet: a new pass


def test_bird_site_lists_best_then_another_day():
    sel = S.site_lists(bird_units(), "birds")
    bc = sel[sel.species == "Sylvia atricapilla"].sort_values("rank")
    assert list(bc.why) == ["best", "best on another day"] and bc.iloc[0].period != bc.iloc[1].period
    assert list(sel.columns[:len(S.COMMON_COLUMNS)]) == S.COMMON_COLUMNS
    assert "Botaurus stellaris" in set(sel.species)                    # no table: every species detected


def test_species_table_limits_site_lists_but_unusual_months_are_still_checked(tmp_path):
    t = tmp_path / "wood-1_site_species.csv"
    pd.DataFrame({"species": ["Sylvia atricapilla", "Turdus merula"], "listed": [True, False]}).to_csv(t, index=False)
    table = S.species_table([str(t)])
    assert set(S.site_lists(bird_units(), "birds", table=table, unusual_months=False).species) == {"Sylvia atricapilla"}
    sel = S.site_lists(bird_units(), "birds", table=table)
    assert sel.loc[sel.species == "Botaurus stellaris", "why"].tolist() == ["outside its usual months"]


def test_bird_model_sample_takes_every_species_and_skips_earlier_picks():
    u = bird_units()
    first = S.site_lists(u, "birds")
    sel = S.model(u, "birds", per_species=10, exclude=set(first.unit_id))
    assert not set(sel.unit_id) & set(first.unit_id) and set(sel.model_group) == {"gbr"}
    assert set(sel.purpose) == {"model"}


def test_reserve_units_are_marked_and_extra():
    sel = S.site_lists(bird_units(), "birds", per_species=1, reserve=1, unusual_months=False)
    bc = sel[sel.species == "Sylvia atricapilla"]
    assert list(bc.reserve) == [False, True] and bc.unit_id.is_unique


def test_audio_clips_model_sheets_are_blind(tmp_path):
    sf = pytest.importorskip("soundfile")
    from ceh_biomonitoring.validation.platforms import audio_clips
    det = bird_det()
    wav = tmp_path / "20260501_050000.wav"
    sf.write(wav, np.zeros(16000 * 400, dtype="float32"), 16000)
    det["source_key"] = det["source_key"].where(~det["source_key"].str.contains("0501"), str(wav))
    sel = S.model(U.audio_units(det, "birds"), "birds", per_species=5)
    sel = sel[sel.source_key == str(wav)]
    res = audio_clips.prepare(sel, tmp_path / "out")
    sheet = pd.read_csv(res["sheet"])
    assert res["blind"] and "species" not in sheet.columns and "what_you_hear" in sheet.columns
    assert (tmp_path / "out" / "model_labels_KEY_do_not_send.csv").exists()
    assert len(list((tmp_path / "out" / "clips").glob("*.wav"))) == len(sel) > 0


# ------------------------------------------------------------------ images
def test_image_tracks_are_one_unit_and_noise_is_kept_apart():
    u = U.image_units(image_rows())
    assert (u.unit_id == "dep1::t1").sum() == 1                       # 10 crops of one track -> one unit
    assert set(u.loc[u.noise_class.notna(), "species"]) == {"not a moth: Diptera"}
    assert u.detection_id.str.startswith("det_").all()
    assert len(U.image_units(image_rows(), per_crop=True)) == len(image_rows())    # all-crops: every crop


def test_image_site_lists_per_deployment_with_noise():
    sel = S.site_lists(U.image_units(image_rows()), "images", per_species=3, noise=2)
    d1 = sel[(sel.site == "dep1") & (sel.why == "species check")]
    assert len(d1) == 3 and d1.unit_id.nunique() == 3 and d1.period.nunique() == 3   # spread over nights
    assert sel.why.str.startswith("noise").sum() == 2
    assert sel[sel.species == "Biston betularia"].why.tolist() == ["species check"]


def test_image_model_sample_is_one_per_country():
    u = U.image_units(image_rows())
    u["country"] = u["deployment_id"].map({"dep1": "Singapore", "dep2": "Costa Rica"})
    sel = S.model(u, "images", per_species=10)
    assert set(sel.model_group) == {"Singapore", "Costa Rica"}
    for _, d in sel.groupby("model_group"):
        assert d.site.nunique() == 1


# ------------------------------------------------------------------ Mothbot
def photos(tmp_path, rows):
    from PIL import Image
    for p in rows["image_path"].unique():
        Image.new("RGB", (200, 100), (120, 120, 120)).save(tmp_path / p)
    return rows.assign(image_path=[str(tmp_path / p) for p in rows["image_path"]])


def test_mothbot_package_is_complete_and_checks(tmp_path):
    pytest.importorskip("PIL")
    from ceh_biomonitoring.validation.platforms import mothbot
    sel = S.site_lists(U.image_units(photos(tmp_path, image_rows())), "images", per_species=2, noise=1)
    res = mothbot.prepare(sel, tmp_path / "pkgs", cluster=False, keep_unzipped=True, round_date="2026-11-18")
    pkgs = {p["package"]: p for p in res["packages"]}
    assert len(pkgs) == 2 and res["blind"]                            # one package per deployment, blind
    pkg = tmp_path / "pkgs" / "dep1" / "2026-11-18_site-lists"
    assert mothbot.check(pkg) == [] and pkg.with_suffix(".zip").exists()
    assert mothbot.check(pkg.with_suffix(".zip")) == []              # what's sent is checked too
    patches = mothbot.read_ndjson(pkg / "02_records" / "patches.ndjson")
    assert len(patches) == (sel.deployment_id == "dep1").sum()
    nights = {p["camera_day_id"].split("__")[1] for p in patches}
    assert "2026-06-01" in nights and not (pkg / "03_classifications" / "_bot.ndjson").exists()
    assert (tmp_path / "pkgs" / "dep1" / "2026-11-18_site-lists_provenance.csv").exists()
    again = mothbot.prepare(sel, tmp_path / "pkgs", cluster=False, round_date="2026-11-18")
    assert all("skipped" in p for p in again["packages"])            # finished packages aren't rebuilt


def test_mothbot_screens_replace_from_the_reserve(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    from ceh_biomonitoring.validation import embeddings as E
    from ceh_biomonitoring.validation.platforms import mothbot
    u = U.image_units(photos(tmp_path, image_rows()))
    sel = S.site_lists(u[u.site == "dep1"], "images", per_species=2, noise=0, reserve=2, unusual_months=False)
    first = sel[(sel.species == "Noctua pronuba") & ~sel.reserve].iloc[0]["detection_id"]
    # every crop far from the 'gecko' centroid except the first pick
    monkeypatch.setattr(E, "embed", lambda paths, settings, **k: np.array(
        [[0.0] * 384 if p.stem == first else [9.0] * 384 for p in paths], dtype=np.float32))
    ref = tmp_path / "gecko.npz"
    np.savez(ref, centroid=np.zeros(384, dtype=np.float32), threshold=1.0, name="gecko")
    res = mothbot.prepare(sel, tmp_path / "pk", cluster=False, screens=[str(ref)], round_date="2026-11-18",
                          keep_unzipped=True)
    p = res["packages"][0]
    assert p["screened_out"] == 1 and p["reserve_used"] == 1 and p["crops"] == 2   # target still met
    ids = {x["patch_id"] for x in mothbot.read_ndjson(tmp_path / "pk" / "dep1" / "2026-11-18_site-lists" / "02_records" / "patches.ndjson")}
    assert first not in ids


def test_collect_reads_mothbot_answers(tmp_path):
    pytest.importorskip("PIL")
    from ceh_biomonitoring.validation import collect
    from ceh_biomonitoring.validation.platforms import mothbot
    sel = S.site_lists(U.image_units(photos(tmp_path, image_rows())), "images", per_species=1, noise=0)
    mothbot.prepare(sel, tmp_path / "pk", cluster=False, round_date="2026-11-18", keep_unzipped=True)
    pkg = tmp_path / "pk" / "dep2" / "2026-11-18_site-lists"
    ids = [x["patch_id"] for x in mothbot.read_ndjson(pkg / "02_records" / "patches.ndjson")]
    want = dict(zip(sel.detection_id, sel.species))
    ans = [{"patch_id": i, "classifier_id": "ad", "classifier_type": "human", "label": want[i] if n == 0 else "Agrotis exclamationis",
            "taxon": {"taxonRank": "species"}, "classified_at": 1} for n, i in enumerate(ids)]
    (pkg / "03_classifications" / "ad.ndjson").write_text("\n".join(json.dumps(a) for a in ans))
    got = collect.mothbot(sel, [pkg])
    assert len(got) == len(ids) and got["agrees"].tolist() == [True] + [False] * (len(ids) - 1)


def test_image_results_load_from_parquet_skipping_empty_photos(tmp_path):
    rows = image_rows()
    empty = rows.iloc[:3].assign(x_min=None, y_min=None, x_max=None, y_max=None, track_id=None)   # photos with no insect
    pd.concat([rows, empty]).rename(columns={U.SPECIES: "top_species_prediction"}).to_parquet(
        tmp_path / "dep_analysis_ready.parquet")                       # an older column name, too
    u = U.load([str(tmp_path)], "images")
    assert len(u) == len(U.image_units(image_rows())) and "Noctua pronuba" in set(u.species)


def test_detection_ids_match_the_labelling_pipeline():
    df = pd.DataFrame({"deployment_id": ["dep000145", " dep1 "], "image_path": ["/x/a.jpg", "b.jpg"],
                       "x_min": [10, 0.1 + 0.2], "y_min": [2.5, 3], "x_max": [100, 4], "y_max": [7, 1e-7]})
    assert U.detection_ids(df) == [U.detection_id(*r) for r in df[["deployment_id", "image_path", "x_min", "y_min",
                                                                     "x_max", "y_max"]].itertuples(index=False)]
