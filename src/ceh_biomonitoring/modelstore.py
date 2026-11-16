"""Find, download and check model files listed in a model list (models.yml).

Each file in the list has a name, a size and a SHA-256 checksum. A file is looked for:
  1. in the download cache (models.cache_dir)
  2. in any folder in models.search_dirs, by its original file name (e.g. a team's model folder)
  3. otherwise it is downloaded (from its own url, or from the list's release address)
and only used if its checksum matches, so results are always made with exactly the listed model.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

import yaml

_INDEX: dict[str, dict[str, list[Path]]] = {}


def load_list(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def cache_dir(settings) -> Path:
    return Path(os.path.expanduser(settings.get("models.cache_dir") or "~/.cache/ceh-biomonitoring/models"))


def search_dirs(settings) -> list[Path]:
    return [Path(os.path.expanduser(d)) for d in (settings.get("models.search_dirs") or [])]


def _local_index(folder: Path) -> dict[str, list[Path]]:
    key = str(folder)
    if key not in _INDEX:
        idx: dict[str, list[Path]] = {}
        if folder.is_dir():
            for p in folder.rglob("*"):
                if p.is_file():
                    idx.setdefault(p.name, []).append(p)
        _INDEX[key] = idx
    return _INDEX[key]


def _verified_ok(path: Path, entry: dict, cache: Path) -> bool:
    """Check size always and the checksum once per file version (remembered in the cache)."""
    try:
        st = path.stat()
    except OSError:
        return False
    if entry.get("bytes") and st.st_size != int(entry["bytes"]):
        return False
    if not entry.get("sha256"):
        return True
    memo_file = cache / "verified.json"
    try:
        memo = json.loads(memo_file.read_text())
    except (OSError, ValueError):
        memo = {}
    stamp = f"{st.st_size}:{int(st.st_mtime)}"
    if memo.get(str(path)) == [stamp, entry["sha256"]]:
        return True
    ok = sha256(path) == entry["sha256"]
    if ok:
        memo[str(path)] = [stamp, entry["sha256"]]
        try:
            cache.mkdir(parents=True, exist_ok=True)
            memo_file.write_text(json.dumps(memo, indent=0))
        except OSError:
            pass
    return ok


def _download(url: str, dest: Path, entry: dict) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {dest.name} ({int(entry.get('bytes') or 0) / 1e6:.0f} MB) ...", flush=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".")
    os.close(fd)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ceh-biomonitoring"})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        if entry.get("sha256") and sha256(Path(tmp)) != entry["sha256"]:
            raise RuntimeError(f"{dest.name}: the downloaded file does not match its checksum")
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return dest


def fetch(settings, model_list: dict, model: str, part: str) -> Path | None:
    """Local path of one file of a listed model, downloading it if needed.
    Returns None for a file the model's own package downloads itself (no url and no release asset)."""
    models = model_list.get("models", {})
    if model not in models:
        raise SystemExit(f"Unknown model '{model}'. See: cehbio models")
    entry = (models[model].get("files") or {}).get(part)
    if entry is None:
        raise SystemExit(f"Model '{model}' has no '{part}' file")
    cache = cache_dir(settings)
    asset = entry.get("asset") or entry["name"]
    candidates = [cache / asset]
    for d in search_dirs(settings):
        candidates += _local_index(d).get(entry["name"], [])
    for c in candidates:
        if c.exists() and _verified_ok(c, entry, cache):
            return c
    url = entry.get("url") or (model_list.get("release", "") + entry["asset"] if entry.get("asset") else "")
    if not url:
        return None
    return _download(url, cache / asset, entry)


def describe(model_list: dict, model: str) -> dict:
    """Provenance for one model: its name and every file's checksum."""
    m = model_list["models"][model]
    return {"model": model, "by": m.get("by", ""), "date": str(m.get("date", "")), "licence": m.get("licence", ""),
            "files": {k: {"name": v.get("asset") or v["name"], "sha256": v.get("sha256", "")}
                      for k, v in (m.get("files") or {}).items()}}
