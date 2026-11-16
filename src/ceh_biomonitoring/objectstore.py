"""Object store access: one private credentials file per person, read-only helpers.

Credentials file (JSON), by default ~/.config/ceh-biomonitoring/credentials.json:

    {"AWS_ACCESS_KEY_ID": "...", "AWS_SECRET_ACCESS_KEY": "...",
     "AWS_URL_ENDPOINT": "https://<your-tenancy>.s3-ext.jc.rl.ac.uk", "AWS_REGION": "eu-west-2"}

Make it private:  chmod 600 ~/.config/ceh-biomonitoring/credentials.json
Never commit it, share it, or paste it into chat.
"""
from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .settings import Settings

REQUIRED = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")


class CredentialsError(RuntimeError):
    pass


def credentials_path(settings: Settings) -> Path:
    return Path(os.environ.get("CEHBIO_CREDENTIALS") or settings.path("credentials_file"))


def load_credentials(settings: Settings) -> dict:
    path = credentials_path(settings)
    if not path.exists():
        raise CredentialsError(
            f"No credentials file at {path}.\n"
            f"Copy credentials/credentials.example.json there, add your object store key, "
            f"then run: chmod 600 {path}"
        )
    if os.name == "posix" and path.stat().st_mode & (stat.S_IRGRP | stat.S_IROTH):
        raise CredentialsError(f"{path} can be read by other people. Fix it with: chmod 600 {path}")
    creds = json.loads(path.read_text())
    missing = [k for k in REQUIRED if not creds.get(k)]
    if missing:
        raise CredentialsError(f"{path} is missing {', '.join(missing)}")
    return creds


def endpoint(settings: Settings, creds: dict) -> str:
    return settings.get("object_store.endpoint") or creds.get("AWS_URL_ENDPOINT") or ""


def client(settings: Settings):
    import boto3
    from botocore.config import Config

    creds = load_credentials(settings)
    return boto3.client(
        "s3",
        endpoint_url=endpoint(settings, creds) or None,
        aws_access_key_id=creds["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=creds["AWS_SECRET_ACCESS_KEY"],
        region_name=creds.get("AWS_REGION") or None,
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
    )


def check_access(settings: Settings, bucket: str | None = None) -> tuple[bool, str]:
    """Read-only test. Returns (ok, message) and never prints secrets."""
    from botocore.exceptions import ClientError, EndpointConnectionError

    try:
        s3 = client(settings)
        if bucket:
            s3.list_objects_v2(Bucket=bucket, MaxKeys=1)
            return True, f"can read bucket '{bucket}'"
        names = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
        return True, f"can list {len(names)} buckets"
    except CredentialsError as e:
        return False, str(e)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "?")
        hint = " Your key may have expired: make a new one at https://s3-portal.jasmin.ac.uk" if code in ("AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "403") else ""
        return False, f"object store refused the request ({code}).{hint}"
    except EndpointConnectionError as e:
        return False, f"cannot reach the object store: {e}"


def list_keys(s3, bucket: str, prefix: str, extensions: Iterable[str], max_keys: int | None = None,
              progress: Callable[[dict], None] | None = None, progress_every_pages: int = 10) -> list[str]:
    exts = tuple(e.lower() for e in extensions)
    keys: list[str] = []
    pages = objects = 0
    start = time.time()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        pages += 1
        contents = page.get("Contents", [])
        objects += len(contents)
        keys.extend(item["Key"] for item in contents if item["Key"].lower().endswith(exts))
        done = max_keys is not None and len(keys) >= max_keys
        if progress and (pages % progress_every_pages == 0 or done):
            progress({"pages_scanned": pages, "objects_scanned": objects, "matching_keys": len(keys),
                      "elapsed_seconds": round(time.time() - start, 1)})
        if done:
            return sorted(keys[:max_keys])
    return sorted(keys)


def download(s3, bucket: str, keys: Iterable[str], dest: Path) -> Iterator[tuple[str, Path | None, str | None]]:
    """Yield (key, local_path or None, error or None) for each key, so one bad file doesn't stop a chunk."""
    dest.mkdir(parents=True, exist_ok=True)
    for key in keys:
        local = dest / Path(key).name
        try:
            s3.download_file(bucket, key, str(local))
            yield key, local, None
        except Exception as e:  # noqa: BLE001 - recorded per file
            yield key, None, f"{type(e).__name__}: {e}"
