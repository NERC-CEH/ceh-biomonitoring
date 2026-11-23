"""Report data: tables from a results folder, the moon, the weather summary and the EntoInsights copy."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from ceh_biomonitoring import chunks, layout
from ceh_biomonitoring.settings import Settings


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CEHBIO_CONFIG_DIR", str(tmp_path / "cfg"))
    return Settings.load(profile="local", overrides={"outputs_root": str(tmp_path / "out"),
                                                       "tmp_root": str(tmp_path / "tmp"),
                                                       "models": {"cache_dir": str(tmp_path / "cache")}},
                         settings_file=tmp_path / "none.yml")


def _images_run(settings, dep="trap-1"):
    rp = layout.new_paths(settings.outputs_root, "images", "farm", dep)
    chunks.write_json(rp.manifest, {"n_chunks": 1, "total_files": 7})
    photos = [f"/cards/{dep}/868531063311026-20260511T{h}.jpg" for h in ("213000", "220000", "230000")] + \
             [f"/cards/{dep}/868531063311026-20260512T{h}.jpg" for h in ("003000", "013000")] + \
             [f"/cards/{dep}/868531063311026-20260512T{h}.jpg" for h in ("214500", "224500")]
    files = pd.DataFrame({"source_key": photos, "filename": [p.split("/")[-1] for p in photos],
                          "status": ["detections", "detections", "no_detections", "detections", "failed",
                                     "detections", "no_detections"]})
    files.to_csv(rp.root / f"{dep}_files.csv", index=False)
    rows = []
    for p, track, sp, conf in ((photos[0], "T1", "Noctua pronuba", 0.9), (photos[1], "T1", "Noctua pronuba", 0.8),
                               (photos[3], "T2", "Biston betularia", 0.7), (photos[5], "T3", "Noctua pronuba", 0.95)):
        t = datetime.strptime(p.split("-")[-1][:15], "%Y%m%dT%H%M%S")
        rows.append({"image_path": p, "source_key": p, "image_datetime": t.strftime("%Y-%m-%d %H:%M:%S"),
                     "deployment_id": dep, "deployment_name": "", "x_min": 10, "y_min": 10, "x_max": 60, "y_max": 60,
                     "crop_status": "crop_1", "class_name": "moth", "class_confidence": 0.99,
                     "order_name": "Lepidoptera Macros", "order_confidence": 0.9,
                     "regional_species_rank_1_name": sp, "regional_species_rank_1_confidence": conf,
                     "track_id": track, "latitude": None, "longitude": None})
    rows.append({**rows[0], "track_id": "T4", "class_name": "nonmoth", "order_name": "Diptera Brachycera",
                 "regional_species_rank_1_name": None, "regional_species_rank_1_confidence": None,
                 "x_min": 200, "x_max": 240})
    det = pd.DataFrame(rows)
    det.to_parquet(rp.root / f"{dep}_analysis_ready.parquet", index=False)
    det.to_parquet(rp.root / f"{dep}_detections.parquet", index=False)
    chunks.write_json(rp.chunks / f"{dep}_chunk_00001_summary.json",
                      {"status": "complete", "provenance": {"models": {"detector": "flat_bug_M_v2"}}})
    return rp


def test_moon_matches_known_phases():
    from ceh_biomonitoring.reporting import sky
    utc = timezone.utc
    assert sky.moon_illumination(datetime(2024, 4, 8, 18, 21, tzinfo=utc)) < 0.02        # eclipse new moon
    assert sky.moon_illumination(datetime(2024, 4, 23, 23, 49, tzinfo=utc)) > 0.98       # full moon
    assert 0.45 < sky.moon_illumination(datetime(2024, 4, 15, 19, 13, tzinfo=utc)) < 0.55
    assert sky.moon_altitude(datetime(2024, 4, 23, 23, 49, tzinfo=utc), 51.5, -0.1) > 15   # full moon at midnight
    assert sky.moon_altitude(datetime(2024, 4, 23, 12, 0, tzinfo=utc), 51.5, -0.1) < 0


def test_weather_is_summarised_over_the_working_hours_only():
    from ceh_biomonitoring.reporting import weather as W
    hours = pd.DataFrame({"time_utc": pd.date_range("2026-05-11 12:00", periods=24, freq="h"),
                          "temperature_c": range(24), "precipitation_mm": [0.0] * 10 + [1.0] + [0.0] * 13,
                          "wind_speed_ms": 2.0, "cloud_cover_pct": 50.0, "relative_humidity_pct": 80.0})
    w = W.over(hours, pd.Timestamp("2026-05-11 20:30"), pd.Timestamp("2026-05-12 01:10"))
    assert w["temperature_at_start_c"] == 8 and w["temperature_min_c"] == 8 and w["temperature_mean_c"] == 11.0   # hours 20:00 to 02:00
    assert w["precipitation_total_mm"] == 1.0 and w["rain_hours"] == 1


def test_report_data_tables(settings, monkeypatch, tmp_path):
    from ceh_biomonitoring.reporting import data as D
    from ceh_biomonitoring.reporting import weather as W
    _images_run(settings)
    seen = {}

    def fake_hourly(s, source, lat, lon, start, end):
        seen.update(source=source, start=start)
        return pd.DataFrame({"time_utc": pd.date_range("2026-05-11", periods=72, freq="h"), "temperature_c": 10.0,
                             "precipitation_mm": 0.0, "wind_speed_ms": 1.0, "cloud_cover_pct": 20.0,
                             "relative_humidity_pct": 90.0})
    monkeypatch.setattr(W, "hourly", fake_hourly)
    sites = tmp_path / "sites.csv"
    pd.DataFrame({"deployment": ["trap-1"], "latitude": [51.60], "longitude": [-1.12],
                  "timezone": ["Europe/London"], "clock": ["local"], "country": ["England"]}).to_csv(sites, index=False)
    r = D.build(settings, "images", "farm", sites=str(sites), use="noncommercial")
    out = settings.outputs_root / "images" / "farm" / "report" / "data"
    assert r["out"] == str(out) and r["deployments"] == 1
    nights = pd.read_parquet(out / "nights.parquet")
    assert list(nights["night"]) == ["2026-05-11", "2026-05-12"]
    n1 = nights.iloc[0]
    assert n1["files"] == 5 and n1["files_failed"] == 1 and n1["hours_worked"] == 4.0
    assert str(n1["first_utc"]) == "2026-05-11 20:30:00"                     # 21:30 BST on a local clock
    assert n1["individuals"] == 3 and "moon_illumination" in nights and n1["temperature_mean_c"] == 10.0
    ind = pd.read_parquet(out / "individuals.parquet")
    assert len(ind) == 4 and set(ind["kind"]) == {"moth", "other insect"}    # T1 is one individual, not two
    sp = pd.read_parquet(out / "species.parquet").set_index("taxon")
    assert sp.loc["Noctua pronuba", "individuals"] == 2 and sp.loc["Noctua pronuba", "nights"] == 2
    assert pd.read_parquet(out / "deployments.parquet")["country"].iloc[0] == "England"   # extra columns kept
    about = json.loads((out / "about.json").read_text())
    assert about["weather"]["source"] == "open-meteo" and about["weather"]["commercial"] is False
    assert about["models"]["models"]["detector"] == "flat_bug_M_v2"
    ento = pd.read_csv(out / "entoinsights" / "trap-1_combined_results.csv")
    for c in ("image_path", "deployment_name", "latitude", "longitude", "top_1_species", "top_1_confidence",
              "image_datetime", "recording_session", "class_name", "order_name", "crop_status"):
        assert c in ento.columns
    assert ento["latitude"].iloc[0] == 51.60 and ento["deployment_name"].iloc[0] == "trap-1"
    assert ento["deployment_id"].notna().all()       # else EntoInsights counts nights twice
    assert (out / "nights.csv").exists()


def test_report_data_without_a_place_still_works_and_says_why(settings):
    from ceh_biomonitoring.reporting import data as D
    _images_run(settings)
    r = D.build(settings, "images", "farm", weather="open-meteo", use="noncommercial")
    assert any("no latitude and longitude" in n for n in r["notes"])
    assert any("taken as UTC" in n for n in r["notes"])


def test_birdnet_results_get_an_entoinsights_copy(tmp_path):
    from ceh_biomonitoring.reporting.entoinsights import export
    root = tmp_path / "wood-1"
    root.mkdir()
    pd.DataFrame({"source_key": ["/r/20260501_050000.WAV"], "filename": ["20260501_050000.WAV"],
                  "start_time": [3.0], "end_time": [6.0], "species_name": ["Turdus merula"],
                  "common_name": ["Eurasian Blackbird"], "confidence": [0.8]}).to_parquet(root / "wood-1_detections.parquet")
    p = export(root, "wood-1", "birds", {"latitude": 51.6, "longitude": -1.1}, tmp_path / "ento")
    b = pd.read_csv(p)
    assert list(b.columns[:6]) == ["path", "filename", "site", "lat", "lon", "scientific_name"]
    pd.DataFrame({"source_key": ["x"], "filename": ["x"], "start_time": [0.0], "end_time": [5.0],
                  "species_name": ["Turdus merula"], "logit": [3.0]}).to_parquet(root / "wood-1_detections.parquet")
    assert export(root, "wood-1", "birds", {}, tmp_path / "ento") is None        # Perch: EntoInsights can't read it


def test_deployment_dates_leave_set_up_tests_out(settings, tmp_path):
    from ceh_biomonitoring.reporting import data as D
    _images_run(settings)
    sites = tmp_path / "sites.csv"
    pd.DataFrame({"deployment": ["trap-1"], "start": ["2026-05-12"]}).to_csv(sites, index=False)
    r = D.build(settings, "images", "farm", sites=str(sites), weather="none", use="noncommercial")
    out = settings.outputs_root / "images" / "farm" / "report" / "data"
    nights = pd.read_parquet(out / "nights.parquet")
    assert list(nights["in_deployment"]) == [False, True] and len(nights) == 2      # kept, but marked
    dep = pd.read_parquet(out / "deployments.parquet").iloc[0]
    assert dep["nights_worked"] == 1 and dep["files"] == 2 and dep["files_outside_deployment"] == 5
    ind = pd.read_parquet(out / "individuals.parquet")
    assert set(ind["night"]) == {"2026-05-12"} and any("outside the deployment dates" in n for n in r["notes"])
    assert ind.loc[ind["kind"] == "other insect", "score_type"].tolist() in ([], ["order_confidence"])


def test_html_reports_are_made_and_never_name_the_user_or_machine(settings):
    pytest.importorskip("matplotlib")
    from ceh_biomonitoring.reporting import html
    rp = _images_run(settings)
    _images_run(settings, dep="trap-2")
    chunks.write_json(rp.chunks / "trap-1_chunk_00001_summary.json",
                      {"status": "complete", "provenance": {"user": "secret-user", "host": "secret-host",
                                                            "models": {"detector": {"model": "insect-detector-flatbug-m-v2",
                                                                                    "by": "flat-bug", "licence": "MIT"},
                                                                       "perch_model": "/home/users/secret-user/perch_v2_cpu/1"}}})
    files = html.make(settings, "images", "farm", weather="none", use="noncommercial")
    assert sorted(f.name for f in files) == ["farm_project.html", "trap-1.html", "trap-2.html"]
    page = (files[0].parent / "trap-1.html").read_text(encoding="utf-8")
    assert "Noctua pronuba" in page and "insect-detector-flatbug-m-v2" in page and "data:image/png;base64" in page
    for secret in ("secret-user", "secret-host"):
        assert secret not in page
    t = json.loads((files[0].parent / "data" / "text.json").read_text())
    assert t["style"]["main"] == "#133b64" and t["deployments"]["trap-1"][0].startswith("The light trap worked")


def test_word_reports_have_the_same_words_and_charts(settings):
    pytest.importorskip("matplotlib")
    from ceh_biomonitoring.reporting import document, html
    try:
        document.quarto()
    except SystemExit:
        pytest.skip("Quarto isn't installed")
    import zipfile
    _images_run(settings)
    files = html.make(settings, "images", "farm", weather="none", formats=["docx"], use="noncommercial")
    assert [f.name for f in files] == ["trap-1.docx"]
    z = zipfile.ZipFile(files[0])
    text = z.read("word/document.xml").decode("utf-8")
    assert "The light trap worked on 2 nights" in text and "Noctua pronuba" in text
    assert sum(n.startswith("word/media/") for n in z.namelist()) >= 3
    assert (files[0].parent / "trap-1_species.csv").exists()


def test_commercial_or_not_must_be_said_and_is_remembered(settings, tmp_path, monkeypatch):
    from ceh_biomonitoring.reporting import data as D
    from ceh_biomonitoring.reporting import use as U
    _images_run(settings)
    monkeypatch.setattr(U, "_interactive", lambda: False)
    with pytest.raises(SystemExit) as e:                         # nobody said, nobody to ask
        D.build(settings, "images", "farm", weather="none")
    assert "--use commercial" in str(e.value)
    D.build(settings, "images", "farm", weather="none", use="commercial")
    out = settings.outputs_root / "images" / "farm" / "report" / "data"
    about = json.loads((out / "about.json").read_text())
    assert about["use"] == "commercial"
    assert any("moth species models" in n and "non-commercial" in n for n in about["notes"])
    D.build(settings, "images", "farm", weather="none")         # remembered: not asked again
    assert json.loads((out / "about.json").read_text())["use"] == "commercial"


def test_commercial_weather_is_era5_land_and_needs_a_key(settings, tmp_path, monkeypatch):
    from ceh_biomonitoring.reporting import use as U
    monkeypatch.setattr(U, "_interactive", lambda: False)
    monkeypatch.setenv("CEHBIO_CREDENTIALS", str(tmp_path / "nokey.json"))
    monkeypatch.delenv("CDSAPI_KEY", raising=False)
    assert U.weather_for("noncommercial", None) == "open-meteo"
    with pytest.raises(SystemExit) as e:
        U.weather_for("commercial", "open-meteo")
    assert "non-commercial use only" in str(e.value)
    with pytest.raises(SystemExit) as e:
        U.weather_for("commercial", None)
    assert "weather-setup" in str(e.value) and "--weather none" in str(e.value)
    monkeypatch.setenv("CDSAPI_KEY", "0123abcd-4567-89ab-cdef-0123456789ab")
    assert U.weather_for("commercial", None) == "era5-land"
    assert U.licence_notes("noncommercial", ["BirdNET Analyzer 2.4"], "birds") == []
    assert len(U.licence_notes("commercial", ["BirdNET Analyzer 2.4"], "birds")) == 1
    assert U.licence_notes("commercial", ["Perch, by Google DeepMind (licence: Apache 2.0)"], "birds") == []
