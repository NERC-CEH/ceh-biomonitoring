"""cehbio uploaded: the files already stored for one of your deployments, and downloading them.

It asks the UKCEH upload service, with your own upload login, so you need no object-store key, and you
only see your own deployments (finished ones too). Listing a big deployment takes a while: the store
gives 1,000 files at a time. Use --name-prefix (e.g. a date, 202605) to list part of it.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

from .upload import DEFAULT_URL, UploadService, _ask, saved_login

TYPES = ["snapshot_images", "audible_recordings", "ultrasound_recordings", "terrestrial_recordings", "aquatic_recordings",
         "motion_images"]


def service(settings) -> UploadService:
    import getpass
    saved = saved_login(settings)
    url = saved.get("UPLOAD_URL") or settings.get("upload.url") or DEFAULT_URL
    user = os.environ.get("CEHBIO_UPLOAD_USER") or saved.get("UKCEH_username") or _ask("Upload service username")
    pw = (os.environ.get("CEHBIO_UPLOAD_PASSWORD") or saved.get("UKCEH_password")
          or getpass.getpass("Upload service password (hidden): "))
    return UploadService(url, user, pw)


def find_deployment(deps: list[dict], given: str) -> dict:
    """A deployment by its ID, or by (part of) its site name if that's unique."""
    g = (given or "").strip().lower()
    exact = [d for d in deps if d.get("deployment_id", "").lower() == g]
    if exact:
        return exact[0]
    hits = [d for d in deps if g and g in f"{d.get('location_name', '')} {d.get('camera_id', '')}".lower()]
    if len(hits) == 1:
        return hits[0]
    names = ", ".join(f"{d['deployment_id']} ({d.get('location_name', '')})" for d in (hits or deps)[:15])
    raise SystemExit(f"{'Several' if hits else 'No'} deployments match '{given}'. Yours: {names or 'none yet'}")


def list_files(svc: UploadService, dep: dict, data_type: str, name_prefix: str = "", quiet: bool = False) -> list[dict]:
    base = {"country": dep["country_code"].lower(), "deployment": dep["deployment_id"], "data_type": data_type}
    return svc.list_files(base, name_prefix, None if quiet else (lambda n: print(f"  {n} files so far...", flush=True)))


def run(args, settings) -> None:
    svc = service(settings)
    deps = svc.deployments()
    dep = find_deployment(deps, args.deployment or _ask("Deployment (ID or site name)"))
    data_type = args.data_type or _ask("Data type", "snapshot_images")
    if data_type not in TYPES:
        raise SystemExit(f"Data type must be one of: {', '.join(TYPES)}")
    print(f"Listing {dep['deployment_id']} ({dep.get('location_name', '')}), {data_type}"
          + (f", names starting '{args.name_prefix}'" if args.name_prefix else "") + "...")
    files = list_files(svc, dep, data_type, args.name_prefix or "")
    out = Path(args.out or f"{dep['deployment_id']}_{data_type}_files.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "size", "stored"])
        w.writeheader()
        w.writerows(files)
    total = sum(int(x.get("size") or 0) for x in files)
    print(f"{len(files)} files ({total / 1e9:.2f} GB) -> {out}")
    if args.download:
        dest = Path(args.download)
        dest.mkdir(parents=True, exist_ok=True)
        base = {"country": dep["country_code"].lower(), "deployment": dep["deployment_id"], "data_type": data_type}
        import requests
        for i, x in enumerate(files, 1):
            target = dest / x["filename"]
            if target.exists() and target.stat().st_size == int(x.get("size") or -1):
                continue                                         # already downloaded
            link = svc.download_link(base, x["filename"])
            with requests.get(link, stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(target, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            if i % 50 == 0 or i == len(files):
                print(f"  downloaded {i}/{len(files)}", flush=True)
        print(f"Downloaded to {dest}")


def add_command(sub, common) -> None:
    p = sub.add_parser("uploaded", parents=[common], help="list (and download) files already stored for your deployments",
                       description=__doc__, formatter_class=__import__("argparse").RawDescriptionHelpFormatter)
    p.add_argument("--deployment", help="deployment ID (e.g. dep000123) or part of its site name")
    p.add_argument("--data-type", help=", ".join(TYPES))
    p.add_argument("--name-prefix", help="only files whose names start with this, e.g. 202605")
    p.add_argument("--out", help="where to write the list (default <deployment>_<data type>_files.csv)")
    p.add_argument("--download", metavar="FOLDER", help="also download the listed files to this folder (skips ones already there)")
    p.set_defaults(func=lambda a: run(a, __import__("ceh_biomonitoring.cli", fromlist=["_settings"])._settings(a)))
