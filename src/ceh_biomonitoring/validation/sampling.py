"""Which units an expert checks: one set of rules for birds, bats and images.

Two purposes, kept apart so the same unit is never labelled twice:

  site-lists  per site: a few units of every species reported there, so an expert can confirm or reject
              each species on the site's list. With --species-table, only the species that table lists
              for the site (for example `bird-results` site lists)
  model       across all sites of ONE COUNTRY (one species model): many units per species, every species
              the model reported (its mistakes are what it learns from), to test or retrain that model.
              Countries are never mixed: results from several give one selection per country
  all         every unit (labelling everything, e.g. every crop of a deployment)

Anything already chosen (given with --exclude) is left out, so rounds can be added over time.

How picks are spread, so the expert sees a fair picture rather than the easiest or busiest cases:
  space        model: one per site first (busiest sites first), the rest in proportion to what each has
  confidence   the picks cover the model's score range: units are split into equal score bands, low to
               high, and one is taken from each
  time         from each band, the unit furthest in time from those already picked, so picks reach
               across the survey (different days, nights, weeks and months, where the data allow)
  'best'       (site-lists for birds and bats) the best-scoring unit, then the best on another day, then
               another recording: the clearest examples, for a quick "is it there?" check
Site-lists add species detected in a month their species list marks UNLIKELY (an early Swallow is a
real record if it's right, so it's checked, not removed). Images site-lists add some non-moth insects
("noise", in proportion to their orders, drawn at random with --seed), so the expert sees what the moth
filter removed. The full method, step by step: docs/sampling-methods.md.

--reserve N adds N spare units per species (and site) after the picks. They're used only when a
platform drops a pick, for example the Mothbot package's screens (geckos, leaves...), so the targets
are still met.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .units import GROUPS

PURPOSES = ("site-lists", "model", "all")
COMMON_COLUMNS = ["selection_id", "purpose", "group", "country", "model_group", "site", "period", "species",
                  "rank", "why", "reserve", "unit_id", "score", "score_type"]


# ------------------------------------------------------------------ the shared rules
def score_spread(df: pd.DataFrame, n: int, score: str = "score") -> pd.DataFrame:
    """n rows spread across the score range (quantiles 5%..95%), not just the highest scores."""
    if n <= 0 or df.empty:
        return df.iloc[0:0]
    if len(df) <= n:
        return df
    work = df.assign(_s=pd.to_numeric(df[score], errors="coerce")).sort_values("_s", na_position="last")
    work = work.reset_index(drop=True)
    idx: list[int] = []
    for q in ([0.5] if n == 1 else np.linspace(0.05, 0.95, n)):
        i = int(round(q * (len(work) - 1)))
        if i not in idx:
            idx.append(i)
    for i in range(len(work)):              # rounding can repeat an index: fill deterministically
        if len(idx) >= n:
            break
        if i not in idx:
            idx.append(i)
    return work.iloc[idx[:n]].drop(columns="_s")


def proportional(counts: pd.Series, total: int) -> dict:
    """Whole numbers in proportion to counts (largest remainder), never more than a count."""
    counts = counts[counts > 0].astype(int)
    if total <= 0 or counts.empty:
        return {}
    total = min(int(total), int(counts.sum()))
    raw = counts / counts.sum() * total
    alloc = np.floor(raw).astype(int)
    left = total - int(alloc.sum())
    for k in (raw - alloc).sort_values(ascending=False).index:
        if left <= 0:
            break
        if alloc[k] < counts[k]:
            alloc[k] += 1
            left -= 1
    return {k: int(v) for k, v in alloc.items() if v > 0}


def spread(df: pd.DataFrame, n: int, score: str = "score", period: str | None = "period") -> pd.DataFrame:
    """n rows covering the score range AND spread out in time: split the rows (sorted by score) into n
    equal bands; from each band take the row furthest in time (days) from the rows already picked, then
    the least-used period, then the row nearest the band's middle score."""
    if n <= 0 or df.empty:
        return df.iloc[0:0]
    if len(df) <= n:
        return df
    if not period or period not in df.columns:
        return score_spread(df, n, score)
    work = df.assign(_s=pd.to_numeric(df[score], errors="coerce")).sort_values("_s", na_position="last")
    work = work.reset_index(drop=True)
    edges = np.linspace(0, len(work), n + 1).round().astype(int)
    day = pd.to_datetime(work[period].astype(str).str[:10], format="%Y-%m-%d", errors="coerce")
    day = ((day - pd.Timestamp("2000-01-01")).dt.days).to_numpy(dtype=float)     # NaN when unknown
    label = work[period].astype(str).to_numpy()
    picked: list[float] = []
    used: dict = {}
    keep = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        mid = (a + b - 1) / 2
        known = [p for p in picked if not np.isnan(p)]

        def gap(i):
            return 0.0 if not known or np.isnan(day[i]) else min(abs(day[i] - p) for p in known)
        best = min(range(a, b), key=lambda i: (-gap(i), used.get(label[i], 0), abs(i - mid)))
        used[label[best]] = used.get(label[best], 0) + 1
        picked.append(day[best])
        keep.append(best)
    return work.iloc[keep].drop(columns="_s")


