"""Species lists: which species a pipeline may report.

A list is a CSV with a 'species' column of scientific names. It can also have a 'month' column (1-12):
then each recording or photo uses the species listed for ITS month, read from the date in its file
name, so a list can follow the seasons (e.g. no Swallows in January). Rows without a month apply all
year. Files whose date can't be read use every species in the list.

    --set species_list=<file>       works with BirdNET, Perch, bats and images

UKCEH builds monthly lists from open records (cehbio species-list, in-house); any list in this format
works.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def norm(name: str) -> str:
    """Compare names on genus + species only, ignoring case and authors."""
    return " ".join(str(name).replace("_", " ").split()[:2]).lower()


class SpeciesList:
    def __init__(self, path: str | Path):
        import pandas as pd
        df = pd.read_csv(path)
        col = next((c for c in df.columns if c.lower() in ("species", "scientific_name", "scientific name")), None)
        if col is None:
            raise SystemExit(f"{path} needs a 'species' column of scientific names")
        df = df[df[col].notna() & (df[col].astype(str).str.strip() != "")]
        if df.empty:
            raise SystemExit(f"{path} has no species in it")
        self.path = str(path)
        self.all_year: set[str] = set()
        self.by_month: dict[int, set[str]] = {}
        months = df["month"] if "month" in df.columns else [None] * len(df)
        for name, m in zip(df[col], months):
            if m is None or str(m).strip() in ("", "nan", "all"):
                self.all_year.add(norm(name))
            else:
                self.by_month.setdefault(int(float(m)), set()).add(norm(name))
        self.everything = set(self.all_year).union(*self.by_month.values()) if self.by_month else set(self.all_year)

    @property
    def monthly(self) -> bool:
        return bool(self.by_month)

    def allowed(self, month: int | None = None) -> set[str]:
        """The species allowed in a month (or all of them if the month isn't known)."""
        if month is None or not self.by_month:
            return self.everything
        return self.all_year | self.by_month.get(int(month), set())

    def describe(self) -> str:
        if self.monthly:
            sizes = [len(self.allowed(m)) for m in range(1, 13)]
            return f"monthly list, {min(sizes)}-{max(sizes)} species a month ({len(self.everything)} in all)"
        return f"{len(self.everything)} species, all year"


def read(path: str | Path) -> set[str]:
    """Every species in a list (all months together)."""
    return SpeciesList(path).everything


_DATE = re.compile(r"(?<!\d)(20\d{2})[-_]?(0[1-9]|1[0-2])[-_]?(0[1-9]|[12]\d|3[01])(?!\d)")


def file_date(key: str, chunk: dict | None = None) -> datetime | None:
    """A recording's or photo's date: from its recorder's file-name pattern if known, else the first
    YYYYMMDD (or YYYY-MM-DD) in its name."""
    chunk = chunk or {}
    if chunk.get("device") or chunk.get("timestamp_pattern"):
        from . import devices
        dev = devices.get(chunk["device"]) if chunk.get("device") else None
        dt = devices.parse_filename(str(key), dev, chunk.get("timestamp_pattern"))["file_datetime"]
        if dt:
            return datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
    m = _DATE.search(Path(str(key)).name)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def file_month(key: str, chunk: dict | None = None) -> int | None:
    d = file_date(key, chunk)
    return d.month if d else None


def birdnet_week(d: datetime | None) -> int:
    """BirdNET's week (1-48: four per month), or -1 for all year."""
    if d is None:
        return -1
    return min(48, (d.month - 1) * 4 + min(4, (d.day - 1) // 7 + 1))
