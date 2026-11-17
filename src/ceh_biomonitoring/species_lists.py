"""Reading a species list: a CSV with a 'species' column of scientific names (other columns are ignored).

Any pipeline can be given one with --set species_list=<file>, so species never recorded near the site
aren't reported. Lists can come from anywhere; UKCEH builds them from open records.
"""
from __future__ import annotations

from pathlib import Path


def norm(name: str) -> str:
    """Compare names on genus + species only, ignoring case and authors."""
    return " ".join(str(name).replace("_", " ").split()[:2]).lower()


def read(path: str | Path) -> set[str]:
    import pandas as pd
    df = pd.read_csv(path)
    col = next((c for c in df.columns if c.lower() in ("species", "scientific_name", "scientific name")), None)
    if col is None:
        raise SystemExit(f"{path} needs a 'species' column of scientific names")
    names = {norm(x) for x in df[col].dropna() if str(x).strip()}
    if not names:
        raise SystemExit(f"{path} has no species in it")
    return names
