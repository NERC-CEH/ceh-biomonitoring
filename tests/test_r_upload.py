"""Uploading from R (r/R/upload.R) against a stand-in upload service on this computer (never the real one):
the right files go to the right deployment, failures are retried, nothing is sent twice, the log never
holds the password or an upload link, and an upload started in R can be finished by the Python tool.

Needs R with the cehbio package installed; skipped otherwise.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from test_r_matches_python import RSCRIPT, _r_has_cehbio

pytestmark = pytest.mark.skipif(not _r_has_cehbio(), reason="needs R with the cehbio package")

DEPLOYMENTS = [{"country": "Thailand", "country_code": "THA", "location_name": "Doi Suthep", "camera_id": "cam01",
                "deployment_id": "dep000078", "status": "active"}]


class Fake(BaseHTTPRequestHandler):
    stored: dict = {}
    fail_once: set = set()
    seen_fields: list = []

    def log_message(self, *a):
        pass

    def _reply(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        f = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode(), keep_blank_values=True).items()}
        if f.get("username") != "partner" or f.get("password") != "hunter2":
            return self._reply(401, {"detail": "no"})
        Fake.seen_fields.append(f)
        if self.path.endswith("get-deployments/"):
            return self._reply(200, DEPLOYMENTS)
        if self.path.endswith("check-file-exist/"):
            return self._reply(200, {"exists": f["filename"] in Fake.stored})
        if self.path.endswith("request-deployment/"):
            return self._reply(200, {"deployment_id": "dep000999", "status": "pending"})
        if self.path.endswith("generate-presigned-url/"):
            port = self.server.server_address[1]
            return self._reply(200, {"url": f"http://127.0.0.1:{port}/put/{f['filename']}?X-Amz-Signature=SECRET"})
        self._reply(404, {})

    def do_PUT(self):
        n = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(n)
        name = urllib.parse.unquote(self.path.split("/put/")[1].split("?")[0])
        if name in Fake.fail_once:
            Fake.fail_once.discard(name)
            return self._reply(500, {"detail": "hiccup"})
        Fake.stored[name] = (len(data), self.headers.get("Content-Type"))
        self._reply(200, {})


@pytest.fixture
def service(tmp_path, monkeypatch):
    Fake.stored, Fake.fail_once, Fake.seen_fields = {}, {"IMG_0002.JPG"}, []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    creds = tmp_path / "credentials.json"
    creds.write_text(json.dumps({"UPLOAD_URL": f"http://127.0.0.1:{srv.server_address[1]}/"}))
    monkeypatch.setenv("CEHBIO_CREDENTIALS", str(creds))
    monkeypatch.setenv("CEHBIO_UPLOAD_USER", "partner")
    monkeypatch.setenv("CEHBIO_UPLOAD_PASSWORD", "hunter2")
    card = tmp_path / "SD"
    (card / "DCIM").mkdir(parents=True)
    for n in ("IMG_0001.jpg", "IMG_0002.JPG", "IMG_0003.jpeg", "IMG_0004.jpg"):
        (card / "DCIM" / n).write_bytes(b"x" * 20_000)
    (card / "DCIM" / "tiny.jpg").write_bytes(b"x")
    (card / "$RECYCLE.BIN").mkdir()
    (card / "$RECYCLE.BIN" / "old.jpg").write_bytes(b"x" * 20_000)
    yield card, tmp_path / "logs"
    srv.shutdown()


def _r_upload(card, logs):
    code = (f'cehbio::cehbio_upload(folder = "{card.as_posix()}", country = "thailand", deployment = "Doi Suthep", '
            f'data_type = "snapshot_images", name = "Jo Bloggs", test = FALSE, yes = TRUE, parallel = 2, '
            f'log_dir = "{logs.as_posix()}")')
    return subprocess.run([RSCRIPT, "-e", code], capture_output=True, text=True)


def test_upload_from_r_then_finish_in_python(service, tmp_path):
    card, logs = service
    r = _r_upload(card, logs)
    assert r.returncode == 0, r.stderr[-2000:]
    # 0002 fails once and is retried within the run; tiny files and the recycle bin are skipped
    assert set(Fake.stored) == {"IMG_0001.jpg", "IMG_0002.JPG", "IMG_0003.jpeg", "IMG_0004.jpg"}
    assert all(size == 20_000 and t == "image/jpeg" for size, t in Fake.stored.values())
    assert {(f.get("country"), f.get("deployment"), f.get("data_type")) for f in Fake.seen_fields if "filename" in f} \
        == {("tha", "dep000078", "snapshot_images")}
    logtext = next(logs.glob("*.csv")).read_text()
    assert "hunter2" not in logtext and "SECRET" not in logtext
    # the Python tool reads R's log and has nothing left to do
    from ceh_biomonitoring import upload
    from ceh_biomonitoring.settings import Settings
    Fake.seen_fields = []
    s = Settings.load(profile="local", overrides={"outputs_root": str(tmp_path / "out")}, settings_file=tmp_path / "x.yml")
    args = argparse.Namespace(folder=str(card), country="thailand", deployment="Doi Suthep", data_type="snapshot_images",
                              name="Jo Bloggs", test=False, yes=True, skip_remote_check=False, parallel=2,
                              log_dir=str(logs))
    upload.run(args, s)
    assert not [f for f in Fake.seen_fields if "filename" in f], "nothing uploaded twice"


def test_r_resumes_and_skips_whats_there(service):
    card, logs = service
    Fake.fail_once = set()
    assert _r_upload(card, logs).returncode == 0
    (card / "DCIM" / "IMG_0005.jpg").write_bytes(b"y" * 30_000)
    Fake.seen_fields = []
    r = _r_upload(card, logs)
    assert r.returncode == 0 and "Resuming: 4 files already uploaded" in r.stderr, r.stderr[-1500:]
    assert [f["filename"] for f in Fake.seen_fields if f.get("filename") and "file_type" in f] == ["IMG_0005.jpg"]


def test_wrong_password_is_said_plainly(service, monkeypatch):
    card, logs = service
    monkeypatch.setenv("CEHBIO_UPLOAD_PASSWORD", "wrong")
    r = _r_upload(card, logs)
    assert r.returncode != 0 and "did not accept your username or password" in r.stderr


def test_list_and_request_deployments_from_r(service):
    code = ('t <- cehbio::cehbio_deployments(); stopifnot(nrow(t) == 1, t$id == "dep000078"); '
            'id <- cehbio::cehbio_request_deployment(name = "Jo Bloggs", country = "Thai", site = "New site", lat = 13.1, '
            'lon = 98.9, device_type = "AMI trap", device_id = "cam09", start = "2027-05-01", yes = TRUE); '
            'stopifnot(id == "dep000999")')
    r = subprocess.run([RSCRIPT, "-e", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    sent = [f for f in Fake.seen_fields if "location_name" in f][0]
    assert sent["country"] == "Thailand" and sent["lat"] == "13.1" and sent["camera_id"] == "cam09"
    assert set(sent) == {"country", "location_name", "lat", "lon", "camera_id", "requested_by", "device_type",
                         "start_date", "end_date", "notes", "username", "password"}
    assert "Sent. Your deployment ID is dep000999" in r.stderr
