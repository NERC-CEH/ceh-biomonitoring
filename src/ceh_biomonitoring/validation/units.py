"""Turning pipeline results into UNITS: the independent things an expert checks.

Two picks are never the same animal doing the same thing, because each group's results are first
grouped into units:

  birds    an EVENT: detections of one species in one recording, joined while the pause is <= 60 s
           (a run of calling; one bird singing with long gaps makes several events)
  bats     a PASS: calls of one species in one recording, joined while the pause is <= 1 s
           (a starting point: check it against your own recordings)
  images   a TRACK: one insect followed through consecutive photos; crops without a track count on
           their own. A track is represented by the crop nearest its median species score

Every unit gets the same columns, so the sampling rules (sampling.py) work the same for every group:
unit_id, site, period (day or night), when, species, score, unlikely (species list says unlikely that
month), noise_class (images: insects that aren't moths, by order), plus where to find it again
(recording and seconds, or photo and box).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

GROUPS = {
    #          unit name, joining gap, time unit, site-lists per species and how, model per species, noise
    "birds": {"unit": "event", "max_gap_s": 60.0, "period": "day", "site_per_species": 2, "site_how": "best",
              "model_per_species": 50, "noise": 0, "scores": ["logit", "confidence"], "prefix": "B",
              "data_type": "audible_recordings"},
    "bats": {"unit": "pass", "max_gap_s": 1.0, "period": "night", "site_per_species": 2, "site_how": "best",
             "model_per_species": 50, "noise": 0, "scores": ["class_probability", "detection_probability"],
             "prefix": "BAT", "data_type": "ultrasound_recordings"},
    "images": {"unit": "track", "period": "night", "site_per_species": 3, "site_how": "spread",
               "model_per_species": 100, "noise": 100, "prefix": "I", "data_type": "snapshot_images"},
}

UNIT_COLUMNS = ["unit_id", "group", "site", "deployment_id", "deployment_name", "country_folder", "bucket",
                "period", "when", "species", "score", "score_type", "unlikely", "noise_class"]

# old column names in earlier image results (the INSPIRE / AMBER outputs)
IMAGE_ALIASES = {"filepath": "image_path", "site_name": "deployment_name",
                 "top_species_prediction": "regional_species_rank_1_name",
                 "species_confidence": "regional_species_rank_1_confidence",
                 **{f"top_{i}_species": f"regional_species_rank_{i}_name" for i in range(2, 6)},
                 **{f"top_{i}_confidence": f"regional_species_rank_{i}_confidence" for i in range(2, 6)}}
SPECIES, SCORE = "regional_species_rank_1_name", "regional_species_rank_1_confidence"


def stable_id(*parts) -> str:
    """The same item gets the same id in every run."""
    return hashlib.sha256("|".join(str(p).strip() for p in parts).encode("utf-8")).hexdigest()[:20]


def detection_id(dep, image, x0, y0, x1, y1) -> str:
    """The labelling pipeline's crop id (det_ + sha256 of deployment, photo and box), so crops chosen in
    earlier Mothbot rounds are recognised."""
    key = "|".join([str(dep).strip(), str(image).strip(), str(float(x0)), str(float(y0)), str(float(x1)),
                    str(float(y1))])
    return "det_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def detection_ids(df: pd.DataFrame) -> list[str]:
    """detection_id for every row at once (the same ids, built column-wise: much faster on millions)."""
    key = df["deployment_id"].astype(str).str.strip() + "|" + df["image_path"].astype(str).str.strip()
    for c in ("x_min", "y_min", "x_max", "y_max"):
        key = key + "|" + df[c].astype(float).map(str)
    return ["det_" + hashlib.sha256(k.encode("utf-8")).hexdigest()[:20] for k in key]


# ------------------------------------------------------------------ reading results
def result_files(paths: list[str], group: str) -> list[Path]:
    """Result tables from files or folders (a deployment's results folder, or a folder of them)."""
    pats = (["*_analysis_ready.parquet", "*analysis_ready*.parquet", "*_detections.parquet", "*.csv"]
            if group == "images" else ["*_detections.parquet"])
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_file():
            out.append(p)
            continue
        if not p.is_dir():
            raise SystemExit(f"Not found: {p}")
        for pat in pats:
            found = sorted(p.glob(pat)) or sorted(p.glob(f"*/{pat}"))
            if found:
                out += found
                break
    if not out:
        raise SystemExit(f"No {group} results found in {', '.join(paths)}. Give the results folders "
                         f"(from `cehbio run`), or their .parquet files.")
    return list(dict.fromkeys(out))


# the columns units need (results can have dozens more; reading only these keeps memory down)
IMAGE_COLUMNS = {"image_path", "source_key", "image_datetime", "bucket_name", "deployment_name", "deployment_id",
                 "country_folder", "x_min", "y_min", "x_max", "y_max", "crop_area", "box_score", "class_name",
                 "class_confidence", "order_name", "order_confidence", SPECIES, SCORE, "track_id",
                 "rank_1_unlikely_this_month", "global_species_rank_1_backbone_family_name", "latitude", "longitude",
                 *IMAGE_ALIASES}


def read_file(f: Path, group: str) -> pd.DataFrame:
    if f.suffix == ".parquet":
        if group == "images":                      # only the columns needed, only rows with a box
            import pyarrow.compute as pc
            import pyarrow.dataset as ds
            data = ds.dataset(f, format="parquet")
            cols = [c for c in data.schema.names if c in IMAGE_COLUMNS]
            box = "x_min" if "x_min" in cols else None
            d = data.to_table(columns=cols, filter=pc.field(box).is_valid() if box else None).to_pandas()
        else:
            d = pd.read_parquet(f)
    else:
        d = pd.read_csv(f, low_memory=False,
                        usecols=(lambda c: c in IMAGE_COLUMNS) if group == "images" else None)
    if group == "images":
        d = d.rename(columns={k: v for k, v in IMAGE_ALIASES.items() if k in d.columns and v not in d.columns})
    return d.assign(results=str(f))


def read_results(paths: list[str], group: str) -> pd.DataFrame:
    return pd.concat([read_file(f, group) for f in result_files(paths, group)], ignore_index=True)


def _when_audio(det: pd.DataFrame) -> pd.Series:
    if "file_datetime" in det.columns and det["file_datetime"].notna().any():
        return pd.to_datetime(det["file_datetime"], errors="coerce")
    from ..species_lists import file_date
    keys = det["source_key"].astype(str)
    return pd.to_datetime(keys.map({k: file_date(k) for k in keys.unique()}), errors="coerce")


def period_of(when: pd.Series, kind: str) -> pd.Series:
    """The day, or the NIGHT (noon to noon, named by the evening it starts), when the time is known.
    Dates without a time stay as dates (a night can't be told from a date alone)."""
    when = pd.to_datetime(when, errors="coerce")
    if kind == "night" and (when.dropna().dt.time != pd.Timestamp(0).time()).any():
        return (when - pd.Timedelta(hours=12)).dt.date.astype(str).replace("NaT", "unknown")
    return when.dt.date.astype(str).replace("NaT", "unknown")


def _first(d: pd.DataFrame, col: str, default=None) -> pd.Series:
    return d[col] if col in d.columns else pd.Series(default, index=d.index)


# ------------------------------------------------------------------ audio: events and passes
def audio_units(det: pd.DataFrame, group: str, max_gap_s: float | None = None) -> pd.DataFrame:
    g = GROUPS[group]
    gap_s = g["max_gap_s"] if max_gap_s is None else max_gap_s
    score = next((c for c in g["scores"] if c in det.columns), None)
    if score is None:
        raise SystemExit(f"These {group} results have no score column ({' or '.join(g['scores'])}).")
    d = det.copy()
    d["species_name"] = d["species_name"].astype("string").str.strip()
    d = d[d["species_name"].notna() & d["species_name"].ne("")]
    if d.empty:
        return pd.DataFrame(columns=UNIT_COLUMNS)
    d[score] = pd.to_numeric(d[score], errors="coerce")
    d["when"] = _when_audio(d)
    d = d.sort_values(["source_key", "species_name", "start_time"])
    prev_end = d.groupby(["source_key", "species_name"])["end_time"].shift()
    d["unit"] = (prev_end.isna() | ((d["start_time"] - prev_end) > gap_s)).cumsum()
    peak = d.loc[d.groupby("unit")[score].idxmax(), ["unit", "start_time", "end_time"]].set_index("unit")
    u = d.groupby("unit", sort=False).agg(
        species=("species_name", "first"), source_key=("source_key", "first"), filename=("filename", "first"),
        when=("when", "first"), start_s=("start_time", "min"), end_s=("end_time", "max"),
        n_windows=("start_time", "size"), score=(score, "max"), results=("results", "first"))
    for col in ("deployment_id", "country_folder", "bucket_name", "common_name", "deployment_name"):
        if col in d.columns:
            u[col] = d.groupby("unit", sort=False)[col].first()
    u["unlikely"] = (d.groupby("unit", sort=False)["unlikely_this_month"].any()
                     if "unlikely_this_month" in d.columns else False)
    u["peak_s"] = peak["start_time"]
    u["window_s"] = peak["end_time"] - peak["start_time"]
    u["windows"] = d.groupby("unit", sort=False).apply(
        lambda x: json.dumps([[round(float(a), 3), round(float(b), 3)] for a, b in zip(x["start_time"], x[score])][:100]),
        include_groups=False)
    u = u.reset_index(drop=True)
    u["group"], u["score_type"], u["noise_class"] = group, score, None
    u["deployment_id"] = _first(u, "deployment_id", "").fillna("").astype(str)
    u["site"] = u["deployment_id"].where(u["deployment_id"].ne(""), u["results"].map(lambda r: Path(r).parent.name))
    u["bucket"] = _first(u, "bucket_name")
    u["period"] = period_of(u["when"], g["period"])
    u["unit_id"] = [stable_id(k, s, sp) for k, s, sp in zip(u["source_key"], u["start_s"], u["species"])]
    return _order(u)


# ------------------------------------------------------------------ images: tracks
def image_units(df: pd.DataFrame, per_crop: bool = False, min_crop_area: float | None = None,
                max_crop_area: float | None = None) -> pd.DataFrame:
    """Moth units (any crop with a species guess: top guess only) and noise units (not a moth, not
    Lepidoptera, no species guess, order known). per_crop: every crop is its own unit (labelling
    everything, as the labelling pipeline's all-crops mode)."""
    for c in ("x_min", "y_min", "x_max", "y_max", "crop_area", SCORE):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df[["x_min", "y_min", "x_max", "y_max"]].notna().all(axis=1)
            & (df["x_max"] > df["x_min"]) & (df["y_max"] > df["y_min"])]
    if "crop_area" not in df.columns:
        df["crop_area"] = (df["x_max"] - df["x_min"]) * (df["y_max"] - df["y_min"])
    if min_crop_area is not None:
        df = df[df["crop_area"] >= min_crop_area]
    if max_crop_area is not None:
        df = df[df["crop_area"] <= max_crop_area]
    if df.empty:
        return pd.DataFrame(columns=UNIT_COLUMNS)
    sp = _first(df, SPECIES, "").astype("string").fillna("").str.strip()
    order = _first(df, "order_name", "").astype("string").fillna("").str.strip()
    moth = _first(df, "class_name", "").astype("string").fillna("").str.lower().eq("moth")
    lep = order.str.contains("lepidoptera", case=False)
    is_noise = ~moth & ~lep & sp.eq("") & order.ne("")
    keep = sp.ne("") | is_noise                      # ids only for crops that can be chosen (saves memory)
    df, sp, order, is_noise = df[keep].copy(), sp[keep], order[keep], is_noise[keep]
    if "image_path" not in df.columns:
        df["image_path"] = df["source_key"]
    df["deployment_id"] = _first(df, "deployment_id", "").fillna("").astype(str)
    df["detection_id"] = detection_ids(df)
    track = _first(df, "track_id", "").astype("string").fillna("").str.strip()
    df["unit_id"] = (df["detection_id"] if per_crop else
                     np.where(track.ne(""), df["deployment_id"] + "::" + track, df["detection_id"]))
    cand = df[sp.ne("")].assign(species=sp[sp.ne("")], noise_class=None)
    noise = df[is_noise]
    noise = noise.assign(noise_class=order[noise.index], species="not a moth: " + order[noise.index])
    if len(cand) and not per_crop:
        s = cand[SCORE]
        dist = (s - s.groupby([cand["species"], cand["unit_id"]], observed=True).transform("median")).abs().fillna(np.inf)
        cand = (cand.assign(_d=dist).sort_values(["species", "unit_id", "_d"])
                .drop_duplicates(["species", "unit_id"]).drop(columns="_d"))
    if not per_crop:
        noise = noise.drop_duplicates("unit_id")
    u = pd.concat([cand, noise], ignore_index=True)
    u["group"], u["score"], u["score_type"] = "images", u.get(SCORE), SCORE
    u["unlikely"] = _first(u, "rank_1_unlikely_this_month", False).fillna(False).astype(bool)
    u["when"] = pd.to_datetime(_first(u, "image_datetime"), errors="coerce")
    u["period"] = period_of(u["when"], "night")
    u["site"] = u["deployment_id"]
    u["bucket"] = _first(u, "bucket_name")
    return _order(u)


