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


def test_login_read_from_credentials_file(tmp_path, monkeypatch):
    import json, os
    f = tmp_path / "credentials.json"
    f.write_text(json.dumps({"UKCEH_username": "u", "UKCEH_password": "p", "UPLOAD_URL": "https://x/"}))
    if os.name == "posix":
        f.chmod(0o600)
    monkeypatch.setenv("CEHBIO_CREDENTIALS", str(f))
    s = Settings.load(profile="local", settings_file=tmp_path / "none.yml")
    assert upload.saved_login(s)["UKCEH_username"] == "u"
    monkeypatch.setenv("CEHBIO_CREDENTIALS", str(tmp_path / "missing.json"))
    assert upload.saved_login(s) == {}


def test_deployment_request_is_sent(monkeypatch, tmp_path, capsys):
    from ceh_biomonitoring import sites
    from ceh_biomonitoring.cli import build_parser
    sent = {}

    class Svc:
        def deployments(self):
            return [{"deployment_id": "dep000001", "country": "United Kingdom", "location_name": "Wood",
                     "camera_id": "CAM1", "status": "active"}]

        def _post(self, path, fields):
            sent.update(path=path, **fields)
            return {"deployment_id": "dep000002", "status": "pending"}

    monkeypatch.setattr(sites, "_service", lambda s: Svc())
    args = build_parser().parse_args(["deployments", "request", "--name", "A P", "--country", "United Kingdom",
                                      "--site", "Meadow", "--lat", "51.7", "--lon", "-1.2", "--device-type", "AudioMoth",
                                      "--device-id", "AM1", "--start", "2027-05-01", "--notes", "", "--yes"])
    s = Settings.load(profile="local", settings_file=tmp_path / "none.yml")
    sites.request(args, s)
    assert sent["path"] == "request-deployment/" and sent["location_name"] == "Meadow" and sent["lat"] == "51.7"
    assert "dep000002" in capsys.readouterr().out
    bad = build_parser().parse_args(["deployments", "request", "--name", "A", "--country", "United Kingdom",
                                     "--site", "M", "--lat", "95", "--lon", "0", "--device-type", "AudioMoth",
                                     "--device-id", "X", "--start", "2027-05-01", "--notes", "", "--yes"])
    with pytest.raises(SystemExit):
        sites.request(bad, s)
