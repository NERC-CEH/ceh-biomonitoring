"""Images: moths and other insects in light-trap photos (AMI traps, LepiSense / AMI-mini).

THE MODELS ARE STILL IN DEVELOPMENT AND FAR FROM PERFECT. Treat every result as a suggestion and have
identifications checked by an expert before relying on them.

For each photo, in time order through each night:
  1. find insects            flat-bug detector; boxes below box_threshold are left out
  2. ignore known clutter    mask (e.g. a ring light) and your own filters (e.g. geckos)
  3. keep the best boxes     at most max_crops_per_image, by detector score (the rest are counted)
  4. moth or not             moth-vs-nonmoth-v1
  5. which order             insect-order-v1 (16 groups, e.g. Lepidoptera Macros, Coleoptera)
  6. which species           the region's species model, for moths / Lepidoptera only (top_n guesses)
  7. tracking                each crop's best match in the previous photo; joined into tracks when
                             everything is combined (<deployment>_analysis_ready / _tracks)

The processing follows amber-inferences (AMI-system, MIT licence), so results match earlier UKCEH outputs.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

from ..base import ChunkResult, Pipeline, require

MODEL_LIST = Path(__file__).with_name("models.yml")
NOTICE = ("NOTE: the image models are still in development and far from perfect. Treat results as "
          "suggestions and have identifications checked by an expert.")


def model_list() -> dict:
    from ...modelstore import load_list
    return load_list(MODEL_LIST)


def species_model_for(region: str, models: dict | None = None) -> str:
    models = (models or model_list())["models"]
    region = region.strip().lower().replace("_", "-").replace(" ", "-")
    hits = [n for n, m in models.items() if m.get("stage") == "species" and m.get("region") == region]
    if not hits:
        regions = sorted({m["region"] for m in models.values() if m.get("stage") == "species"})
        raise SystemExit(f"No species model for region '{region}'. Regions: {', '.join(regions)}")
    return sorted(hits)[-1]


# ----------------------------------------------------------------------------- dates and nights
_AMI_MINI = re.compile(r"(20\d{6})T(\d{6})")
_PLAIN = re.compile(r"(20\d{12})")


def image_datetime(key: str, device: dict | None = None, pattern: str | None = None) -> datetime | None:
    if device or pattern:
        from ... import devices
        dt = devices.parse_filename(key, device, pattern)["file_datetime"]
        if dt:
            return datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
    name = Path(key).name
    m = _AMI_MINI.search(name)
    s = m.group(1) + m.group(2) if m else (_PLAIN.search(name).group(1) if _PLAIN.search(name) else None)
    try:
        return datetime.strptime(s, "%Y%m%d%H%M%S") if s else None
    except ValueError:
        return None


def recording_session(dt: datetime | None) -> str:
    """The night a photo belongs to: photos before noon count as the previous night."""
    if dt is None:
        return ""
    return (dt - timedelta(days=1) if dt.time() < time(12, 0) else dt).strftime("%Y-%m-%d")


# ----------------------------------------------------------------------------- the pipeline
class Images(Pipeline):
    name = "images"
    title = "Moths and other insects in light-trap images (AMI, LepiSense)"
    extra = "images"
    data_type = "snapshot_images"
    extensions = (".jpg", ".jpeg")
    key_field = "image_keys"
    media = ("images",)
    needs_gpu = True
    files_per_chunk = 3000
    defaults = {
        "region": "",                  # species model for this region, e.g. uk, thailand (cehbio models)
        "species_model": "",           # or name a species model exactly
        "detector": "insect-detector-flatbug-m",
        "binary_model": "moth-vs-nonmoth-v1",
        "order_model": "insect-order-v1",
        "box_threshold": 0.2,          # detector score below this: not an insect
        "max_crops_per_image": 100,    # keep the best boxes per photo (the rest are counted)
        "top_n": 5,                    # species guesses per crop
        "mask": "",                    # black-and-white image: black = ignore (see cehbio mask)
        "mask_overlap": 0.5,           # ignore a box when this much of it is in the black area
        "filters": "",                 # YAML file(s) of your own rules (see docs/images.md)
        "save_crops": False,           # also save each crop as a .jpg
        "track_cost_threshold": 1.0,   # link crops between photos at or below this cost
        "batch_size": 64,
        "device": "auto",              # auto | cuda | cpu
        "deployment_name": "", "lat": None, "lon": None,
    }

    def check_installed(self) -> None:
        for mod in ("torch", "torchvision", "timm", "flat_bug", "PIL", "cv2"):
            require(mod, self.extra)

    # ---------------------------------------------------------------- chunking by night
    def group_files(self, keys, device=None, timestamp_pattern=None):
        nights: dict[str, list[tuple]] = {}
        for k in keys:
            dt = image_datetime(k, device, timestamp_pattern)
            nights.setdefault(recording_session(dt) or "~undated", []).append((dt or datetime.max, Path(k).name, k))
        return [[k for *_, k in sorted(v)] for _, v in sorted(nights.items())]

    # ---------------------------------------------------------------- models
    _loaded: dict = {}

    def _models(self, params: dict):
        import torch
        from ... import modelstore
        from ...settings import Settings
        from . import nets

        dev = params.get("device", "auto")
        dev = ("cuda" if torch.cuda.is_available() else "cpu") if dev == "auto" else dev
        if dev == "cuda":
            dev = "cuda:0"      # flat-bug compares device names exactly
        species = params.get("species_model") or (species_model_for(params["region"]) if params.get("region") else "")
        key = (dev, params["detector"], params["binary_model"], params["order_model"], species)
        if self._loaded.get("key") == key:
            return self._loaded
        settings, ml = Settings.load(), model_list()
        get = lambda m, part: modelstore.fetch(settings, ml, m, part)  # noqa: E731
        print(f"Loading models on {dev} ...", flush=True)
        loaded = {"key": key, "device": dev}
        loaded["detector"] = nets.load_flatbug(get(params["detector"], "weights"), dev)
        loaded["binary"], loaded["binary_labels"] = nets.load_binary(get(params["binary_model"], "weights"),
                                                                      get(params["binary_model"], "labels"), dev)
        loaded["order"], loaded["order_labels"] = nets.load_order(get(params["order_model"], "weights"),
                                                                   get(params["order_model"], "labels"), dev)
        loaded["species"], loaded["species_labels"] = (
            nets.load_species(get(species, "weights"), get(species, "labels"), dev) if species else (None, []))
        loaded["provenance"] = {
            "detector": modelstore.describe(ml, params["detector"]),
            "binary": modelstore.describe(ml, params["binary_model"]),
            "order": modelstore.describe(ml, params["order_model"]),
            "species": modelstore.describe(ml, species) if species else None,
            "device": dev,
        }
        if not species:
            print("No species model chosen (--set region=uk, thailand, ...): species columns will be empty.")
        Images._loaded = loaded
        return loaded

    # ---------------------------------------------------------------- one chunk
    def process(self, files, chunk, params, workdir):
        import cv2
        import numpy as np
        import torch
        from PIL import Image

        from . import filters as F
        from . import nets, tracking
        from ... import devices

        print(NOTICE, flush=True)
        M = self._models(params)
        dev, top_n = M["device"], int(params["top_n"])
        device_profile = devices.get(chunk["device"]) if chunk.get("device") else None
        pattern = chunk.get("timestamp_pattern")
        mask = F.Mask(params["mask"], params["mask_overlap"]) if params.get("mask") else None
        rules = F.load_rules(params.get("filters"))
        thr, cap, bs = float(params["box_threshold"]), int(params["max_crops_per_image"]), int(params["batch_size"])
        crop_dir = workdir / "keep" / "crops"
        species_cols = ([f"regional_species_rank_{i + 1}_name" for i in range(top_n)]
                        + [f"regional_species_rank_{i + 1}_confidence" for i in range(top_n)])
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fixed = {"bucket_name": chunk.get("bucket_code", ""), "deployment_name": params.get("deployment_name") or "",
                 "deployment_id": chunk.get("deployment_id", ""), "latitude": params.get("lat"),
                 "longitude": params.get("lon"), "analysis_datetime": now}

        ordered = sorted(files, key=lambda kp: (image_datetime(kp[0], device_profile, pattern) or datetime.max,
                                                Path(kp[0]).name))
        rows, none, failed = [], [], []
        previous, previous_name = [], None
        for key, path in ordered:
            dt = image_datetime(key, device_profile, pattern)
            meta = {"source_key": key, "filename": Path(key).name, "image_path": key,
                    "image_datetime": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "",
                    "recording_session": recording_session(dt)}
            try:
                image = Image.open(path).convert("RGB")
                boxes = nets.detect_flatbug(M["detector"], path)
            except Exception as e:  # noqa: BLE001
                failed.append({**{k: meta[k] for k in ("source_key", "filename", "image_datetime")},
                               "status": "failed", "error": f"{type(e).__name__}: {e}"})
                previous, previous_name = [], None
                continue
            W, H = image.size
            blur = float(cv2.Laplacian(np.array(image), cv2.CV_64F).var())

            # 1-3: threshold, mask, detection-stage filters, cap
            kept, n_masked, n_removed = [], 0, 0
            for i, (x0, y0, x1, y1, score, label) in enumerate(boxes):
                if score < thr:
                    continue
                crop = {"crop_status": f"crop_{i + 1}", "x_min": x0, "y_min": y0, "x_max": x1, "y_max": y1,
                        "box_score": score, "box_label": label, "filename": meta["filename"]}
                if mask is not None and mask.ignored((x0, y0, x1, y1), W, H):
                    n_masked += 1
                    continue
                remove, names = F.apply(rules, "detection", crop, W, H)
                if remove:
                    n_removed += 1
                    continue
                crop["filters"] = names
                kept.append(crop)
            n_over = max(0, len(kept) - cap)
            if n_over:
                keep_idx = sorted(sorted(range(len(kept)), key=lambda j: -kept[j]["box_score"])[:cap])
                kept = [kept[j] for j in keep_idx]
            counts = {"n_boxes_detected": len(boxes), "n_boxes_masked": n_masked,
                      "n_boxes_removed_by_filters": n_removed, "n_boxes_over_cap": n_over}

            # 4-6: classify in batches
            current = []
            if kept:
                pil_crops = [image.crop((c["x_min"], c["y_min"], c["x_max"], c["y_max"])) for c in kept]
                tensors = torch.stack([nets.CROP_TRANSFORM(p) for p in pil_crops])
                for s in range(0, len(kept), bs):
                    batch = tensors[s:s + bs].to(dev)
                    pb, po = nets.classify(M["binary"], batch), nets.classify(M["order"], batch)
                    for j in range(len(batch)):
                        c = kept[s + j]
                        c["class_name"] = M["binary_labels"][int(pb[j].argmax())]
                        c["class_confidence"] = float(pb[j].max())
                        c["order_name"] = M["order_labels"][int(po[j].argmax())]
                        c["order_confidence"] = float(po[j].max())
                    if M["species"] is not None:
                        want = [j for j in range(len(batch)) if kept[s + j]["class_name"] == "moth"
                                or "Lepidoptera" in kept[s + j]["order_name"]]
                        if want:
                            probs, emb = nets.species_scores(M["species"], batch[want])
                            for w_i, j in enumerate(want):
                                top = probs[w_i].argsort()[-top_n:][::-1]
                                kept[s + j]["_species"] = ([M["species_labels"][t] for t in top]
                                                           + [float(probs[w_i][t]) for t in top])
                                kept[s + j]["_embedding"] = emb[w_i]
                for c, pc in zip(kept, pil_crops):
                    names = c.pop("filters")
                    sp = c.pop("_species", [None] * top_n * 2)     # not a moth: no species guesses
                    c.update(dict(zip(species_cols, sp)))
                    rm_o, n_o = F.apply(rules, "order", c, W, H)
                    rm_s, n_s = F.apply(rules, "species", c, W, H) if M["species"] is not None else (False, [])
                    if rm_o or rm_s:
                        counts["n_boxes_removed_by_filters"] += 1
                        continue
                    c["filters"] = ";".join(names + n_o + n_s)
                    c["crop_bluriness"] = float(cv2.Laplacian(np.array(pc), cv2.CV_64F).var())
                    c["crop_area"] = (c["x_max"] - c["x_min"]) * (c["y_max"] - c["y_min"])
                    c["cropped_image_path"] = ""
                    if params.get("save_crops"):
                        crop_dir.mkdir(parents=True, exist_ok=True)
                        out = crop_dir / f"{Path(key).stem}_{c['crop_status']}.jpg"
                        pc.save(out)
                        c["cropped_image_path"] = f"crops/{out.name}"
                    current.append(c)

            # 7: best match in the previous photo
            for_tracking = []
            for c in current:
                emb = c.pop("_embedding", None)
                box = [c["x_min"], c["y_min"], c["x_max"], c["y_max"]]
                me = {"embedding": emb, "box": box, "image_size": (W, H), "crop": c["crop_status"]} if emb is not None else None
                c.update(tracking.best_match(previous, previous_name, me, c["crop_status"]))
                if me is not None:
                    for_tracking.append(me)
                rows.append({**meta, **fixed, "image_bluriness": blur, **c, **counts})
            previous, previous_name = for_tracking, meta["filename"]
            if not current:
                none.append({"source_key": key, "filename": meta["filename"], "status": "no_detections",
                             "image_datetime": meta["image_datetime"], "recording_session": meta["recording_session"],
                             "image_bluriness": blur, **counts})

        cols = (["source_key", "filename", "image_path", "image_datetime", "bucket_name", "deployment_name",
                 "deployment_id", "latitude", "longitude", "analysis_datetime", "recording_session", "image_bluriness",
                 "crop_status", "crop_bluriness", "crop_area", "cropped_image_path", "box_score", "box_label",
                 "x_min", "y_min", "x_max", "y_max", "class_name", "class_confidence", "order_name",
                 "order_confidence"] + species_cols + tracking.MATCH_COLUMNS
                + ["filters", "n_boxes_detected", "n_boxes_masked", "n_boxes_removed_by_filters", "n_boxes_over_cap"])
        det = pd.DataFrame(rows, columns=cols)
        prov = {**M["provenance"], "box_threshold": thr, "max_crops_per_image": cap,
                "mask": getattr(mask, "path", None), "n_filters": len(rules), "notice": NOTICE}
        try:
            from importlib.metadata import version
            prov["packages"] = {p: version(p) for p in ("torch", "torchvision", "timm", "flat-bug")}
        except Exception:  # noqa: BLE001
            pass
        return ChunkResult(det, none, failed, prov)

    # ---------------------------------------------------------------- after combining: tracks
    def after_combine(self, ddir, deployment, detections, files, params):
        from .tracking import NO_DETECTION, build_tracks
        rows = detections.copy()
        if len(files) and "status" in files:
            empty = files[files["status"] == "no_detections"].copy()
            if len(empty):
                empty = empty.rename(columns={"source_key": "image_path"})
                empty["crop_status"] = NO_DETECTION
                keep = [c for c in empty.columns if c in rows.columns or c in ("image_path", "crop_status")]
                rows = pd.concat([rows, empty[keep]], ignore_index=True)
        if not len(rows):
            return {}
        ready, tracks = build_tracks(rows, float(params.get("track_cost_threshold", 1.0)))
        ready.to_parquet(ddir / f"{deployment}_analysis_ready.parquet", index=False)
        tracks.to_parquet(ddir / f"{deployment}_tracks.parquet", index=False)
        n_crops = int((ready["crop_status"] != NO_DETECTION).sum())
        return {"n_crops": n_crops, "n_tracks": int(len(tracks)),
                "n_single_image_tracks": int(tracks["is_single_image_track"].sum()) if len(tracks) else 0,
                "outputs": [f"{deployment}_analysis_ready.parquet", f"{deployment}_tracks.parquet"],
                "notice": NOTICE}
