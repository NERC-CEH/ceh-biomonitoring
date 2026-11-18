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


def latest(stage: str, region: str | None = None, models: dict | None = None) -> str:
    """The newest model (by release date) for a step, and for species, a region."""
    models = (models or model_list())["models"]
    hits = [(str(m.get("released", "")), n) for n, m in models.items()
            if m.get("stage") == stage and (region is None or m.get("region") == region)]
    if not hits:
        raise SystemExit(f"No {stage} model" + (f" for region '{region}'" if region else ""))
    return max(hits)[1]


def resolve(name: str, stage: str, models: dict | None = None) -> str:
    """'latest' (or empty) means the newest model for that step."""
    return latest(stage, models=models) if name in ("", "latest", None) else name


def species_model_for(region: str, models: dict | None = None) -> str:
    models = models or model_list()
    region = region.strip().lower().replace("_", "-").replace(" ", "-")
    regions = sorted({m["region"] for m in models["models"].values() if m.get("stage") == "species"})
    if region not in regions:
        raise SystemExit(f"No species model for region '{region}'. Regions: {', '.join(regions)}")
    return latest("species", region, models)


# ----------------------------------------------------------------------------- dates and nights


def image_datetime(key: str, device: dict | None = None, pattern: str | None = None) -> datetime | None:
    if device or pattern:
        from ... import devices
        dt = devices.parse_filename(key, device, pattern)["file_datetime"]
        if dt:
            return datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
    from ... import times                       # every layout the toolkit knows (AMI, AMI-mini, Mothbox ...)
    return times.from_name(Path(key).name)


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
        "detector": "latest",          # latest = the newest model for each step (cehbio models)
        "binary_model": "latest",
        "order_model": "latest",
        "order_input": "native",       # native = as the order model was trained (128 px, 0-1);
                                       # amber-300 = as amber-inferences did, to compare with old results
        "box_threshold": 0.2,          # detector score below this: not an insect
        "detector_score_threshold": None,  # flat-bug's own cut-off (its default 0.2); lower finds fainter insects
        "detector_min_size": None,     # smallest insect flat-bug reports, in pixels (its default 32)
        "enhance_contrast": False,     # boost contrast for detection only (pale insects on a white sheet)
        "detector_precision": "float32",  # float32 (best) or float16 (faster on a GPU, may miss faint insects)
        "max_crops_per_image": 100,    # keep the best boxes per photo (the rest are counted)
        "top_n": 5,                    # species guesses per crop
        "species_list": "",            # CSV with a 'species' column: guesses only from these species
        "species_list_unlikely": "flag",  # species marked unlikely that month: flag (top guess) | remove
        "mask": "",                    # black-and-white image: black = ignore (see cehbio mask)
        "mask_overlap": 0.5,           # ignore a box when this much of it is in the black area
        "mask_site": "",               # for a masks.json with several sites: which one (default: by folder)
        "filters": "",                 # YAML file(s) of your own rules (see docs/images.md)
        "save_crops": False,           # also save each crop as a .jpg
        "save_outlines": False,        # each insect's outline + area, length, width (for biomass)
        "save_overlays": False,        # flat-bug's overlay image of each photo (outlines drawn on it)
        "pixels_per_mm": None,         # camera scale: also give outline sizes in mm / mm²
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
        ml = model_list()
        det_name = resolve(params.get("detector"), "detector", ml)
        bin_name = resolve(params.get("binary_model"), "binary", ml)
        ord_name = resolve(params.get("order_model"), "order", ml)
        species = params.get("species_model") or (species_model_for(params["region"], ml) if params.get("region") else "")
        key = (dev, det_name, bin_name, ord_name, species, params.get("detector_score_threshold"),
               params.get("detector_min_size"), params.get("detector_precision"))
        if self._loaded.get("key") == key:
            return self._loaded
        settings = Settings.load()
        get = lambda m, part: modelstore.fetch(settings, ml, m, part)  # noqa: E731
        print(f"Loading models on {dev}: {det_name}, {bin_name}, {ord_name}, {species or 'no species model'}",
              flush=True)
        loaded = {"key": key, "device": dev}
        fb_default = nets.flatbug_default_model()
        if fb_default not in {f["name"] for m in ml["models"].values() for f in m["files"].values()}:
            print(f"NOTE: the installed flat-bug offers a newer detector ({fb_default}) than this model list. "
                  f"Run `cehbio update` to get the newest model list.", flush=True)
        loaded["detector"] = nets.load_flatbug(get(det_name, "weights"), dev, params.get("detector_score_threshold"),
                                               params.get("detector_min_size"),
                                               params.get("detector_precision") or "float32")
        loaded["binary"], loaded["binary_labels"], loaded["binary_transform"] = nets.load_binary(
            get(bin_name, "weights"), get(bin_name, "labels"), dev, ml["models"][bin_name].get("kind", ""))
        loaded["order"], loaded["order_labels"], loaded["order_table"] = nets.load_order(
            get(ord_name, "weights"), get(ord_name, "labels"), dev)
        loaded["species"], loaded["species_labels"] = (
            nets.load_species(get(species, "weights"), get(species, "labels"), dev) if species else (None, []))
        loaded["provenance"] = {
            "detector": modelstore.describe(ml, det_name),
            "binary": modelstore.describe(ml, bin_name),
            "order": modelstore.describe(ml, ord_name),
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
        from . import nets, outline, tracking
        from ... import devices

        print(NOTICE, flush=True)
        M = self._models(params)
        dev, top_n = M["device"], int(params["top_n"])
        device_profile = devices.get(chunk["device"]) if chunk.get("device") else None
        pattern = chunk.get("timestamp_pattern")
        mask = F.load_mask(params.get("mask"), params["mask_overlap"], params.get("mask_site")
                           or chunk.get("deployment_id"))
        rules = F.load_rules(params.get("filters"))
        thr, cap, bs = float(params["box_threshold"]), int(params["max_crops_per_image"]), int(params["batch_size"])
        slist, list_masks = None, {}
        if params.get("species_list") and M["species"] is not None:
            from ...species_lists import SpeciesList, keep_unlikely, norm
            slist = SpeciesList(params["species_list"])
            with_unlikely = keep_unlikely(params)
            label_names = [norm(lab) for lab in M["species_labels"]]
            print(f"Species list: {slist.describe()}", flush=True)

        def list_mask(month):
            if slist is None:
                return None
            m = month if slist.monthly else None
            if m not in list_masks:
                wanted = slist.allowed(m, with_unlikely)
                list_masks[m] = np.array([lab in wanted for lab in label_names])
            return list_masks[m]
        crop_dir = workdir / "keep" / "crops"
        overlay_dir = workdir / "keep" / "overlays"
        if params.get("save_overlays"):
            overlay_dir.mkdir(parents=True, exist_ok=True)
        want_outlines, ppm = bool(params.get("save_outlines")), params.get("pixels_per_mm")
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
        if str(dev).startswith("cpu"):
            print("Detecting insects on the CPU: this can take a minute or more per photo.", flush=True)
        for n_done, (key, path) in enumerate(ordered, start=1):
            started = datetime.now()
            dt = image_datetime(key, device_profile, pattern)
            meta = {"source_key": key, "filename": Path(key).name, "image_path": key,
                    "image_datetime": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "",
                    "recording_session": recording_session(dt)}
            try:
                image = Image.open(path).convert("RGB")
                det_input = path
                if params.get("enhance_contrast"):
                    det_input = nets.enhance(path, Path(path).with_name("_enhanced_" + Path(path).name))
                overlay = overlay_dir / f"{Path(key).stem}_overlay.jpg" if params.get("save_overlays") else None
                try:
                    boxes = nets.detect_flatbug(M["detector"], det_input, overlay)
                except Exception as first:  # noqa: BLE001 - the detector is stricter than PIL: retry a clean copy
                    clean = Path(path).with_name("_resaved_" + Path(path).name)
                    image.save(clean, quality=95)
                    try:
                        boxes = nets.detect_flatbug(M["detector"], clean, overlay)
                        print(f"[note] {Path(key).name}: detector could not read it ({first}); used a re-saved copy")
                    finally:
                        clean.unlink(missing_ok=True)
                if det_input != path:
                    Path(det_input).unlink(missing_ok=True)
                if n_done <= 5 or n_done % 50 == 0 or n_done == len(ordered):
                    secs = (datetime.now() - started).total_seconds()
                    print(f"  photo {n_done}/{len(ordered)}: {Path(key).name}, {len(boxes)} boxes ({secs:.0f} s)",
                          flush=True)
            except Exception as e:  # noqa: BLE001
                failed.append({**{k: meta[k] for k in ("source_key", "filename", "image_datetime")},
                               "status": "failed", "error": f"{type(e).__name__}: {e}"})
                previous, previous_name = [], None
                continue
            W, H = image.size
            blur = float(cv2.Laplacian(np.array(image), cv2.CV_64F).var())

            # 1-3: threshold, mask, detection-stage filters, cap
            photo_mask = mask.for_photo(key) if isinstance(mask, F.SiteMasks) else mask
            kept, n_masked, n_removed = [], 0, 0
            for i, (x0, y0, x1, y1, score, label, poly) in enumerate(boxes):
                if score < thr:
                    continue
                crop = {"crop_status": f"crop_{i + 1}", "x_min": x0, "y_min": y0, "x_max": x1, "y_max": y1,
                        "box_score": score, "box_label": label, "filename": meta["filename"]}
                if want_outlines:
                    crop.update(outline.columns(poly, ppm) if poly else {})
                if photo_mask is not None and photo_mask.ignored((x0, y0, x1, y1), W, H):
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
                btf = M["binary_transform"]
                bin_tensors = torch.stack([btf(p) for p in pil_crops]) if btf else tensors
                ord_tensors = (tensors if params.get("order_input") == "amber-300"
                               else torch.stack([nets.order_transform(p) for p in pil_crops]))
                for s in range(0, len(kept), bs):
                    batch = tensors[s:s + bs].to(dev)
                    pb = nets.classify(M["binary"], bin_tensors[s:s + bs].to(dev))
                    po = nets.order_scores(M["order"], ord_tensors[s:s + bs].to(dev), M["order_table"])
                    for j in range(len(batch)):
                        c = kept[s + j]
                        c["class_name"] = M["binary_labels"][int(pb[j].argmax())]
                        c["class_confidence"] = float(pb[j].max())
                        c.update(po[j])
                    if M["species"] is not None:
                        want = [j for j in range(len(batch)) if kept[s + j]["class_name"] == "moth"
                                or "Lepidoptera" in kept[s + j]["order_name"]]
                        if want:
                            probs, emb = nets.species_scores(M["species"], batch[want])
                            for w_i, j in enumerate(want):
                                allowed = list_mask(dt.month if dt else None)
                                ranked = np.where(allowed, probs[w_i], -1.0) if allowed is not None else probs[w_i]
                                top = ranked.argsort()[-top_n:][::-1]
                                kept[s + j]["_species"] = ([M["species_labels"][t] for t in top]
                                                           + [float(probs[w_i][t]) for t in top])
                                kept[s + j]["_embedding"] = emb[w_i]
                for c, pc in zip(kept, pil_crops):
                    names = c.pop("filters")
                    sp = c.pop("_species", [None] * top_n * 2)     # not a moth: no species guesses
                    c.update(dict(zip(species_cols, sp)))
                    if slist is not None:
                        c["rank_1_unlikely_this_month"] = bool(sp[0]) and norm(sp[0]) in slist.unlikely(
                            dt.month if dt else None)
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
                 "order_confidence", "order_score", "order_sure"] + species_cols + tracking.MATCH_COLUMNS
                + ["filters", "n_boxes_detected", "n_boxes_masked", "n_boxes_removed_by_filters", "n_boxes_over_cap"]
                + (["outline_area_px", "outline_length_px", "outline_width_px"]
                   + (["outline_area_mm2", "outline_length_mm", "outline_width_mm"] if ppm else []) + ["outline"]
                   if want_outlines else []))
        det = pd.DataFrame(rows, columns=cols)
        prov = {**M["provenance"], "box_threshold": thr, "max_crops_per_image": cap,
                "detector_settings": {k: params.get(k) for k in ("detector_score_threshold", "detector_min_size",
                                                                  "enhance_contrast", "detector_precision")},
                "order_input": params.get("order_input"),
                "species_list": params.get("species_list") or None,
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
