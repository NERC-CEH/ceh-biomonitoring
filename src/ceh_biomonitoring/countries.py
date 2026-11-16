"""Country table (folder name and object-store bucket per country), for --country.

The table is provided by an organisation's plug-in through the entry-point group
"ceh_biomonitoring.data" (a package containing countries.csv), or by setting countries_file.
Without one, use --bucket (an object-store bucket) or --folder (files on disk).
"""
from __future__ import annotations

from importlib import metadata, resources

import pandas as pd

from .settings import Settings


def load(settings: Settings) -> pd.DataFrame:
    custom = settings.get("countries_file")
    if custom:
        return pd.read_csv(custom)
    for ep in metadata.entry_points(group="ceh_biomonitoring.data"):
        f = resources.files(ep.value).joinpath("countries.csv")
        if f.is_file():
            with f.open() as fh:
                return pd.read_csv(fh)
    raise SystemExit("No country table is installed. Use --bucket <bucket name> or --folder <path> instead of --country.")


def get(settings: Settings, country: str) -> dict:
    df = load(settings)
    active = df[df["active"].astype(str).str.upper() == "TRUE"]
    hit = active[(active["country_folder"] == country) | (active["bucket_code"] == country)]
    if hit.empty:
        known = ", ".join(sorted(active["country_folder"]))
        raise SystemExit(f"Unknown country '{country}'. Known: {known}")
    return hit.iloc[0].to_dict()
