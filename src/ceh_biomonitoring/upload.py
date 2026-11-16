"""Upload recordings or images to UKCEH through the UKCEH upload service.

Partners never need object-store keys: they sign in to the upload service, which hands out a
one-off upload link per file. Ported from the AMI interactive_upload.py (March 2026) with the same
service calls; improvements: hidden password, .JPG/.WAV found too, one log folder, unattended mode.

    cehbio upload                    asks everything step by step
    cehbio upload --folder E:/DCIM --country Thailand --deployment "Site A - cam01" \
                  --data-type snapshot_images --name "Jo Bloggs" --yes

Resuming: every file is logged as it goes. Run the same command again and files already
uploaded are skipped.
"""
from __future__ import annotations

import csv
import getpass
import mimetypes
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_URL = "https://connect-apps.ceh.ac.uk/ceh-biomonitoring-upload/"   # the UKCEH upload service
MIN_BYTES = 10 * 1024                       # skip tiny/empty files
SKIP_PARTS = ("$RECYCLE.BIN", ".Trashes", ".Trash-0", "System Volume Information")
IMAGE_TYPES = ("snapshot_images",)
EXTENSIONS = {"snapshot_images": (".jpg", ".jpeg")}
DEFAULT_AUDIO = (".wav",)
SALTMARSH = "united kingdom (saltmarsh soundscapes)"
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _retry(fn, attempts=5, base=2.0):
    for i in range(attempts):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            if i == attempts - 1:
                raise
            time.sleep(min(60, base * 2 ** i))


class UploadService:
    def __init__(self, url: str, username: str, password: str):
        import requests
        self.url, self.http = url.rstrip("/") + "/", requests.Session()
        self.auth = {"username": username, "password": password}

    def _post(self, path: str, fields: dict):
        r = self.http.post(self.url + path, data={**fields, **self.auth}, timeout=300)
        if r.status_code == 401:
            raise PermissionError("The upload service did not accept your username or password.")
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code} at {path}: {r.text[:500]}")
        try:
            return r.json()
        except ValueError:
            return r.text

    def deployments(self) -> list[dict]:
        return self._post("get-deployments/", {})

    def exists(self, base: dict, filename: str) -> bool:
        d = _retry(lambda: self._post("check-file-exist/", {**base, "filename": filename}))
        if isinstance(d, dict):
            if "exists" in d:
                return bool(d["exists"])
            if isinstance(d.get("result"), dict) and "exists" in d["result"]:
                return bool(d["result"]["exists"])
            if isinstance(d.get(filename), (bool, int)):
                return bool(d[filename])
        raise RuntimeError(f"Unexpected reply from check-file-exist: {str(d)[:300]}")

    def upload_link(self, base: dict, filename: str, file_type: str) -> str:
        d = _retry(lambda: self._post("generate-presigned-url/", {**base, "filename": filename, "file_type": file_type}))
        if isinstance(d, str):
            return d.strip().strip('"')
        if isinstance(d, dict):
            for v in (d.get("url"), d.get(filename), (d.get("result") or {}).get("url") if isinstance(d.get("result"), dict) else None):
                if isinstance(v, str):
                    return v
        raise RuntimeError(f"Unexpected reply from generate-presigned-url: {str(d)[:300]}")

    def put(self, link: str, path: Path, file_type: str) -> None:
        if not link.lower().startswith(("http://", "https://")):
            raise RuntimeError("The upload service returned an invalid upload link.")

        def go():
            with open(path, "rb") as f:
                r = self.http.put(link, data=f, headers={"Content-Type": file_type}, timeout=3600)
            if r.status_code >= 400:
                raise RuntimeError(f"upload failed HTTP {r.status_code}: {r.text[:300]}")
        _retry(go)


# ---------------------------------------------------------------- files and the log
def find_files(folder: Path, data_type: str) -> list[Path]:
    exts = EXTENSIONS.get(data_type, DEFAULT_AUDIO)
    out = []
    for p in folder.rglob("*"):
        try:
            if (p.is_file() and p.suffix.lower() in exts and not any(s in str(p) for s in SKIP_PARTS)
                    and p.stat().st_size >= MIN_BYTES):
                out.append(p)
        except OSError:
            continue
    return sorted(out)


def log_path(log_dir: Path, bucket: str, dep: str, data_type: str) -> Path:
    safe = lambda s: s.replace("/", "_").replace(" ", "_")
    return log_dir / f"upload_status_{safe(bucket)}_{safe(dep)}_{safe(data_type)}.csv"


def log(path: Path, local: Path, stage: str, status: str, detail: str = "") -> None:
    with _lock:
        new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["timestamp_utc", "local_path", "filename", "stage", "status", "detail"])
            w.writerow([_now(), str(local), local.name, stage, status, detail[:1000]])