# columns whose values repeat a lot: stored as categories, which keeps millions of units small
# (not photo paths or times: nearly every value differs, and huge category lists slow every join down)
CATEGORY_COLUMNS = {"group", "site", "deployment_id", "deployment_name", "country_folder", "bucket", "bucket_name",
                    "period", "species", "score_type", "noise_class", "results", "class_name", "order_name",
                    "common_name", "global_species_rank_1_backbone_family_name"}


def _order(u: pd.DataFrame) -> pd.DataFrame:
    for c in UNIT_COLUMNS:
        if c not in u.columns:
            u[c] = None
    u = u[UNIT_COLUMNS + [c for c in u.columns if c not in UNIT_COLUMNS]].reset_index(drop=True)
    for c in CATEGORY_COLUMNS & set(u.columns):
        u[c] = u[c].astype("category")
    return u


def concat_units(parts: list[pd.DataFrame]) -> pd.DataFrame:
    """Join units from several files, keeping category columns as categories (a plain concat would turn
    them back into text, using several times the memory)."""
    from pandas.api.types import union_categoricals
    parts = [p for p in parts if len(p)]
    if not parts:
        return pd.DataFrame(columns=UNIT_COLUMNS)
    cols = list(dict.fromkeys(c for p in parts for c in p.columns))
    out = {}
    for c in cols:
        series = [p[c] if c in p.columns else pd.Series(pd.Categorical([None] * len(p)) if c in CATEGORY_COLUMNS
                                                        else [None] * len(p)) for p in parts]
        if all(isinstance(x.dtype, pd.CategoricalDtype) for x in series):
            out[c] = pd.Series(union_categoricals(series, ignore_order=True))
        else:
            out[c] = pd.concat([x.reset_index(drop=True) for x in series], ignore_index=True)
    return pd.DataFrame(out)


def load(paths: list[str], group: str, max_gap_s: float | None = None, per_crop: bool = False,
         min_crop_area: float | None = None, max_crop_area: float | None = None) -> pd.DataFrame:
    """Units from one or more results folders or files, any number of deployments."""
    if group not in GROUPS:
        raise SystemExit(f"Unknown group '{group}'. Choose from: {', '.join(GROUPS)}")
    parts = []
    files = result_files(paths, group)
    for i, f in enumerate(files, 1):                  # one file (deployment) at a time keeps memory down
        df = read_file(f, group)
        parts.append(image_units(df, per_crop, min_crop_area, max_crop_area) if group == "images"
                     else audio_units(df, group, max_gap_s))
        if len(files) > 1:
            print(f"  {i}/{len(files)} {f.name}: {len(parts[-1])} units", flush=True)
    return concat_units(parts)
