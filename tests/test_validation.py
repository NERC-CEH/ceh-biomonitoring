"""Manual validation: units, sampling (site-lists, model, all), platforms and collecting answers, on
made-up results (no models, no object store)."""
import json

import numpy as np
import pandas as pd
import pytest

from ceh_biomonitoring.validation import sampling as S
from ceh_biomonitoring.validation import units as U


# ------------------------------------------------------------------ a made-up GBIF (no internet in tests)
TAXA = {
    797: {"key": 797, "scientificName": "Lepidoptera", "canonicalName": "Lepidoptera", "rank": "ORDER",
          "taxonomicStatus": "ACCEPTED", "kingdom": "Animalia", "phylum": "Arthropoda", "class": "Insecta",
          "order": "Lepidoptera", "kingdomKey": 1, "phylumKey": 54, "classKey": 216, "orderKey": 797},
    811: {"key": 811, "scientificName": "Diptera", "canonicalName": "Diptera", "rank": "ORDER",
          "taxonomicStatus": "ACCEPTED", "kingdom": "Animalia", "phylum": "Arthropoda", "class": "Insecta",
          "order": "Diptera", "kingdomKey": 1, "phylumKey": 54, "classKey": 216, "orderKey": 811},
    1794467: {"key": 1794467, "scientificName": "Noctua pronuba (Linnaeus, 1758)", "canonicalName": "Noctua pronuba",
              "rank": "SPECIES", "taxonomicStatus": "ACCEPTED", "kingdom": "Animalia", "phylum": "Arthropoda",
              "class": "Insecta", "order": "Lepidoptera", "family": "Noctuidae", "genus": "Noctua",
              "species": "Noctua pronuba", "orderKey": 797, "speciesKey": 1794467,
              "vernacularName": "Large Yellow Underwing"},
    1987000: {"key": 1987000, "scientificName": "Biston betularia (Linnaeus, 1758)", "canonicalName": "Biston betularia",
              "rank": "SPECIES", "taxonomicStatus": "ACCEPTED", "kingdom": "Animalia", "phylum": "Arthropoda",
              "class": "Insecta", "order": "Lepidoptera", "family": "Geometridae", "genus": "Biston",
              "species": "Biston betularia", "orderKey": 797, "speciesKey": 1987000},
    5555: {"key": 5555, "scientificName": "Agrius convolvuli (Linnaeus, 1758)", "canonicalName": "Agrius convolvuli",
           "rank": "SPECIES", "taxonomicStatus": "ACCEPTED", "kingdom": "Animalia", "phylum": "Arthropoda",
           "class": "Insecta", "order": "Lepidoptera", "family": "Sphingidae", "genus": "Agrius",
           "species": "Agrius convolvuli", "orderKey": 797, "speciesKey": 5555},
}


@pytest.fixture(autouse=True)
def fake_gbif(tmp_path, monkeypatch):
    from ceh_biomonitoring.validation import gbif
    monkeypatch.setattr(gbif, "cache_dir", lambda settings=None: tmp_path / "gbif-cache")
    by_name = {t["canonicalName"]: k for k, t in TAXA.items()}

    def get(self, path, **params):
        if path == "species/match":
            k = by_name.get(params["name"])
            return {"usageKey": k, "matchType": "EXACT", "confidence": 99} if k else {"matchType": "NONE"}
        if path.startswith("species/"):
            t = TAXA.get(int(path.split("/")[1]))
            return dict(t, datasetKey=gbif.BACKBONE) if t else None
        if path == "enumeration/country":
            return [{"iso2": "SG", "iso3": "SGP", "title": "Singapore"}]
        if path == "occurrence/search":
            got = [{"name": "5555", "count": 12}, {"name": "1794467", "count": 3}] if params["country"] == "SG" else []
            return {"facets": [{"field": "SPECIES_KEY", "counts": got[params["facetOffset"]:]}]}
        return None
    monkeypatch.setattr(gbif.Backbone, "_get", get)


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


