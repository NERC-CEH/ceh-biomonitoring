"""Split a deployment's files into chunk JSONs, one per Slurm task.

Layout under <outputs_root>/<pipeline>/<country>/:
    keys/chunks/<deployment>/<deployment>_chunk_00001.json
    keys/manifests/<deployment>/manifest.json
Chunk JSONs keep the field names the older scripts used (audio_keys / image_keys),
so existing chunk files still work.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def chunk_dir(base: Path, deployment: str) -> Path:
    return base / "keys" / "chunks" / deployment


def manifest_path(base: Path, deployment: str) -> Path:
    return base / "keys" / "manifests" / deployment / "manifest.json"


def write_chunks(base: Path, country: dict, deployment: str, keys: list[str], files_per_chunk: int,
                 key_field: str, data_type: str, extra: dict | None = None) -> list[Path]:
    out = chunk_dir(base, deployment)
    if out.exists() and any(out.glob("*.json")):
        raise SystemExit(f"Chunks already exist in {out}. Delete them first if you want to rebuild.")
    n = math.ceil(len(keys) / files_per_chunk) if keys else 0
    paths = []
    for i in range(n):
        part = keys[i * files_per_chunk:(i + 1) * files_per_chunk]
        p = out / f"{deployment}_chunk_{i + 1:05d}.json"
        write_json(p, {
            "country_name": country["country_name"], "country_folder": country["country_folder"],
            "bucket_code": country["bucket_code"], "deployment_id": deployment, "data_type": data_type,
            "chunk_index": i + 1, "n_chunks": n, "n_files": len(part), key_field: part, **(extra or {}),
        })
        paths.append(p)
    write_json(manifest_path(base, deployment), {
        "created_at": now_utc(), "country_folder": country["country_folder"],
        "bucket_code": country["bucket_code"], "deployment_id": deployment, "data_type": data_type,
        "total_files": len(keys), "files_per_chunk": files_per_chunk, "n_chunks": n,
        "chunk_dir": str(out), **(extra or {}),
    })
    return paths


def read_chunk(path: Path) -> dict:
    chunk = json.loads(Path(path).read_text())
    for field in ("keys", "audio_keys", "image_keys"):
        if field in chunk:
            chunk["keys"] = chunk[field]
            break
    else:
        raise SystemExit(f"{path} has no list of files (keys / audio_keys / image_keys).")
    return chunk
