"""Split a deployment's files into chunk JSONs, one per Slurm task.

They go in the run's working/file_lists/ folder (see layout.py), with manifest.json beside them.
Chunk JSONs keep the field names the older scripts used (audio_keys / image_keys),
so existing chunk files still work.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def pack(groups: list[list[str]], size: int) -> list[list[str]]:
    """Put whole groups (e.g. nights) into chunks of up to `size` files, in order.
    A group bigger than `size` is split, as nothing else is possible."""
    chunks_, cur = [], []
    for g in groups:
        if len(g) > size:
            if cur:
                chunks_.append(cur)
                cur = []
            chunks_.extend(g[i:i + size] for i in range(0, len(g), size))
            continue
        if cur and len(cur) + len(g) > size:
            chunks_.append(cur)
            cur = []
        cur = cur + list(g)
    if cur:
        chunks_.append(cur)
    return chunks_


def write_chunks(out: Path, country: dict, deployment: str, keys: list[str], files_per_chunk: int,
                 key_field: str, data_type: str, extra: dict | None = None,
                 groups: list[list[str]] | None = None, manifest: Path | None = None) -> list[Path]:
    """Chunk JSONs in `out`, and the manifest (default out/manifest.json)."""
    out = Path(out)
    if out.exists() and any(p for p in out.glob("*.json") if p.name != "manifest.json"):
        raise SystemExit(f"Chunks already exist in {out}. Delete them first if you want to rebuild.")
    if groups is not None:
        parts = pack(groups, files_per_chunk)
        keys = [k for part in parts for k in part]
    else:
        parts = [keys[i:i + files_per_chunk] for i in range(0, len(keys), files_per_chunk)]
    n = len(parts)
    paths = []
    for i, part in enumerate(parts):
        p = out / f"{deployment}_chunk_{i + 1:05d}.json"
        write_json(p, {
            "country_name": country["country_name"], "country_folder": country["country_folder"],
            "bucket_code": country["bucket_code"], "deployment_id": deployment, "data_type": data_type,
            "chunk_index": i + 1, "n_chunks": n, "n_files": len(part), key_field: part, **(extra or {}),
        })
        paths.append(p)
    write_json(manifest or out / "manifest.json", {
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
