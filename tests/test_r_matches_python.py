"""The R package makes the report tables on its own (r/R/report_data.R). This checks it makes the SAME
tables as Python (reporting/data.py) from the same results: images with tracks, untracked crops and other
insects; bird events; bat passes; a local clock across the change of the clocks; deployment dates; the moon.

Needs R with the cehbio package installed (R CMD INSTALL r); skipped otherwise.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ceh_biomonitoring import chunks, layout
from ceh_biomonitoring.settings import Settings


def _rscript() -> str | None:
    found = shutil.which("Rscript")
    if found:
        return found
    for base in sorted(Path("C:/Program Files/R").glob("R-*/bin/Rscript.exe"), reverse=True):
        return str(base)
    return None


RSCRIPT = _rscript()


def _r_has_cehbio() -> bool:
    if not RSCRIPT:
        return False
    r = subprocess.run([RSCRIPT, "-e", "cat(requireNamespace('cehbio', quietly=TRUE) && "
                        "exists('cehbio_report_data', asNamespace('cehbio')))"], capture_output=True, text=True)
    return r.stdout.strip().endswith("TRUE")


pytestmark = pytest.mark.skipif(not _r_has_cehbio(), reason="needs R with the cehbio package")


def _images(root: Path, dep: str, start: datetime, nights: int, seed: int):
    rng = np.random.default_rng(seed)
    rp = layout.new_paths(root, "images", "farm", dep)
    chunks.write_json(rp.manifest, {"n_chunks": 1})
    files, rows = [], []
    species = ["Noctua pronuba", "Biston betularia", "Agrotis exclamationis", "Xestia c-nigrum"]
    for n in range(nights):
        t = start + timedelta(days=n)
        for k in range(30):
            when = t + timedelta(minutes=17 * k)
            name = f"/cards/{dep}/01-{when:%Y%m%d%H%M%S}-snapshot.jpg"
            status = rng.choice(["detections", "no_detections", "failed"], p=[0.6, 0.35, 0.05])
            files.append({"source_key": name, "filename": name.split("/")[-1], "status": status})
            if status != "detections":
                continue
            for b in range(int(rng.integers(1, 4))):
                x0 = float(rng.integers(0, 900)) + (0.25 if b == 2 else 0.0)
                kind = rng.choice(["moth", "nonmoth", "moth_untracked"], p=[0.6, 0.2, 0.2])
                rows.append({"image_path": name, "source_key": name, "image_datetime": f"{when:%Y-%m-%d %H:%M:%S}",
                             "deployment_id": dep, "deployment_name": "", "x_min": x0, "y_min": 5.0, "x_max": x0 + 40.5,
                             "y_max": 60.0, "class_name": "moth" if kind != "nonmoth" else "nonmoth",
                             "order_name": "Lepidoptera Macros" if kind != "nonmoth" else rng.choice(["Diptera Brachycera", "Trichoptera"]),
                             "order_confidence": round(float(rng.uniform(0.3, 1)), 4),
                             "regional_species_rank_1_name": rng.choice(species) if kind != "nonmoth" else None,
                             "regional_species_rank_1_confidence": round(float(rng.uniform(0.1, 1)), 4) if kind != "nonmoth" else None,
                             "track_id": f"Track_{n:02d}{int(rng.integers(0, 12)):04d}" if kind != "moth_untracked" else None,
                             "latitude": None, "longitude": None})
    pd.DataFrame(files).to_csv(rp.root / f"{dep}_files.csv", index=False)
    det = pd.DataFrame(rows)
    det.to_parquet(rp.root / f"{dep}_analysis_ready.parquet", index=False)
    det.to_parquet(rp.root / f"{dep}_detections.parquet", index=False)
    chunks.write_json(rp.chunks / f"{dep}_chunk_00001_summary.json",
                      {"provenance": {"models": {"detector": {"model": "insect-detector-flatbug-m-v2", "by": "flat-bug",
                                                              "licence": "MIT"}}}})


def _audio(root: Path, pipeline: str, dep: str, seed: int):
    rng = np.random.default_rng(seed)
    rp = layout.new_paths(root, pipeline, "woods", dep)
    chunks.write_json(rp.manifest, {"n_chunks": 1})
    files, rows = [], []
    names = ["Turdus merula", "Erithacus rubecula", "Strix aluco"] if pipeline == "birds" else \
            ["Pipistrellus pipistrellus", "Nyctalus noctula"]
    for d in range(3):
        for h in (20, 22, 4):
            day = datetime(2026, 5, 10 + d) + timedelta(hours=h)
            key = f"/rec/{dep}/{day:%Y%m%d_%H%M%S}.WAV"
            files.append({"source_key": key, "filename": key.split("/")[-1], "status": "detections"})
            t = 0.0
            for _ in range(int(rng.integers(3, 12))):
                t += float(rng.choice([1.0, 3.0, 0.5, 90.0, 0.2]))
                row = {"source_key": key, "filename": key.split("/")[-1], "deployment_id": dep, "start_time": round(t, 3),
                       "end_time": round(t + (3.0 if pipeline == "birds" else 0.01), 3), "species_name": rng.choice(names),
                       "common_name": None}
                row["confidence" if pipeline == "birds" else "class_probability"] = round(float(rng.uniform(0.1, 1)), 4)
                rows.append(row)
    pd.DataFrame(files).to_csv(rp.root / f"{dep}_files.csv", index=False)
    pd.DataFrame(rows).to_parquet(rp.root / f"{dep}_detections.parquet", index=False)


def _compare(a: Path, b: Path, name: str, keys: list[str]):
    pa, pr = pd.read_csv(a / f"{name}.csv"), pd.read_csv(b / f"{name}.csv")
    assert list(pa.columns) == list(pr.columns), f"{name}: columns differ\n{list(pa.columns)}\n{list(pr.columns)}"
    assert len(pa) == len(pr), f"{name}: {len(pa)} rows in Python, {len(pr)} in R"
    if not len(pa):
        return
    pa = pa.sort_values(keys, kind="stable").reset_index(drop=True)
    pr = pr.sort_values(keys, kind="stable").reset_index(drop=True)
    for c in pa.columns:
        x, y = pa[c], pr[c]
        if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y):
            assert np.allclose(x.astype(float), y.astype(float), atol=1e-6, equal_nan=True), f"{name}.{c} differs"
        else:
            xs = x.astype(object).where(x.notna(), "").astype(str).str.replace(r"\.0$", "", regex=True)
            ys = y.astype(object).where(y.notna(), "").astype(str).str.replace(r"\.0$", "", regex=True)
            assert (xs == ys).all(), f"{name}.{c} differs:\n{pd.DataFrame({'py': xs, 'r': ys})[xs != ys].head()}"


def _both(tmp_path, pipeline, project, sites_rows, weather="none"):
    from ceh_biomonitoring.reporting import data as D
    sites = tmp_path / "sites.csv"
    pd.DataFrame(sites_rows).to_csv(sites, index=False)
    shutil.copytree(tmp_path / "py", tmp_path / "r")
    s = Settings.load(profile="local", overrides={"outputs_root": str(tmp_path / "py"), "tmp_root": str(tmp_path / "tmp")},
                      settings_file=tmp_path / "none.yml")
    D.build(s, pipeline, project, sites=str(sites), weather=weather)
    code = (f'options(cehbio.results = "{(tmp_path / "r").as_posix()}"); '
            f'cehbio::cehbio_report_data("{pipeline}", "{project}", sites = "{sites.as_posix()}", weather = "{weather}")')
    r = subprocess.run([RSCRIPT, "-e", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-3000:]
    return (tmp_path / "py" / pipeline / project / "report" / "data", tmp_path / "r" / pipeline / project / "report" / "data")


def test_images_tables_match(tmp_path, monkeypatch):
    monkeypatch.setenv("CEHBIO_CONFIG_DIR", str(tmp_path / "cfg"))
    root = tmp_path / "py"
    _images(root, "trap-a", datetime(2026, 10, 22, 19, 0), 6, 1)       # local clock across the clocks going back
    _images(root, "trap-b", datetime(2026, 5, 9, 21, 0), 4, 2)
    _images(root, "trap-c", datetime(2026, 3, 25, 18, 40), 7, 5)       # no clock given: the clock check decides
    py, r = _both(tmp_path, "images", "farm", [
        {"deployment": "trap-c", "latitude": 51.6, "longitude": -1.12, "timezone": "Europe/London"},
        {"deployment": "trap-a", "latitude": 51.6, "longitude": -1.12, "timezone": "Europe/London", "clock": "local",
         "site_name": "North field"},
        {"deployment": "trap-b", "latitude": 50.1, "longitude": -5.0, "timezone": "Europe/London", "clock": "UTC",
         "start": "2026-05-10", "site_name": "Cliff"}])
    _compare(py, r, "deployments", ["deployment_id"])
    _compare(py, r, "nights", ["deployment_id", "night"])
    _compare(py, r, "individuals", ["deployment_id", "unit_id", "taxon"])
    _compare(py, r, "species", ["deployment_id", "kind", "taxon"])
    tp, tr = (json.loads((x / "text.json").read_text(encoding="utf-8")) for x in (py, r))
    assert tp["deployments"] == tr["deployments"] and tp["project_summary"] == tr["project_summary"]
    for k in ("how", "caveat", "night", "unit", "weather", "moon", "models", "citations", "notes"):
        assert tp["methods"][k] == tr["methods"][k], k
    assert tp["labels"] == tr["labels"] and tp["style"] == tr["style"]
    ep, er = (pd.read_csv(x / "entoinsights" / "trap-a_combined_results.csv") for x in (py, r))
    assert len(ep) == len(er) and set(ep.columns) == set(er.columns)


@pytest.mark.parametrize("pipeline", ["birds", "bats"])
def test_audio_tables_match(tmp_path, monkeypatch, pipeline):
    monkeypatch.setenv("CEHBIO_CONFIG_DIR", str(tmp_path / "cfg"))
    _audio(tmp_path / "py", pipeline, "wood-1", 3)
    _audio(tmp_path / "py", pipeline, "wood-2", 4)
    py, r = _both(tmp_path, pipeline, "woods", [{"deployment": "wood-1", "latitude": 51.6, "longitude": -1.12},
                                                 {"deployment": "wood-2", "latitude": 52.0, "longitude": 0.1}])
    for name, keys in (("deployments", ["deployment_id"]), ("nights", ["deployment_id", "night"]),
                       ("individuals", ["deployment_id", "unit_id"]), ("species", ["deployment_id", "taxon"])):
        _compare(py, r, name, keys)
    tp, tr = (json.loads((x / "text.json").read_text(encoding="utf-8")) for x in (py, r))
    assert tp["deployments"] == tr["deployments"] and tp["methods"]["notes"] == tr["methods"]["notes"]


def test_weather_matches(tmp_path, monkeypatch):
    """Live Open-Meteo weather, summarised the same way (skipped when offline)."""
    import urllib.error
    import urllib.request
    try:
        urllib.request.urlopen("https://historical-forecast-api.open-meteo.com", timeout=10)
    except urllib.error.HTTPError:
        pass                                      # it answered: we're online
    except Exception:  # noqa: BLE001
        pytest.skip("no internet")
    monkeypatch.setenv("CEHBIO_CONFIG_DIR", str(tmp_path / "cfg"))
    _images(tmp_path / "py", "trap-w", datetime(2025, 6, 2, 21, 30), 3, 7)
    py, r = _both(tmp_path, "images", "farm", [{"deployment": "trap-w", "latitude": 51.6, "longitude": -1.12,
                                                 "timezone": "Europe/London", "clock": "local"}], weather="open-meteo")
    n = pd.read_csv(py / "nights.csv")
    assert n["temperature_mean_c"].notna().all()
    _compare(py, r, "nights", ["deployment_id", "night"])
