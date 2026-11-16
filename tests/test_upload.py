"""Upload tests against a fake upload service (never contacts the real one)."""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from ceh_biomonitoring import upload
from ceh_biomonitoring.settings import Settings

DEPLOYMENTS = [
    {"country": "Thailand", "country_code": "THA", "location_name": "Doi Suthep", "camera_id": "cam01",
     "deployment_id": "dep000078", "status": "active"},
    {"country": "Thailand", "country_code": "THA", "location_name": "Old site", "camera_id": "cam02",
     "deployment_id": "dep000070", "status": "inactive"},
]


class FakeService:
    calls: list = []
    stored: set = set()
    fail_once: set = set()

    def __init__(self, url, username, password):
        self.password = password

    def deployments(self):
        return DEPLOYMENTS

    def exists(self, base, filename):
        return filename in FakeService.stored

    def upload_link(self, base, filename, file_type):
        FakeService.calls.append((base["country"], base["deployment"], base["data_type"], filename))
        return f"https://example.invalid/put/{filename}?X-Amz-Signature=SECRET"

    def put(self, link, path, file_type):
        if path.name in FakeService.fail_once:
            FakeService.fail_once.discard(path.name)
            raise RuntimeError("network hiccup")
        FakeService.stored.add(path.name)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    FakeService.calls, FakeService.stored, FakeService.fail_once = [], set(), {"IMG_0002.JPG"}
    monkeypatch.setattr(upload, "UploadService", FakeService)
    monkeypatch.setenv("CEHBIO_UPLOAD_USER", "partner")
    monkeypatch.setenv("CEHBIO_UPLOAD_PASSWORD", "hunter2")
    card = tmp_path / "SD"
    (card / "DCIM").mkdir(parents=True)
    for n in ("IMG_0001.jpg", "IMG_0002.JPG", "IMG_0003.jpeg"):
        (card / "DCIM" / n).write_bytes(b"x" * 20_000)
    (card / "DCIM" / "tiny.jpg").write_bytes(b"x")                 # under 10 KB: skipped
    (card / "$RECYCLE.BIN").mkdir()
    (card / "$RECYCLE.BIN" / "old.jpg").write_bytes(b"x" * 20_000)  # recycle bin: skipped
    s = Settings.load(profile="local", overrides={"outputs_root": str(tmp_path / "out")}, settings_file=tmp_path / "x.yml")
    args = argparse.Namespace(folder=str(card), country="thailand", deployment="Doi Suthep", data_type="snapshot_images",
                              name="Jo Bloggs", test=False, yes=True, skip_remote_check=False, parallel=2,
                              log_dir=str(tmp_path / "logs"))
    return s, args, tmp_path


def test_upload_then_resume(setup):
    s, args, tmp = setup
    upload.run(args, s)
    assert {c[:3] for c in FakeService.calls} == {("tha", "dep000078", "snapshot_images")}
    assert FakeService.stored == {"IMG_0001.jpg", "IMG_0003.jpeg"}       # 0002 failed once
    logtext = next((tmp / "logs").glob("*.csv")).read_text()
    assert "hunter2" not in logtext and "SECRET" not in logtext, "no password or upload link in the log"
    FakeService.calls = []
    upload.run(args, s)                                                   # second run: resume
    assert [c[3] for c in FakeService.calls] == ["IMG_0002.JPG"], "only the failed file is retried"
    assert FakeService.stored == {"IMG_0001.jpg", "IMG_0002.JPG", "IMG_0003.jpeg"}


def test_inactive_and_unknown_deployments_rejected(setup):
    s, args, _ = setup
    args.deployment = "Old site"
    with pytest.raises(SystemExit):
        upload.run(args, s)


def test_find_files_audio(tmp_path):
    (tmp_path / "a.WAV").write_bytes(b"x" * 20_000)
    (tmp_path / "b.jpg").write_bytes(b"x" * 20_000)
    assert [p.name for p in upload.find_files(tmp_path, "audible_recordings")] == ["a.WAV"]


def test_dragged_folder_quotes_are_removed():
    from ceh_biomonitoring.upload import clean_path
    assert str(clean_path('  "C:/My Data/site 1"  ')) == str(Path("C:/My Data/site 1"))
    assert str(clean_path("'/data/site'")) == str(Path("/data/site"))
