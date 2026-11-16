"""Tracking: linking the same insect across consecutive images of a night.

Each crop is compared with every crop in the previous image on four equally weighted costs
(appearance, overlap, size and distance). The cheapest is its best match. A whole deployment is then
walked in time order and a crop joins its best match's track if the total cost is at or below the
threshold (default 1), otherwise it starts a new track.

Ported from amber-inferences (AMI-system, MIT licence) and the UKCEH post-processing script, so the
numbers match earlier outputs. No PyTorch needed.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

NO_DETECTION = "No detections for this image."
NO_EMBEDDING = "No embedding found for crop_status '{crop}'. Tracking not possible."
NO_PREVIOUS = "No species crops from previous image. Tracking not possible."
COST_ERROR = "Error performing similarity calculations. Tracking not possible."
MATCH_COLUMNS = ["previous_image", "best_match_crop", "cnn_cost", "iou_cost", "box_ratio_cost",
                 "dist_ratio_cost", "total_cost"]


def iou(b1, b2) -> float:
    a1 = (b1[2] - b1[0] + 1) * (b1[3] - b1[1] + 1)
    a2 = (b2[2] - b2[0] + 1) * (b2[3] - b2[1] + 1)
    w = max(0, min(b1[2], b2[2]) - max(b1[0], b2[0]) + 1)
    h = max(0, min(b1[3], b2[3]) - max(b1[1], b2[1]) + 1)
    inter = w * h
    return float(np.around(inter / (a1 + a2 - inter), 2))


def box_ratio(b1, b2) -> float:
    a1 = (b1[2] - b1[0] + 1) * (b1[3] - b1[1] + 1)
    a2 = (b2[2] - b2[0] + 1) * (b2[3] - b2[1] + 1)
    return min(a1, a2) / max(a1, a2)


def distance_ratio(b1, b2, diag: float) -> float:
    c1 = (b1[0] + (b1[2] - b1[0]) / 2, b1[1] + (b1[3] - b1[1]) / 2)
    c2 = (b2[0] + (b2[2] - b2[0]) / 2, b2[1] + (b2[3] - b2[1]) / 2)
    return math.dist(c1, c2) / diag


def cosine(e1, e2) -> float:
    n1, n2 = np.linalg.norm(e1), np.linalg.norm(e2)
    if n1 == 0 or n2 == 0:
        return 0.0
    return float(np.dot(e1, e2) / (n1 * n2))


def cost(prev: dict, cur: dict) -> dict:
    """prev/cur: {'embedding', 'box': [x0, y0, x1, y1], 'image_size': (w, h)}"""
    b1, b2 = prev["box"], cur["box"]
    w, h = prev["image_size"]
    c = {"cnn_cost": 1 - cosine(prev["embedding"], cur["embedding"]),
         "iou_cost": 1 - iou(b1, b2),
         "box_ratio_cost": 1 - box_ratio(b1, b2),
         "dist_ratio_cost": distance_ratio(b1, b2, math.hypot(w, h))}
    c["total_cost"] = sum(c.values())
    return c


def best_match(previous: list[dict], previous_image: str | None, crop: dict | None, crop_name: str) -> dict:
    """The cheapest crop in the previous image for one crop (or why there is none)."""
    empty = {k: None for k in MATCH_COLUMNS}
    if crop is None:                                     # not a moth: no embedding
        return {**empty, "best_match_crop": NO_EMBEDDING.format(crop=crop_name)}
    if not previous:
        return {**empty, "best_match_crop": NO_PREVIOUS}
    best = None
    for p in previous:
        try:
            c = cost(p, crop)
        except Exception:  # noqa: BLE001 - malformed box: skip this pairing
            continue
        if best is None or c["total_cost"] < best[1]["total_cost"]:
            best = (p, c)
    if best is None:
        return {**empty, "best_match_crop": COST_ERROR}
    return {"previous_image": previous_image, "best_match_crop": best[0]["crop"], **best[1]}


def build_tracks(df: pd.DataFrame, cost_threshold: float = 1.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Give every crop a track_id. Returns (analysis_ready rows, one row per track)."""
    df = df.copy()
    for col in ("previous_image", "best_match_crop", "total_cost"):
        if col not in df:
            df[col] = pd.NA
    df["image_datetime"] = pd.to_datetime(df["image_datetime"], errors="coerce")
    df["total_cost"] = pd.to_numeric(df["total_cost"], errors="coerce")
    df["crop_status"] = df["crop_status"].fillna("").astype(str)
    df = df.sort_values(["image_datetime", "image_path", "crop_status"], kind="mergesort").reset_index(drop=True)

    track_ids, decisions = [], []
    lookup: dict[tuple[str, str], str] = {}
    counter = 0
    for image_path, crop, prev, prev_crop, total in zip(df["image_path"], df["crop_status"], df["previous_image"],
                                                         df["best_match_crop"], df["total_cost"]):
        if crop == NO_DETECTION:
            track_ids.append(pd.NA)
            decisions.append("no_detection")
            continue
        if pd.notna(prev) and pd.notna(prev_crop) and pd.notna(total) and float(total) <= cost_threshold:
            key = (Path(str(prev)).name, prev_crop)
            if key in lookup:
                tid, decision = lookup[key], "linked_to_previous_track"
            else:
                tid, decision = f"Track_{counter:06d}", "linked_previous_missing_created_track"
                counter += 1
                lookup[key] = tid
        else:
            tid = f"Track_{counter:06d}"
            counter += 1
            decision = "new_track_missing_tracking" if pd.isna(total) else "new_track_cost_above_threshold"
        track_ids.append(tid)
        decisions.append(decision)
        lookup[(Path(str(image_path)).name, crop)] = tid
    df["track_id"], df["tracking_decision"] = track_ids, decisions

    det = df[df["crop_status"] != NO_DETECTION]
    for col in ("class_name", "order_name", "regional_species_rank_1_name"):
        if col not in det:
            det = det.assign(**{col: pd.NA})
    tracks = (det.sort_values(["track_id", "image_datetime"])
              .groupby("track_id", as_index=False)
              .agg(track_start_datetime=("image_datetime", "min"),
                   track_end_datetime=("image_datetime", "max"),
                   track_length_images=("image_path", "nunique"),
                   n_detection_rows=("image_path", "size"),
                   representative_image_path=("image_path", "first"),
                   representative_crop_status=("crop_status", "first"),
                   binary_class=("class_name", "first"),
                   order_name=("order_name", "first"),
                   regional_species_rank_1_name=("regional_species_rank_1_name", "first"),
                   mean_total_cost=("total_cost", "mean")))
    tracks["track_duration_minutes"] = (tracks["track_end_datetime"]
                                       - tracks["track_start_datetime"]).dt.total_seconds() / 60
    tracks["is_single_image_track"] = tracks["track_length_images"] == 1
    return df, tracks