# ------------------------------------------------------------------ times, file types, species lists, machine IDs
def test_times_are_read_whatever_their_layout():
    from ceh_biomonitoring import times as T
    got = T.parse(pd.Series(["2024-11-01 20:57:39", "2024-11-01T20:57:39+08:00", "2024:11:01 20:57:39",
                             "20241101205739", None, "", "not a time"], dtype=object))
    assert got.iloc[:4].eq(pd.Timestamp("2024-11-01 20:57:39")).all() and got.iloc[4:].isna().all()
    assert T.parse(pd.Series([1730494659, 1730494659000])).eq(pd.Timestamp("2024-11-01 20:57:39")).all()
    for name, want in [("20240725204340-snapshot.jpg", "2024-07-25 20:43:40"),
                       ("01-20240204211800-snapshot.jpg", "2024-02-04 21:18:00"),
                       ("ami-mini-20250428T210338.jpg", "2025-04-28 21:03:38"),
                       ("123456789012345-20260806T025318.jpg", "2026-08-06 02:53:18"),
                       ("bowedBarbo_2026-07-06T22-03-07+02-00.jpg", "2026-07-06 22:03:07"),
                       ("SMA01234_20240705_043000.wav", "2024-07-05 04:30:00")]:
        assert str(T.from_name(name)) == want, name
    assert T.from_name("$R6USYHX.jpg") is None
    # the results win over the file name (they carry clock corrections); the file name fills gaps
    when, src, n = T.best(["2024-11-06 19:00:00", None], ["20230519003840-snapshot.jpg", "20240101210000-snapshot.jpg"])
    assert list(src) == ["results", "file name"] and n == 1 and when[1] == pd.Timestamp("2024-01-01 21:00:00")


def test_image_units_skip_recycle_bin_and_broken_rows_and_use_file_times():
    rows = image_rows()
    junk = rows.iloc[:2].assign(image_path=["$RVRFTOJ.jpg", "319502299373"])
    no_time = rows.iloc[[11]].assign(image_path="20260603221500-snapshot.jpg", image_datetime=None, track_id="z")
    u = U.image_units(pd.concat([rows, junk, no_time], ignore_index=True))
    assert not u["image_path"].isin(["$RVRFTOJ.jpg", "319502299373"]).any()
    z = u[u["image_path"] == "20260603221500-snapshot.jpg"].iloc[0]
    assert z["time_source"] == "file name" and z["period"] == "2026-06-03"


def test_mothbot_package_has_a_gbif_backbone_species_list(tmp_path):
    pytest.importorskip("PIL")
    from ceh_biomonitoring.validation.platforms import mothbot
    sel = S.site_lists(U.image_units(photos(tmp_path, image_rows())), "images", per_species=2, noise=1)
    mothbot.prepare(sel, tmp_path / "pkgs", cluster=False, keep_unzipped=True, round_date="2026-11-18")
    pkg = tmp_path / "pkgs" / "dep1" / "2026-11-18_site-lists"
    man = json.loads((pkg / "dataset.json").read_text())
    assert man["species_lists"] == ["species/SpeciesList_Singapore_Lepidoptera-GBIF-backbone-2026-11-18.csv"]
    t = pd.read_csv(pkg / man["species_lists"][0], sep="\t")
    assert {"taxonKey", "scientificName", "species", "family", "numberOfOccurrences"} <= set(t.columns)
    # the country's GBIF list (Agrius) and the species the models named (Noctua), with backbone keys
    assert {5555, 1794467} <= set(t["taxonKey"].dropna().astype(int))
    assert t.set_index("taxonKey").loc[5555, "numberOfOccurrences"] == 12
    assert not (pkg / "03_classifications" / "_bot.ndjson").exists()     # still blind by default
    deps = mothbot.read_ndjson(pkg / "02_records" / "deployments.ndjson")
    first = min(c["night_date"] for c in mothbot.read_ndjson(pkg / "02_records" / "camera-days.ndjson"))
    assert deps[0]["device_id_from_folder"] == "dep1 name" and deps[0]["deployment_start_from_folder"] == first
    assert mothbot.check(pkg) == []


def test_mothbot_machine_ids_follow_mothbots_format_when_shown(tmp_path):
    pytest.importorskip("PIL")
    from ceh_biomonitoring.validation.platforms import mothbot
    rows = image_rows().assign(global_species_rank_1_name="Biston betularia", global_species_rank_1_gbif_id=1987000.0,
                               global_species_rank_1_confidence=0.3, global_model_key="global_hierarchical_classifier",
                               analysis_datetime="2026-06-10 14:55:41")
    sel = S.site_lists(U.image_units(photos(tmp_path, rows)), "images", per_species=1, noise=1)
    mothbot.prepare(sel, tmp_path / "pk", cluster=False, keep_unzipped=True, round_date="2026-11-18", blind=False)
    pkg = tmp_path / "pk" / "dep1" / "2026-11-18_site-lists"
    bot = mothbot.read_ndjson(pkg / "03_classifications" / "_bot.ndjson")
    moth = [b for b in bot if b["taxon"].get("scientificName") == "Noctua pronuba"][0]
    assert moth["classifier_type"] == "bot" and moth["classified_at"] == 1          # the default machine ID
    assert moth["taxon"]["taxonID"] == 1794467 and moth["taxon"]["taxonIDSource"] == "gbif-backbone"
    assert moth["taxon"]["genus"] == "Noctua" and moth["taxon"]["species"] == "pronuba"
    assert moth["species_list"].startswith("SpeciesList_") and moth["machine_identified_at"].startswith("2026-06-10")
    same = [b for b in bot if b["patch_id"] == moth["patch_id"]]
    assert {b["classifier_id"] for b in same} == {"regional-species-model", "global_hierarchical_classifier", "order-model"}
    glob = [b for b in same if b["classifier_id"] == "global_hierarchical_classifier"][0]
    assert glob["taxon"]["taxonID"] == 1987000 and glob["classified_at"] is None
    fly = [b for b in bot if b["taxon"].get("scientificName") == "Diptera"]
    assert fly and fly[0]["classified_at"] == 1 and fly[0]["taxon"]["taxonRank"] == "order"
    assert mothbot.check(pkg) == []