def best_then_others(df: pd.DataFrame, n: int, score: str = "score") -> pd.DataFrame:
    """The best-scoring unit, then the best on another day/night, then in another recording/photo, then
    the next best: the clearest examples, spread over time where possible. Adds a 'why' column."""
    if n <= 0 or df.empty:
        return df.iloc[0:0]
    work = df.assign(_s=pd.to_numeric(df[score], errors="coerce")).sort_values("_s", ascending=False,
                                                                                na_position="last")
    src = "source_key" if "source_key" in work.columns else ("image_path" if "image_path" in work.columns else None)
    picked, why, periods, sources = [], [], set(), set()
    for _ in range(min(n, len(work))):
        rest = work.drop(index=picked)
        if not picked:
            choice, reason = rest.index[0], "best"
        elif len(r := rest[~rest["period"].isin(periods)]):
            choice, reason = r.index[0], "best on another day"
        elif src and len(r := rest[~rest[src].isin(sources)]):
            choice, reason = r.index[0], "best in another recording"
        else:
            choice, reason = rest.index[0], "next best"
        picked.append(choice)
        why.append(reason)
        periods.add(work.at[choice, "period"])
        if src:
            sources.add(work.at[choice, src])
    return work.loc[picked].drop(columns="_s").assign(why=why)


def across_sites(group: pd.DataFrame, target: int, score: str = "score", site_col: str = "site",
                 period: str | None = "period") -> pd.DataFrame:
    """Up to target rows for one species: one per site first (busiest sites first), the rest in
    proportion to what each site has; each site's rows spread over the score range and over time."""
    if target <= 0 or group.empty:
        return group.iloc[0:0]
    target = min(target, len(group))
    counts = group[site_col].astype(str).value_counts()
    alloc = {s: 0 for s in counts.index}
    left = target
    for s in counts.index:
        if left <= 0:
            break
        alloc[s] = 1
        left -= 1
    if left > 0:
        for s, n in proportional((counts - pd.Series(alloc)).clip(lower=0), left).items():
            alloc[s] += n
    parts = [spread(group[group[site_col].astype(str) == s], n, score, period) for s, n in alloc.items() if n > 0]
    return pd.concat(parts).head(target) if parts else group.iloc[0:0]