def already_uploaded(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return {r["filename"] for r in csv.DictReader(f) if r.get("stage") == "UPLOAD" and r.get("status") == "OK"}
    except Exception:  # noqa: BLE001 - a damaged log just disables resuming
        return set()


def upload_one(svc: UploadService, base: dict, path: Path, logp: Path, check_remote: bool) -> str:
    file_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    if check_remote:
        try:
            if svc.exists(base, path.name):
                log(logp, path, "CHECK_REMOTE", "OK", "exists=True")
                return "already there"
            log(logp, path, "CHECK_REMOTE", "OK", "exists=False")
        except Exception as e:  # noqa: BLE001 - try the upload anyway
            log(logp, path, "CHECK_REMOTE", "FAIL", str(e))
    try:
        link = svc.upload_link(base, path.name, file_type)
        log(logp, path, "PRESIGN", "OK")              # the link itself is not logged
    except Exception as e:  # noqa: BLE001
        log(logp, path, "PRESIGN", "FAIL", str(e))
        return "failed"
    try:
        svc.put(link, path, file_type)
        log(logp, path, "UPLOAD", "OK")
        return "uploaded"
    except Exception as e:  # noqa: BLE001
        log(logp, path, "UPLOAD", "FAIL", str(e))
        return "failed"


# ---------------------------------------------------------------- the conversation
def clean_path(text: str) -> Path:
    """A folder typed or dragged in: drop surrounding spaces and quotation marks."""
    return Path(text.strip().strip("\"'").strip())


def _ask(prompt: str, default: str | None = None) -> str:
    v = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return v or (default or "")


def _choose(prompt: str, options: list[str], given: str | None = None) -> str:
    if given:
        hit = [o for o in options if o.lower() == given.lower()] or [o for o in options if given.lower() in o.lower()]
        if len(hit) == 1:
            return hit[0]
        raise SystemExit(f"'{given}' doesn't match one of: {', '.join(options)}")
    print(prompt)
    for i, o in enumerate(options, 1):
        print(f"  {i}. {o}")
    while True:
        c = input("Choose a number: ").strip()
        if c.isdigit() and 1 <= int(c) <= len(options):
            return options[int(c) - 1]
        print("Please type one of the numbers above.")


def saved_login(settings) -> dict:
    """The upload login from the credentials file, if there is one (UKCEH_username / UKCEH_password,
    the same names the older pipelines use). Never required: partners are simply asked."""
    import json
    from .objectstore import credentials_path
    path = credentials_path(settings)
    try:
        if os.name == "posix" and path.stat().st_mode & 0o044:
            print(f"Not using the login in {path}: other people can read it (fix with chmod 600 {path}).")
            return {}
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def run(args, settings) -> None:
    saved = saved_login(settings)
    url = saved.get("UPLOAD_URL") or settings.get("upload.url") or DEFAULT_URL
    user = os.environ.get("CEHBIO_UPLOAD_USER") or saved.get("UKCEH_username") or _ask("Upload service username")
    pw = (os.environ.get("CEHBIO_UPLOAD_PASSWORD") or saved.get("UKCEH_password")
          or getpass.getpass("Upload service password (hidden): "))
    svc = UploadService(url, user, pw)
    print("Fetching the list of deployments...")
    deps = [d for d in svc.deployments() if d.get("status") == "active"]

    name = args.name or _ask("Your full name")
    countries = sorted({d["country"] for d in deps}) + ["Test"]
    country = _choose("\nCountry:", countries, args.country)
    if country == "Test":
        bucket, dep_id = "test-upload", "dep_test"
    else:
        here = [d for d in deps if d["country"] == country]
        labels = [f"{d['location_name']} - {d['camera_id']}" for d in here]
        label = _choose("\nDeployment:", labels, args.deployment)
        d = here[labels.index(label)]
        bucket, dep_id = d["country_code"].lower(), d["deployment_id"]
    types = (["terrestrial_recordings", "aquatic_recordings"] if country.lower() == SALTMARSH
             else ["snapshot_images", "audible_recordings", "ultrasound_recordings"])
    data_type = _choose("\nWhat are you uploading?", types, args.data_type)

    folder = clean_path(args.folder or _ask("\nFolder with the files (e.g. the SD card)"))
    while not folder.is_dir():
        if args.folder:
            raise SystemExit(f"Folder not found: {folder}")
        folder = clean_path(_ask("That folder doesn't exist. Folder path"))
    files = find_files(folder, data_type)
    if not files:
        raise SystemExit(f"No {data_type} files found in {folder}")

    logp = log_path(Path(args.log_dir or settings.path("outputs_root") / "upload_logs"), bucket, dep_id, data_type)
    done = already_uploaded(logp)
    if done:
        before = len(files)
        files = [f for f in files if f.name not in done]
        print(f"\nResuming: {before - len(files)} files already uploaded earlier, {len(files)} still to do.")
    if args.test or (not args.yes and _ask("\nTry 10 random files first as a test? (yes/no)", "no").lower().startswith("y")):
        files = random.sample(files, k=min(10, len(files)))
        print(f"Test run with {len(files)} files.")

    print(f"\n  Name:        {name}\n  Destination: {bucket} / {dep_id} / {data_type}\n"
          f"  Files:       {len(files)} from {folder}\n  Log:         {logp}")
    if not files:
        print("Nothing left to upload.")
        return
    if not args.yes and not _ask("\nStart uploading? (yes/no)", "no").lower().startswith("y"):
        print("Cancelled.")
        return

    base = {"name": name, "country": bucket, "deployment": dep_id, "data_type": data_type}
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futs = [pool.submit(upload_one, svc, base, f, logp, not args.skip_remote_check) for f in files]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            counts[r] = counts.get(r, 0) + 1
            if i % 25 == 0 or i == len(futs):
                print(f"  {i}/{len(futs)} done: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), flush=True)
    print(f"\nFinished: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + f"\nLog: {logp}")
    if counts.get("failed"):
        print("Some files failed. Run the same command again to retry just those.")