def test_mothbot_times_are_strict_iso_and_bad_dates_are_caught(tmp_path):
    pytest.importorskip("PIL")
    from ceh_biomonitoring.validation.platforms import mothbot
    assert mothbot.iso_time(pd.Timestamp("2026-06-12 23:00:55")) == "2026-06-12T23:00:55"
    assert mothbot.iso_time(pd.Timestamp("2026-06-12 23:00:55"), "UTC") == "2026-06-12T23:00:55+00:00"
    sel = S.site_lists(U.image_units(photos(tmp_path, image_rows())), "images", per_species=1, noise=0)
    mothbot.prepare(sel, tmp_path / "pk", cluster=False, keep_unzipped=True, round_date="2026-11-18",
                    species_list="none", clock_timezone="UTC")
    pkg = tmp_path / "pk" / "dep1" / "2026-11-18_site-lists"
    recs = mothbot.read_ndjson(pkg / "02_records" / "patches.ndjson")
    assert all(p["captured_at"].endswith("+00:00") for p in recs) and mothbot.check(pkg) == []
    recs[0]["captured_at"] = "06/12/2026 23:00:55"                      # what Mothbot misread before
    (pkg / "02_records" / "patches.ndjson").write_text("\n".join(json.dumps(p) for p in recs))
    assert any("ISO 8601" in p for p in mothbot.check(pkg))


def test_mothbot_reads_16_bit_and_png_photos(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    from ceh_biomonitoring.validation.platforms import mothbot
    rows = image_rows()
    rows = rows[rows.deployment_id == "dep2"].assign(image_path=["c.png", "d.tif"])
    Image.fromarray((np.arange(100 * 200).reshape(100, 200) % 65535).astype(np.uint16)).save(tmp_path / "c.png")
    Image.new("RGBA", (200, 100), (10, 200, 10, 128)).save(tmp_path / "d.tif")
    rows = rows.assign(image_path=[str(tmp_path / p) for p in rows["image_path"]])
    sel = S.site_lists(U.image_units(rows), "images", per_species=1, noise=0)
    res = mothbot.prepare(sel, tmp_path / "pk", cluster=False, keep_unzipped=True, round_date="2026-11-18",
                          species_list="none")
    assert res["packages"][0]["crops"] == 2 and res["packages"][0]["failures"] == 0


def test_labelling_project_folders_chain_the_steps(tmp_path, monkeypatch, capsys):
    """--project puts each step in labelling/<group>/<project>/ and each step finds the one before."""
    from ceh_biomonitoring import cli
    from ceh_biomonitoring.settings import Settings
    from ceh_biomonitoring.validation.platforms import audio_clips
    real = Settings.load
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls, profile=None, **k: real(
        profile="local", overrides={"outputs_root": str(tmp_path / "out")}, settings_file=tmp_path / "none.yml")))
    res = tmp_path / "wood-1"
    res.mkdir()
    bird_det().drop(columns="results").to_parquet(res / "wood-1_detections.parquet")
    cli.main(["validate", "sample", "birds", str(res), "--for", "site-lists", "--project", "woods"])
    proj = tmp_path / "out" / "labelling" / "birds" / "woods"
    sel = list((proj / "1_sample").glob("*.csv"))
    assert len(sel) == 1 and (proj / "READ ME.txt").exists() and (proj / "3_answers" / "returned").is_dir()
    assert "validate prepare --project woods" in capsys.readouterr().out
    seen = {}
    monkeypatch.setattr(audio_clips, "prepare", lambda sel_, out, **k: seen.update(out=out, n=len(sel_)) or {})
    cli.main(["validate", "prepare", "--project", "woods"])
    assert seen["out"] == proj / "2_for_experts" / sel[0].stem and seen["n"] > 0
    with pytest.raises(SystemExit, match="No labelling project 'nope'"):
        cli.main(["validate", "prepare", "--project", "nope"])
    with pytest.raises(SystemExit, match="--project"):
        cli.main(["validate", "prepare"])
