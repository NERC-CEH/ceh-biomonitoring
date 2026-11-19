"""The results in EntoInsights' format (https://github.com/AMI-system/EntoInsights), so its R functions
(wrangle_results, plot_device_operation_calendar, get_top_species_*, plot_moths_vs_nonmoths, ...) work
on the toolkit's results without changes.

  images  <deployment>_combined_results.csv: one row per crop (and per photo with nothing found), with
          image_path, deployment_name, latitude, longitude, image_datetime, recording_session,
          top_1_species ... top_5_species and their confidences, class_name/confidence, order_name/confidence,
          crop_status and track_id.
          In R: EntoInsights::wrangle_results("<that file>", taxa = "moth")
  birds   <deployment>_birdnet_results.csv (BirdNET results only, as EntoInsights reads), with path,
          filename, site, lat, lon, scientific_name, common_name, confidence, start_time, end_time.
          In R: EntoInsights::wrangle_results("<that file>", taxa = "bird", source = "birdnet",
                filepath_colname = "path", sitename_colname = "site", latitude_colname = "lat",
                longitude_colname = "lon", topspeciespred_colname = "scientific_name",
                speciesconf_colname = "confidence")
          EntoInsights reads the date from the first 15 characters of the file name (YYYYMMDD_HHMMSS, as
          AudioMoth names files), so other recorders' names won't give dates there.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def export(run_root: Path, dep: str, pipeline: str, site: dict, out: Path) -> Path | None:
    out.mkdir(parents=True, exist_ok=True)
    if pipeline == "images":
        f = run_root / f"{dep}_analysis_ready.parquet"
        if not f.exists():
            f = run_root / f"{dep}_detections.parquet"
        if not f.exists():
            return None
        d = pd.read_parquet(f)
        ren = {}
        for i in range(1, 6):
            ren[f"regional_species_rank_{i}_name"] = f"top_{i}_species"
            ren[f"regional_species_rank_{i}_confidence"] = f"top_{i}_confidence"
        d = d.rename(columns={k: v for k, v in ren.items() if k in d.columns})
        for c in ("top_1_species", "top_1_confidence"):
            if c not in d.columns:
                d[c] = None
        # every row needs its deployment (photos with nothing found had none): EntoInsights counts nights
        # per deployment, so a blank one counts those nights twice
        dep_id = d["deployment_id"] if "deployment_id" in d.columns else pd.Series(None, index=d.index)
        d["deployment_id"] = dep_id.where(dep_id.notna() & dep_id.astype(str).str.strip().ne(""), dep)
        name = d["deployment_name"] if "deployment_name" in d.columns else pd.Series("", index=d.index)
        d["deployment_name"] = name.where(name.astype(str).str.strip().ne("") & name.notna(), dep)
        for c in ("latitude", "longitude"):
            if c not in d.columns or d[c].isna().all():
                d[c] = site.get(c)
        if "image_path" not in d.columns:
            d["image_path"] = d.get("source_key")
        d["image_datetime"] = pd.to_datetime(d.get("image_datetime"), errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
        if "recording_session" not in d.columns or d["recording_session"].isna().all():
            t = pd.to_datetime(d["image_datetime"], errors="coerce")
            d["recording_session"] = (t - pd.Timedelta(hours=12)).dt.strftime("%Y-%m-%d")
        keep = [c for c in d.columns if c not in ("outline",)]
        p = out / f"{dep}_combined_results.csv"
        d[keep].to_csv(p, index=False)
        return p
    if pipeline == "birds":
        f = run_root / f"{dep}_detections.parquet"
        if not f.exists():
            return None
        d = pd.read_parquet(f)
        if "confidence" not in d.columns:                       # Perch gives logits: EntoInsights reads BirdNET only
            return None
        b = pd.DataFrame({"path": d["source_key"], "filename": d["filename"], "site": dep,
                          "lat": site.get("latitude"), "lon": site.get("longitude"),
                          "scientific_name": d["species_name"], "common_name": d.get("common_name"),
                          "confidence": d["confidence"], "start_time": d["start_time"], "end_time": d["end_time"]})
        p = out / f"{dep}_birdnet_results.csv"
        b.to_csv(p, index=False)
        return p
    return None
