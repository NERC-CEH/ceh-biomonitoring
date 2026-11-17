"""Engine tests. No object store, no models: a fake pipeline and fake downloads."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from ceh_biomonitoring import chunks, objectstore, pipelines, runner
from ceh_biomonitoring.cli import build_parser
from ceh_biomonitoring.pipelines.base import ChunkResult, Pipeline
from ceh_biomonitoring.settings import Settings

COUNTRY = {"country_name": "United Kingdom", "country_folder": "uk", "bucket_code": "gbr"}


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CEHBIO_CONFIG_DIR", str(tmp_path / "cfg"))
    return Settings.load(profile="local", overrides={"outputs_root": str(tmp_path / "out"),
                                                       "tmp_root": str(tmp_path / "tmp")},
                         settings_file=tmp_path / "none.yml")


class FakePipeline(Pipeline):
    name = "fake"
    extensions = (".wav",)
    key_field = "audio_keys"
    defaults = {"threshold": 0.5}

    def process(self, files, chunk, params, workdir):
        rows = [{"source_key": k, "filename": p.name, "score": 0.9} for k, p in files if "bird" in k]
        none = [{"source_key": k, "filename": p.name, "status": "no_detections"} for k, p in files if "bird" not in k]
        (workdir / "keep").mkdir(parents=True, exist_ok=True)
        (workdir / "keep" / "extra.txt").write_text("kept")
        return ChunkResult(pd.DataFrame(rows), none, [], {"model": "fake-1"})


def fake_download(s3, bucket, keys, dest):
    dest.mkdir(parents=True, exist_ok=True)
    for k in keys:
        if "broken" in k:
            yield k, None, "download: 404"
            continue
        p = dest / Path(k).name
        p.write_bytes(b"RIFF")
        yield k, p, None


def test_profiles_and_overrides(settings, tmp_path):
    assert settings.profile == "local"
    assert settings.outputs_root == tmp_path / "out"
    assert settings.get("slurm.enabled") is False
    jasmin = Settings.load(profile="jasmin", settings_file=tmp_path / "none.yml")
    assert jasmin.get("slurm.partition") == "standard" and jasmin.get("slurm.gpu.partition") == "orchid"
    assert "{user}" not in str(jasmin.outputs_root)


def test_chunks_round_trip(tmp_path):
    keys = [f"dep1/audible_recordings/f{i}.wav" for i in range(5)]
    paths = chunks.write_chunks(tmp_path, COUNTRY, "dep1", keys, 2, "audio_keys", "audible_recordings")
    assert [p.name for p in paths] == ["dep1_chunk_00001.json", "dep1_chunk_00002.json", "dep1_chunk_00003.json"]
    c = chunks.read_chunk(paths[-1])
    assert c["keys"] == keys[4:] and c["n_chunks"] == 3
    with pytest.raises(SystemExit):   # never silently overwrite existing chunks
        chunks.write_chunks(tmp_path, COUNTRY, "dep1", keys, 2, "audio_keys", "audible_recordings")


def test_old_chunk_files_still_read(tmp_path):
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"image_keys": ["a.jpg"], "chunk_index": 1}))
    assert chunks.read_chunk(p)["keys"] == ["a.jpg"]


def test_run_chunk_and_combine(settings, monkeypatch):
    monkeypatch.setattr(objectstore, "client", lambda s: object())
    monkeypatch.setattr(objectstore, "download", fake_download)
    p = FakePipeline()
    base = settings.pipeline_dir(p.name, "uk")
    keys = ["dep1/x/bird1.wav", "dep1/x/quiet.wav", "dep1/x/broken.wav", "dep1/x/bird2.wav"]
    paths = chunks.write_chunks(base, COUNTRY, "dep1", keys, 2, "audio_keys", "x")
    runner.save_run_params(settings, p, "uk", "dep1", p.params())
    for c in paths:
        s = runner.run_chunk(settings, p, c)
        assert s["status"] == "complete"
        assert s["provenance"]["models"] == {"model": "fake-1"}
    # second run skips finished chunks
    assert runner.run_chunk(settings, p, paths[0])["status"] == "complete"
    qa = runner.combine(settings, p, "uk", "dep1")
    assert qa["complete"] and qa["n_detections"] == 2 and qa["files_expected"] == 4
    assert qa["files_by_status"] == {"detections": 2, "no_detections": 1, "failed": 1}
    ddir = runner.deployment_dir(settings, p, "uk", "dep1")
    det = pd.read_parquet(ddir / "dep1_detections.parquet")
    assert set(det["deployment_id"]) == {"dep1"}
    assert (ddir / "chunks" / "dep1_chunk_00001_keep" / "extra.txt").exists()
    assert not any((settings.tmp_root).rglob("*.wav")), "temporary downloads are cleaned up"


def test_combine_reports_missing_chunks(settings, monkeypatch):
    monkeypatch.setattr(objectstore, "client", lambda s: object())
    monkeypatch.setattr(objectstore, "download", fake_download)
    p = FakePipeline()
    base = settings.pipeline_dir(p.name, "uk")
    paths = chunks.write_chunks(base, COUNTRY, "dep2", ["dep2/a/bird.wav", "dep2/a/b.wav"], 1, "audio_keys", "a")
    runner.save_run_params(settings, p, "uk", "dep2", p.params())
    runner.run_chunk(settings, p, paths[0])
    qa = runner.combine(settings, p, "uk", "dep2")
    assert not qa["complete"] and qa["chunks_missing"] == ["dep2_chunk_00002"]


def test_credentials_must_be_private(settings, tmp_path, monkeypatch):
    f = tmp_path / "creds.json"
    f.write_text(json.dumps({"AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "b"}))
    monkeypatch.setenv("CEHBIO_CREDENTIALS", str(f))
    if os.name == "posix":
        f.chmod(0o644)
        with pytest.raises(objectstore.CredentialsError):
            objectstore.load_credentials(settings)
        f.chmod(0o600)
    assert objectstore.load_credentials(settings)["AWS_ACCESS_KEY_ID"] == "a"


def test_registry_lists_without_importing_models():
    names = [r[0] for r in pipelines.available()]
    assert {"birds", "bats"} <= set(names)


def test_project_bucket_instead_of_country(settings, monkeypatch):
    from ceh_biomonitoring import countries
    from ceh_biomonitoring.cli import _where
    monkeypatch.setattr(countries.metadata, "entry_points", lambda group=None: [])   # as if no plug-in
    a = build_parser().parse_args(["status", "bats", "--bucket", "my-project-bucket", "--deployment", "dep000114"])
    c = _where(settings, a)
    assert c["bucket_code"] == "my-project-bucket" and a.country == "my-project-bucket"
    b = build_parser().parse_args(["status", "bats", "--country", "thailand", "--deployment", "dep1"])
    with pytest.raises(SystemExit, match="No country table"):   # country tables come from plug-ins
        _where(settings, b)
    with pytest.raises(SystemExit):
        _where(settings, build_parser().parse_args(["status", "bats", "--deployment", "dep1"]))


class MovingPipeline(FakePipeline):
    """Moves its inputs around, like the BatDetect and BirdNET pipelines do."""
    def process(self, files, chunk, params, workdir):
        import shutil
        dest = workdir / "audio"
        dest.mkdir(parents=True, exist_ok=True)
        moved = [(k, Path(shutil.move(str(p), dest / p.name))) for k, p in files]
        return super().process(moved, chunk, params, workdir)


def test_local_folder_never_touches_originals(settings, tmp_path):
    from ceh_biomonitoring.cli import list_local
    data = tmp_path / "card"
    (data / "night1").mkdir(parents=True)
    for n in ("bird_a.WAV", "quiet.wav", "notes.txt"):
        (data / "night1" / n).write_bytes(b"RIFF....")
    keys = list_local(data, (".wav",))
    assert [Path(k).name for k in keys] == ["bird_a.WAV", "quiet.wav"], "case-insensitive, other files ignored"
    p = MovingPipeline()
    local = {"country_name": "local", "country_folder": "local", "bucket_code": "local"}
    paths = chunks.write_chunks(settings.pipeline_dir(p.name, "local"), local, "site1", keys, 10, "audio_keys",
                                "local", {"source": "local", "device": "song-meter"})
    runner.save_run_params(settings, p, "local", "site1", p.params())
    s = runner.run_chunk(settings, p, paths[0])
    assert s["status"] == "complete" and s["n_detections"] == 1
    for n in ("bird_a.WAV", "quiet.wav", "notes.txt"):
        assert (data / "night1" / n).read_bytes() == b"RIFF....", f"original {n} must be untouched"


def test_devices_layering_and_timestamps():
    from ceh_biomonitoring import devices
    names = devices.available()
    assert {"audiomoth", "song-meter"} <= set(names)
    assert devices.parse_timestamp("SMA01234_20240705_043000.wav", devices.get("song-meter")) == "2024-07-05 04:30:00"
    assert devices.parse_timestamp("no_date_here.wav", devices.get("audiomoth")) is None
    r = devices.parse_filename("SMA01234_20240705_043000.wav", devices.get("song-meter"))
    assert r == {"file_datetime": "2024-07-05 04:30:00", "device_serial": "SMA01234"}
    # a pattern given on the command line wins, and MM (month) is not mm (minutes)
    assert devices.parse_timestamp("site3__13-05-2026__22h41m07s.wav", None, "*__DD-MM-YYYY__hhhmmmsss") == "2026-05-13 22:41:07"
    assert devices.parse_timestamp("123456789012345-20260806T025318.jpg", None, "SERIAL-YYYYMMDDThhmmss") == "2026-08-06 02:53:18"
    assert devices.parse_timestamp("rec 2026-11-13 19.45.00.wav", None, "rec YYYY-MM-DD hh.mm.ss") == "2026-11-13 19:45:00"
    # device params sit between pipeline defaults and the command line
    p = pipelines.get("bats")
    a = build_parser().parse_args(["run", "bats", "--country", "uk", "--deployment", "d", "--set", "detection_threshold=0.5"])
    from ceh_biomonitoring.cli import _params
    assert _params(p, a, {"params": {"bats": {"detection_threshold": 0.4}}})["detection_threshold"] == 0.5
    b = build_parser().parse_args(["run", "bats", "--country", "uk", "--deployment", "d"])
    assert _params(p, b, {"params": {"bats": {"detection_threshold": 0.4}}})["detection_threshold"] == 0.4


def test_device_must_match_pipeline():
    from ceh_biomonitoring import devices
    with pytest.raises(SystemExit):
        devices.check_compatible({"name": "camera", "media": "images"}, pipelines.get("bats"))


def test_cli_parses():
    a = build_parser().parse_args(["run", "bats", "--country", "uk", "--deployment", "dep1", "--set", "detection_threshold=0.5"])
    assert a.pipeline == "bats" and a.set == ["detection_threshold=0.5"]


def test_image_device_timestamps():
    from ceh_biomonitoring import devices
    ami, lep = devices.get("ami-trap"), devices.get("lepisense")
    assert devices.parse_timestamp("dep000076/snapshot_images/20240725204340-snapshot.jpg", ami) == "2024-07-25 20:43:40"
    r = devices.parse_filename("site-a/123456789012345-20260806T025318.jpg", lep)
    assert r == {"file_datetime": "2026-08-06 02:53:18", "device_serial": "123456789012345"}
    assert devices.parse_timestamp("ami-mini-20250428T210338_crop_1.jpg", lep) == "2025-04-28 21:03:38"
    assert lep["needs_mask"] is True and ami["needs_mask"] is False


def test_status_and_combine_default_to_local_results(settings):
    from ceh_biomonitoring.cli import _where, build_parser
    a = build_parser().parse_args(["status", "bats", "--deployment", "wood-1"])
    assert _where(settings, a, need_source=False)["bucket_code"] == "local" and a.country == "local"
    a = build_parser().parse_args(["run", "bats", "--deployment", "wood-1"])
    with pytest.raises(SystemExit):
        _where(settings, a)


def test_config_from_an_installed_package():
    from ceh_biomonitoring.cli import config_path
    p = config_path("pkg:ceh_biomonitoring/profiles/defaults.yml")
    assert p.exists() and p.name == "defaults.yml"
    assert config_path("~/x.yml").is_absolute()


def test_species_list_reading(tmp_path):
    from ceh_biomonitoring.species_lists import norm, read
    f = tmp_path / "l.csv"
    f.write_text("species,same_as\nEptesicus serotinus,Eptesicus serotinus\nCnephaeus serotinus,Eptesicus serotinus\n")
    names = read(f)
    assert norm("Eptesicus serotinus (Schreber, 1774)") in names and norm("Cnephaeus_serotinus_Serotine") in names
    bad = tmp_path / "b.csv"
    bad.write_text("name\nx\n")
    with pytest.raises(SystemExit):
        read(bad)


def test_monthly_species_lists(tmp_path):
    from datetime import datetime
    from ceh_biomonitoring.species_lists import SpeciesList, birdnet_week, file_date, file_month
    f = tmp_path / "m.csv"
    f.write_text("species,month\nHirundo rustica,5\nHirundo rustica,6\nErithacus rubecula,\nTurdus iliacus,1\n")
    sl = SpeciesList(f)
    assert sl.monthly and sl.allowed(5) == {"hirundo rustica", "erithacus rubecula"}
    assert sl.allowed(1) == {"turdus iliacus", "erithacus rubecula"}            # no Swallow in January
    assert sl.allowed(None) == {"hirundo rustica", "erithacus rubecula", "turdus iliacus"}
    assert file_month("x/20240705_043000.WAV") == 7 and file_month("site_2024-11-02_dawn.wav") == 11
    assert file_month("nodate.wav") is None
    assert file_date("SMA01234_20240705_043000.wav", {"device": "song-meter"}) == datetime(2024, 7, 5, 4, 30)
    assert birdnet_week(datetime(2024, 1, 1)) == 1 and birdnet_week(datetime(2024, 12, 31)) == 48
    assert birdnet_week(None) == -1


def test_unlikely_months_are_kept_and_flagged(tmp_path):
    import pandas as pd
    from ceh_biomonitoring.species_lists import SpeciesList, flag_unlikely, keep_unlikely
    f = tmp_path / "m.csv"
    f.write_text("species,month,likelihood\nHirundo rustica,6,expected\nHirundo rustica,2,unlikely\n"
                 "Erithacus rubecula,2,expected\n")
    sl = SpeciesList(f)
    assert "hirundo rustica" in sl.allowed(2)                       # an early Swallow is still reported
    assert sl.allowed(2, unlikely=False) == {"erithacus rubecula"}
    det = pd.DataFrame({"source_key": ["a/20260210_0500.wav", "a/20260210_0500.wav", "a/20260610_0500.wav"],
                        "species_name": ["Hirundo rustica", "Erithacus rubecula", "Hirundo rustica"]})
    assert list(flag_unlikely(det, sl)["unlikely_this_month"]) == [True, False, False]
    assert keep_unlikely({}) and not keep_unlikely({"species_list_unlikely": "remove"})


def test_example_files_match_the_manifest():
    """Every example in the repository is there and unchanged; every file has a licence and a credit."""
    import hashlib
    from ceh_biomonitoring import examples
    m = examples.manifest()
    assert {"birds", "bats", "images"} <= set(m)
    for pipeline, ex in m.items():
        for f in ex["files"]:
            assert f["licence"] and f["credit"] and f["sha256"], f["name"]
            if f["in_repo"]:
                local = examples.REPO_EXAMPLES / pipeline / f["name"]
                assert hashlib.sha256(local.read_bytes()).hexdigest() == f["sha256"], f["name"]


def test_example_check():
    import pandas as pd
    from ceh_biomonitoring.examples import check
    det = pd.DataFrame({"species_name": ["Erithacus rubecula", "Parus major"]})
    assert check("birds", det, {"min_detections": 1, "any_species": ["Erithacus rubecula"]})[0]
    assert not check("birds", det, {"any_species": ["Turdus merula"]})[0]
    assert not check("bats", det.iloc[:0], {"min_detections": 1})[0]