# ------------------------------------------------------------------ countries (one species model each)
def model_groups(df: pd.DataFrame, country: str | None = None, settings=None) -> pd.DataFrame:
    """Adds 'country' and 'model_group' (the country's species model: countries sharing one, e.g. Kenya
    and Uganda, go together). Country is --country when given (for every row); otherwise the results'
    country, bucket or country folder. If --country disagrees with the results, stop rather than mix."""
    from .. import countries as K
    try:
        table = K.load(settings) if settings is not None else pd.DataFrame()
    except (Exception, SystemExit):  # noqa: BLE001 - no country table installed: use the names as they are
        table = pd.DataFrame()
    by = {}
    for r in table.to_dict("records"):
        for k in (r.get("country_name"), r.get("country_folder"), r.get("bucket_code")):
            if k and str(k) != "nan":
                by[str(k).lower()] = (r.get("country_name"), r.get("species_model") or r.get("country_name"))
    raw = pd.Series(pd.NA, index=df.index, dtype="string")
    for col in ("country", "bucket", "bucket_name", "country_folder"):
        if col in df.columns:
            raw = raw.fillna(df[col].astype("string").replace({"": pd.NA, "local": pd.NA, "None": pd.NA}))
    if country:
        want = by.get(str(country).lower(), (country, country))[0]
        said = {by.get(str(c).lower(), (c, c))[0] for c in raw.dropna().unique()}
        if not by and len(said) == 1 and len(next(iter(said))) <= 4 and str(next(iter(said))).lower() != str(want).lower():
            print(f"NOTE: no country table to check that '{next(iter(said))}' is {want}: taking --country {want}.",
                  flush=True)
            said = set()        # one bucket code (e.g. 'sgp') can't be checked without the table: take --country
        if said - {want}:
            raise SystemExit(f"--country {country}, but some results are from {', '.join(sorted(map(str, said - {want})))}. "
                             f"Give results from one country at a time.")
        raw = pd.Series(country, index=df.index, dtype="string")
    if raw.isna().any():
        raise SystemExit("Model samples are made per country (each country has its own species model), but some "
                         "results don't say which country they're from. Give --country <country>.")
    out = df.copy()
    out["country"] = [by.get(str(c).lower(), (c, c))[0] for c in raw]
    out["model_group"] = [by.get(str(c).lower(), (c, c))[1] for c in raw]
    return out


# ------------------------------------------------------------------ the purposes
def species_table(paths: list[str] | None) -> pd.DataFrame | None:
    """Species a site should be checked for: CSVs with 'species' (and optionally 'site' and 'listed').
    A file named <site>_site_species.csv (from bird-results) gives the site from its name."""
    if not paths:
        return None
    parts = []
    for p in paths:
        t = pd.read_csv(p)
        if "site" not in t.columns:
            name = Path(p).name
            t["site"] = name[: -len("_site_species.csv")] if name.endswith("_site_species.csv") else None
        if "listed" in t.columns:
            t = t[t["listed"].astype(str).str.lower().isin(["true", "1", "yes"])]
        parts.append(t[["site", "species"]])
    return pd.concat(parts, ignore_index=True)


def _keep_listed(u: pd.DataFrame, table: pd.DataFrame | None) -> pd.DataFrame:
    if table is None:
        return u
    named = set(table["site"].dropna())
    if named and not named & set(u["site"]):
        print(f"NOTE: the species table names sites {', '.join(sorted(map(str, named)))}, which aren't in these "
              f"results (sites {', '.join(sorted(map(str, set(u['site']))))}): using it for every site.", flush=True)
        table = table.assign(site=None)
    any_site = set(table.loc[table["site"].isna(), "species"])
    pairs = set(zip(table["site"].dropna(), table.loc[table["site"].notna(), "species"]))
    ok = [sp in any_site or (st, sp) in pairs for st, sp in zip(u["site"], u["species"])]
    return u[ok]


def site_lists(units: pd.DataFrame, group: str, per_species: int | None = None, how: str | None = None,
               unusual_months: bool = True, noise: int | None = None, seed: int = 42,
               exclude: set | None = None, table: pd.DataFrame | None = None, reserve: int = 0) -> pd.DataFrame:
    g = GROUPS[group]
    n = g["site_per_species"] if per_species is None else per_species
    how = how or g["site_how"]
    pool = units[~units["unit_id"].isin(exclude or set())]
    moths, nz = pool[pool["noise_class"].isna()], pool[pool["noise_class"].notna()]
    rows = []
    for (_, _), d in _keep_listed(moths, table).groupby(["site", "species"], sort=True, observed=True):
        ch = best_then_others(d, n) if how == "best" else spread(d, n).assign(why="species check")
        rows.append(ch.assign(rank=range(1, len(ch) + 1), reserve=False))
        if reserve:
            rest = d[~d["unit_id"].isin(ch["unit_id"])]
            rv = best_then_others(rest, reserve) if how == "best" else spread(rest, reserve)
            rows.append(rv.assign(why="reserve", rank=range(len(ch) + 1, len(ch) + 1 + len(rv)), reserve=True))
    chosen = pd.concat(rows) if rows else moths.iloc[0:0]
    if unusual_months:
        odd = moths[moths["unlikely"].fillna(False).astype(bool) & ~moths["unit_id"].isin(chosen.get("unit_id", []))]
        odd = odd.sort_values("score", ascending=False).drop_duplicates(["site", "species"])
        chosen = pd.concat([chosen, odd.assign(why="outside its usual months", rank=n + 1, reserve=False)])
    k = g["noise"] if noise is None else noise
    rng = np.random.default_rng(seed)
    for _, d in nz.groupby("site", sort=True, observed=True):
        for o, m in proportional(d["noise_class"].astype(str).value_counts(), k).items():
            grp = d[d["noise_class"].astype(str) == o]
            pick = grp.loc[rng.choice(grp.index.to_numpy(), size=min(m, len(grp)), replace=False)]
            chosen = pd.concat([chosen, pick.assign(why=f"noise (not a moth: {o})", rank=None, reserve=False)])
    return finish(chosen, "site-lists", group)


