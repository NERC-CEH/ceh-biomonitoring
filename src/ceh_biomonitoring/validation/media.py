"""Getting the recordings and photos a selection points to: from disk when they're there, otherwise from
the object store, with your own credentials (credentials_file in your settings), on any machine.

Where a file is looked for, in order:
  1. the path in the results, if it exists on this machine
  2. --source-root: a folder holding copies (searched by file name), e.g. a hard drive of a deployment
  3. the object store: the results' own key, in the bucket from --bucket, the results (bucket_name), or
     the country table (country_folder -> bucket). Results whose path is a file on another machine (for
     example a temporary download folder) are found at <deployment>/<data type>/<file name>, the layout
     uploads use
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pandas as pd

from .units import GROUPS


class Media:
    """Use as:  with Media(settings, group, bucket, source_root) as m:  path = m.get(row)"""

    def __init__(self, settings, group: str, bucket: str | None = None, source_root: str | None = None):
        self.settings, self.group, self.bucket = settings, group, bucket
        self.roots = [Path(source_root)] if source_root else []
        self._index: dict[str, Path] | None = None
        self._s3 = None
        self._buckets: dict[str, str] | None = None
        self._tmp = None

    def __enter__(self):
        base = None
        try:
            base = self.settings.tmp_root
            base.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001 - fall back to the system temp folder
            base = None
        self._tmp = Path(tempfile.mkdtemp(prefix="cehbio_validate_", dir=base))
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -------------------------------------------------------------- where the file is
    def _local(self, name: str) -> Path | None:
        if not self.roots:
            return None
        if self._index is None:
            self._index = {}
            for r in self.roots:
                for p in r.rglob("*"):
                    if p.is_file():
                        self._index.setdefault(p.name, p)
        return self._index.get(name)

    def bucket_for(self, row) -> str | None:
        if self.bucket:
            return self.bucket
        b = row.get("bucket") if isinstance(row, dict) else getattr(row, "bucket", None)
        if b and str(b) not in ("local", "nan", "None"):
            return str(b)
        folder = row.get("country_folder") if isinstance(row, dict) else getattr(row, "country_folder", None)
        if folder and str(folder) not in ("local", "nan", "None"):
            if self._buckets is None:
                from .. import countries
                try:
                    t = countries.load(self.settings)
                    self._buckets = dict(zip(t["country_folder"].astype(str), t["bucket_code"].astype(str)))
                except (Exception, SystemExit):  # noqa: BLE001
                    self._buckets = {}
            return self._buckets.get(str(folder), str(folder))
        return None

    @staticmethod
    def key_for(path: str, deployment: str, data_type: str) -> str:
        p = str(path)
        if p.startswith("/") or (len(p) > 1 and p[1] == ":"):         # a path on some machine, not a key
            return f"{deployment}/{data_type}/{Path(p).name}"
        return p

    def get(self, row) -> Path:
        """A local path to the row's recording or photo (downloaded to a temporary folder if need be).
        Raises an error that says what was tried."""
        r = row if isinstance(row, dict) else row._asdict()
        path = str(r.get("image_path") if self.group == "images" else r.get("source_key"))
        if Path(path).is_file():
            return Path(path)
        found = self._local(Path(path).name)
        if found:
            return found
        bucket = self.bucket_for(r)
        if not bucket:
            raise FileNotFoundError(f"{path} isn't on this machine and no bucket is known: give --bucket, "
                                    f"or --source-root <folder with the files>")
        key = self.key_for(path, str(r.get("deployment_id") or ""), GROUPS[self.group]["data_type"])
        local = self._tmp / Path(key).name
        if not local.exists():
            if self._s3 is None:
                from .. import objectstore
                self._s3 = objectstore.client(self.settings)
            try:
                self._s3.download_file(bucket, key, str(local))
            except Exception as e:  # noqa: BLE001
                local.unlink(missing_ok=True)
                raise FileNotFoundError(f"not on this machine, and object store {bucket}:{key} gave "
                                        f"{type(e).__name__}: {e}") from e
        return local

    def done_with(self, path: Path) -> None:
        """Delete a downloaded copy (keeps disk use to one file at a time)."""
        if self._tmp and Path(path).parent == self._tmp:
            Path(path).unlink(missing_ok=True)


def by_source(sel: pd.DataFrame, group: str) -> list[tuple[str, pd.DataFrame]]:
    """Rows grouped by their recording or photo, so each is fetched once."""
    col = "image_path" if group == "images" else "source_key"
    return list(sel.groupby(col, sort=False, observed=True))