def model(units: pd.DataFrame, group: str, per_species: int | None = None, exclude: set | None = None,
          country: str | None = None, settings=None, reserve: int = 0) -> pd.DataFrame:
    n = GROUPS[group]["model_per_species"] if per_species is None else per_species
    pool = units[~units["unit_id"].isin(exclude or set()) & units["noise_class"].isna()]
    if pool.empty:
        return finish(pool, "model", group)
    pool = model_groups(pool, country, settings)
    rows = []
    for _, d in pool.groupby(["model_group", "species"], sort=True, observed=True):              # never across countries
        ch = across_sites(d, n).drop_duplicates("unit_id")
        rows.append(ch.assign(why="model examples", rank=range(1, len(ch) + 1), reserve=False))
        if reserve:
            rv = across_sites(d[~d["unit_id"].isin(ch["unit_id"])], reserve).drop_duplicates("unit_id")
            rows.append(rv.assign(why="reserve", rank=range(len(ch) + 1, len(ch) + 1 + len(rv)), reserve=True))
    return finish(pd.concat(rows) if rows else pool.iloc[0:0], "model", group)


def everything(units: pd.DataFrame, group: str, exclude: set | None = None) -> pd.DataFrame:
    pool = units[~units["unit_id"].isin(exclude or set())]
    return finish(pool.assign(why="all", rank=None, reserve=False), "all", group)


# ------------------------------------------------------------------ writing
def excluded_units(paths: list[str] | None) -> set[str]:
    """unit_ids already chosen in earlier selections (any purpose)."""
    out: set[str] = set()
    for p in paths or []:
        out |= set(pd.read_csv(p, usecols=["unit_id"])["unit_id"].astype(str))
    return out


def finish(rows: pd.DataFrame, purpose: str, group: str) -> pd.DataFrame:
    rows = rows.copy().reset_index(drop=True)
    rows["purpose"], rows["group"] = purpose, group
    rows["selection_id"] = [f"{GROUPS[group]['prefix']}{i:05d}" for i in range(1, len(rows) + 1)]
    for c in COMMON_COLUMNS:
        if c not in rows.columns:
            rows[c] = None
    return rows[COMMON_COLUMNS + [c for c in rows.columns if c not in COMMON_COLUMNS and not c.startswith("_")]]


def write(sel: pd.DataFrame, out: Path, record: dict) -> tuple[Path, Path]:
    """<out>.csv: the selection (one row per unit to check); <out>_record.json: how it was chosen."""
    out = Path(out).with_suffix("")
    out.parent.mkdir(parents=True, exist_ok=True)
    sel.to_csv(f"{out}.csv", index=False)
    main = sel[~sel["reserve"].fillna(False).astype(bool)] if len(sel) else sel
    record = {"made_at": datetime.now(timezone.utc).isoformat(), "items": int(len(main)),
              "reserve_items": int(len(sel) - len(main)),
              "species": int(main["species"].nunique()) if len(main) else 0,
              "by_reason": main["why"].value_counts().to_dict() if len(main) else {}, **record}
    Path(f"{out}_record.json").write_text(json.dumps(record, indent=2, default=str))
    return Path(f"{out}.csv"), Path(f"{out}_record.json")
