"""Mothbot: packages for the Mothbot labelling site (https://mothbot-classify.vercel.app), in its
"Mothbox Next" format (version 3). Moved here from the UKCEH expert-labelling pipeline (2026).

Each package is one labelling round:

  <out>/<deployment>/<YYYY-MM-DD>_<purpose>.zip        (one per deployment; --one-package for one in all)
     dataset.json              the manifest: deployment > night hierarchy
     01_patches/<id>.jpg       a crop per selected detection, cut from the original photo with the
                               detector's box (no re-detection; the photo itself isn't included)
     02_records/               patches, patch-sources (photo, box, size), deployments, camera-days (nights)
     03_classifications/       _bot.ndjson: the models' identifications, ONLY with --no-blind (one row per
                               model per crop, in Mothbot's machine-ID format, so the expert can switch
                               between models); experts' answers are saved here as <their initials>.ndjson
     species/SpeciesList_<country>_<taxon>-GBIF-backbone-<date>.csv
                               the species list the expert picks names from, on the GBIF Backbone
                               Taxonomy (see gbif.py; --species-list for your own, --no-species-list)
  <out>/<deployment>/<YYYY-MM-DD>_<purpose>_provenance.csv   every crop back to its photo, box, model
                               outputs and why it was chosen (kept OUT of the package the expert gets)

The date is the labelling round, not when the photos were taken (that's in each patch's captured_at).
A night runs noon to noon and is named by the evening it starts.

Optional steps:
  clustering   similar crops are grouped (DINOv2 embeddings + HDBSCAN), so an expert can label a cluster
               at once (on by default; --no-cluster to skip)
  screens      crops that look like a reference set (e.g. geckos) are left out and replaced from the
               selection's reserve units (sample with --reserve). Screens come from --screen <ref.npz>
               or the validation.screens setting
Photos can be JPEG, PNG, TIFF, WebP or BMP (HEIC too, with pillow-heif installed); 16-bit and other
unusual pixel formats are converted. A photo's time comes from the results, else its file name, else its
EXIF (see times.py).

Packages follow Mothbot Classify as it was on MOTHBOT["classify"]["checked"]; `cehbio update` says when
Mothbot has changed since, so the format can be checked again.

Packages are checked before zipping (every patch present, records consistent, boxes inside photos), and
a finished package isn't rebuilt when the command is run again.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..media import Media, by_source

GROUPS = ["images"]
MARKER, DONE = ".cehbio_package", ".cehbio_complete"

# the Mothbot versions these packages were last checked against (cehbio update compares with the newest)
MOTHBOT = {
    "format": "mothbox-next-dataset, version 3",
    "classify": {"repo": "Digital-Naturalism-Laboratories/mothbot-classify", "branch": "main",
                 "checked": "2026-11-08", "commit": "7ad9eb1"},
    "process": {"repo": "Digital-Naturalism-Laboratories/Mothbot_Process", "checked": "v1.1.39"},
}


def mothbot_status() -> list[str]:
    """Whether Mothbot has changed since these packages were checked against it (for cehbio update)."""
    import urllib.request
    out = []

    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "ceh-biomonitoring", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    c = MOTHBOT["classify"]
    try:
        head = get(f"https://api.github.com/repos/{c['repo']}/commits/{c['branch']}")
        sha, when = head["sha"][:7], head["commit"]["committer"]["date"][:10]
        out.append(f"Mothbot Classify (the labelling site): checked {c['checked']} ({c['commit']}); newest {when} "
                   f"({sha})" + ("" if sha == c["commit"] else "  <- has changed: check the package format "
                                 "(docs/validation.md, 'Keeping up with Mothbot')"))
    except Exception as e:  # noqa: BLE001
        out.append(f"Mothbot Classify: couldn't reach GitHub ({type(e).__name__})")
    pr = MOTHBOT["process"]
    try:
        tag = get(f"https://api.github.com/repos/{pr['repo']}/releases/latest")["tag_name"]
        out.append(f"Mothbot Process: checked {pr['checked']}; newest {tag}"
                   + ("" if tag == pr["checked"] else "  <- new release: check its machine-ID fields"))
    except Exception as e:  # noqa: BLE001
        out.append(f"Mothbot Process: couldn't reach GitHub ({type(e).__name__})")
    return out


def _ndjson(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def read_ndjson(path: Path) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def _night(t) -> str:
    t = pd.to_datetime(t, errors="coerce")
    return "unknown" if pd.isna(t) else (t - pd.Timedelta(hours=12)).date().isoformat()


def _has(v) -> bool:
    return v is not None and str(v).strip() not in ("", "nan", "None", "NaT", "<NA>")


# ------------------------------------------------------------------ photos of any kind
def _open_photo(path):
    """A photo as 8-bit RGB, whatever it was saved as. Pixels stay as stored (no EXIF rotation), as the
    detector saw them, so the boxes fit."""
    from PIL import Image
    if str(path).lower().endswith((".heic", ".heif")):
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError as e:
            raise RuntimeError("HEIC photos need pillow-heif: pip install pillow-heif") from e
    from ... import times
    src = Image.open(path)
    try:
        src.load()
        taken = times.exif_time(src)
        im = src
        if im.mode in ("I;16", "I;16B", "I;16L", "I", "F"):      # 16-bit or float: scaled to 8-bit
            arr = np.asarray(im, dtype=np.float64)
            lo, hi = np.nanpercentile(arr, 0.1), np.nanpercentile(arr, 99.9)
            arr = np.clip((arr - lo) / max(hi - lo, 1e-9) * 255, 0, 255).astype(np.uint8)
            im = Image.fromarray(arr, "L")
        if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            im = Image.new("RGB", im.size, (255, 255, 255))
            im.paste(rgba, mask=rgba.split()[-1])
        rgb = im.convert("RGB")
    finally:
        src.close()                                        # so a downloaded copy can be deleted (Windows)
    return rgb, taken


# ------------------------------------------------------------------ machine identifications
def model_names(settings, rows: pd.DataFrame) -> dict:
    """Names for the models behind the results' columns (Mothbot's classifier ids)."""
    regional = None
    if "species_model" in rows.columns and rows["species_model"].notna().any():
        regional = str(rows["species_model"].dropna().iloc[0])
    else:
        try:
            from ... import countries
            t = countries.load(settings)
            folder = rows["country_folder"].dropna().astype(str) if "country_folder" in rows.columns else pd.Series([], dtype=str)
            hit = t[t["country_folder"].astype(str).isin(set(folder))] if len(folder) else t.iloc[0:0]
            if len(hit) and "species_model" in hit.columns:
                regional = str(hit["species_model"].iloc[0])
        except (Exception, SystemExit):  # noqa: BLE001 - no country table: a generic name
            pass
    g = "global_model_key"
    glob = (str(rows[g].dropna().iloc[0]) if g in rows.columns and rows[g].notna().any() else "global-model")
    if "global_model_version" in rows.columns and rows["global_model_version"].notna().any():
        glob += f" {rows['global_model_version'].dropna().iloc[0]}"
    return {"regional": regional or "regional-species-model", "global": glob, "order": "order-model"}


def machine_ids(r: dict, bb, models: dict, species_list: str | None) -> list[dict]:
    """The models' identifications of one crop, in Mothbot's machine-ID (bot) format: one row per model,
    the regional species model's (or, for a non-moth, the order model's) marked as the default."""
    from .. import gbif
    pid = r["detection_id"]
    out = []
    when = r.get("analysis_datetime")

    def add(classifier, label, taxon, conf, default):
        if not taxon:
            return
        row = {"patch_id": pid, "classifier_id": classifier, "classifier_type": "bot", "classification_type": "taxon",
               "label": label, "taxon": taxon, "morphospecies": None, "is_error": False,
               "confidence": float(conf) if _has(conf) else None,
               "classified_at": 1 if default else None,          # the default shows first; experts' answers win
               "source_bot_detection_id": f"{pid}::detector"}
        if species_list:
            row["species_list"] = species_list
        if _has(when):
            row["machine_identified_at"] = str(when)
        out.append(row)

    noise = _has(r.get("noise_class"))
    sp = r.get("regional_species_rank_1_name") if _has(r.get("regional_species_rank_1_name")) else (
        None if noise else r.get("species"))
    if _has(sp):
        rec = bb.match(sp)
        add(models["regional"], gbif.norm(sp), gbif.mothbot_taxon(rec, sp), r.get("regional_species_rank_1_confidence",
            r.get("score")), True)
    gsp = r.get("global_species_rank_1_name")
    if _has(gsp):
        rec = bb.taxon(r.get("global_species_rank_1_gbif_id")) if _has(r.get("global_species_rank_1_gbif_id")) else None
        rec = rec or bb.match(gsp)
        extra = {k: r[c] for k, c in (("genus", "global_species_rank_1_backbone_genus_name"),
                                      ("family", "global_species_rank_1_backbone_family_name")) if _has(r.get(c))}
        add(models["global"], gbif.norm(gsp), gbif.mothbot_taxon(rec, gsp, extra), r.get("global_species_rank_1_confidence"),
            False)
    order = r.get("noise_class") if noise else r.get("order_name")
    if _has(order):
        name = str(order).split()[0]                       # "Lepidoptera Macros" -> Lepidoptera
        rec = bb.match(name)
        taxon = gbif.mothbot_taxon(rec, name) if rec else {"scientificName": name, "taxonRank": "order",
                                                            "kingdom": "Animalia", "phylum": "Arthropoda",
                                                            "class": "Insecta", "order": name}
        add(models["order"], name, taxon, r.get("order_confidence"), noise or not out)
    return out


# ------------------------------------------------------------------ building one package
def build(rows: pd.DataFrame, pkg: Path, dataset_id: str, title: str, settings, blind: bool,
          media: Media, screens: list[dict], do_cluster: bool, cluster_opts: dict,
          species: dict | None = None, bb=None) -> dict:
    """species: {"table": the species list, "name": its file name, "about": where it came from}.
    bb: GBIF backbone look-ups (for the machine identifications)."""
    from .. import embeddings as E
    if pkg.exists() and (pkg / DONE).exists():
        return {"package": str(pkg), "skipped": "already built"}
    if pkg.exists():
        if not (pkg / MARKER).exists():
            raise SystemExit(f"{pkg} exists and isn't a package this command made: choose another --out")
        shutil.rmtree(pkg)                                   # an unfinished earlier attempt
    patches = pkg / "01_patches"
    for d in (patches, pkg / "02_records", pkg / "03_classifications", pkg / "04_exports"):
        d.mkdir(parents=True, exist_ok=True)
    (pkg / MARKER).write_text("made by cehbio validate prepare --platform mothbot\n")

    if not screens:
        rows = rows[~rows["reserve"].fillna(False).astype(bool)]
    made, fails = [], []
    for photo, items in by_source(rows, "images"):
        try:
            src = media.get(items.iloc[0].to_dict())
        except Exception as e:  # noqa: BLE001
            fails += [{"detection_id": r, "image_path": photo, "status": "photo not found", "error": str(e)}
                      for r in items["detection_id"]]
            continue
        try:
            im, taken = _open_photo(src)
            W, H = im.size
            for r in items.to_dict("records"):
                x0, y0 = max(0, int(round(r["x_min"]))), max(0, int(round(r["y_min"])))
                x1, y1 = min(W, int(round(r["x_max"]))), min(H, int(round(r["y_max"])))
                if x1 <= x0 or y1 <= y0:
                    fails.append({"detection_id": r["detection_id"], "image_path": photo,
                                  "status": "box outside photo", "error": f"{x0},{y0},{x1},{y1} in {W}x{H}"})
                    continue
                im.crop((x0, y0, x1, y1)).save(patches / f"{r['detection_id']}.jpg", quality=95)
                made.append({**r, "_box": [x0, y0, x1, y1], "_W": W, "_H": H, "_exif_time": taken})
        except Exception as e:  # noqa: BLE001
            fails += [{"detection_id": r, "image_path": photo, "status": "photo unreadable", "error": str(e)}
                      for r in items["detection_id"]]
        finally:
            media.done_with(src)
    crops = pd.DataFrame(made)
    if crops.empty:
        raise SystemExit(f"No crops could be made for {dataset_id}: see the failures above")
    paths = [patches / f"{d}.jpg" for d in crops["detection_id"]]

    # screens, then top up from the reserve
    emb = None
    crops["screened_out"], crops["screen"], crops["screen_distance"] = False, "", np.nan
    if screens or do_cluster:
        emb = E.embed(paths, settings)
    if screens:
        hit, which, dist = E.screen(emb, screens)
        crops["screened_out"], crops["screen"], crops["screen_distance"] = hit, which, dist
        key = ["model_group", "species"] if (crops["purpose"] == "model").all() else ["site", "species"]
        keep = []
        for _, g in crops.groupby(key, sort=False, dropna=False, observed=True):
            prim = g[~g["reserve"].fillna(False).astype(bool)]
            want = len(prim)
            ok = list(prim.index[~prim["screened_out"]])
            spare = g[g["reserve"].fillna(False).astype(bool) & ~g["screened_out"]].sort_values("rank")
            ok += list(spare.index[: max(0, want - len(ok))])
            keep += ok
        crops["used"] = crops.index.isin(keep)
    else:
        crops["used"] = True
    for i in crops.index[~crops["used"]]:
        (patches / f"{crops.at[i, 'detection_id']}.jpg").unlink(missing_ok=True)
    use = crops[crops["used"]].copy()
    if emb is not None:
        emb = emb[crops["used"].to_numpy()]

    # clustering
    use["cluster_id"] = np.nan
    if do_cluster and len(use):
        labels = E.cluster(emb, **cluster_opts)
        use["cluster_id"] = np.where(labels >= 0, labels, np.nan)

    # records
    now = datetime.now(timezone.utc).isoformat()
    from ... import times
    when, _, _ = times.best(use["image_datetime"] if "image_datetime" in use.columns else None, use["image_path"])
    exif = pd.to_datetime(use["_exif_time"], errors="coerce").reset_index(drop=True)
    use["captured_at"] = when.fillna(exif).to_numpy()            # results, file name, then the photo's EXIF
    use["night"] = [_night(t) for t in use["captured_at"]]
    use["camera_day_id"] = use["deployment_id"].astype(str) + "__" + use["night"]
    p_rows, s_rows, bot = [], [], []
    models = model_names(settings, use) if not blind else {}
    for r in use.to_dict("records"):
        pid = r["detection_id"]
        rec = {"patch_id": pid, "dataset_id": dataset_id, "asset_path": f"01_patches/{pid}.jpg",
               "media_type": "image/jpeg",
               "captured_at": None if pd.isna(r["captured_at"]) else r["captured_at"].isoformat(),
               "deployment_id": str(r["deployment_id"]), "camera_day_id": r["camera_day_id"]}
        if not pd.isna(r["cluster_id"]):
            rec.update(cluster_id=float(r["cluster_id"]), clustered_at=now)
        p_rows.append(rec)
        x0, y0, x1, y1 = r["_box"]
        s_rows.append({"patch_id": pid, "source_type": "crop_from_photo", "source_photo_id": Path(str(r["image_path"])).stem,
                       "source_photo_asset_path": str(r["image_path"]), "source_photo_width": r["_W"],
                       "source_photo_height": r["_H"], "crop_direction": 0.0, "crop_shape_type": "rotation",
                       "crop_points": [[float(x0), float(y0)], [float(x1), float(y0)], [float(x1), float(y1)], [float(x0), float(y1)]],
                       "source_bot_detection_id": f"{pid}::detector"})
        if not blind:
            bot += machine_ids(r, bb, models, species["name"] if species else None)
    rec_dir = pkg / "02_records"
    _ndjson(rec_dir / "patches.ndjson", p_rows)
    _ndjson(rec_dir / "patch-sources.ndjson", s_rows)
    # Mothbot shows a deployment as "<device> · <start date>": the deployment's name and first night
    dep_rows = []
    for d, g in use.groupby("deployment_id", observed=True, sort=True):
        name = next((str(n) for n in g["deployment_name"] if _has(n)), str(d)) if "deployment_name" in g else str(d)
        site = next((str(n) for n in g.get("country_folder", pd.Series(dtype=object)) if _has(n)), "")
        nights = sorted(n for n in g["night"].unique() if n != "unknown")
        dep_rows.append({"deployment_id": str(d), "dataset_id": dataset_id, "deployment_name": name,
                         "site_id": f"{dataset_id}/site/{site or 'site'}", "site_name_from_folder": site.replace("_", " "),
                         "device_id_from_folder": name, "deployment_start_from_folder": nights[0] if nights else "",
                         "dataset_name_from_folder": title})
    _ndjson(rec_dir / "deployments.ndjson", dep_rows)
    _ndjson(rec_dir / "camera-days.ndjson", [
        {"camera_day_id": c, "dataset_id": dataset_id, "deployment_id": str(d), "night_date": n}
        for c, d, n in use[["camera_day_id", "deployment_id", "night"]].drop_duplicates().sort_values("camera_day_id").itertuples(index=False)])
    (rec_dir / "current-classifications.ndjson").write_text("")
    if bot:
        _ndjson(pkg / "03_classifications" / "_bot.ndjson", bot)
    lists = []
    if species is not None and len(species["table"]):
        f = pkg / "species" / species["name"]
        f.parent.mkdir(parents=True, exist_ok=True)
        species["table"].to_csv(f, sep="\t", index=False)       # tab-separated, as GBIF's downloads are
        lists.append(f"species/{species['name']}")
    manifest = {
        "format": "mothbox-next-dataset", "version": 3, "dataset_id": dataset_id,
        "hierarchy": {"levels": [
            {"key": "deployment", "label": "Deployment", "records": "02_records/deployments.ndjson",
             "id_field": "deployment_id", "parent_field": None},
            {"key": "night", "label": "Night", "records": "02_records/camera-days.ndjson",
             "id_field": "camera_day_id", "parent_field": "deployment_id"}],
            "leaf": {"key": "night", "patch_field": "camera_day_id"}},
        "title": title,
        "description": ("Expert-labelling package made with ceh-biomonitoring (cehbio validate). "
                        + ("The models' identifications are in 03_classifications/_bot.ndjson. " if not blind else
                           "The models' identifications are left out, so the expert labels without them. ")
                        + (f"Species list: {lists[0]} (GBIF Backbone Taxonomy)." if lists else "")),
        "package_kind": "lightweight_substrate", "classification_unit": "patch",
        "source": {"included": False, "path": None, "original_source_available_elsewhere": True,
                   "trace_fields": ["02_records/patch-sources.ndjson"]},
        "cloud_upload_default": {"include_source": False, "include_patches": True},
        "folders": {"records": "02_records/", "classifications": "03_classifications/", "patches": "01_patches/"},
        "records": {"patches": "02_records/patches.ndjson",
                    "current_classifications": "02_records/current-classifications.ndjson",
                    "deployments": "02_records/deployments.ndjson", "camera_days": "02_records/camera-days.ndjson",
                    "patch_sources": "02_records/patch-sources.ndjson"},
        "classification_sources": ["03_classifications/_bot.ndjson"] if bot else [],
        "patches": {"included": True, "path": "01_patches/", "required_when_source_absent": False},
        "species_lists": lists,
        "made_with": {"tool": "ceh-biomonitoring", "mothbot_checked": MOTHBOT["classify"]["checked"]},
    }
    (pkg / "dataset.json").write_text(json.dumps(manifest, indent=2))
    problems = check(pkg)
    if problems:
        raise SystemExit(f"{pkg} failed its checks:\n  " + "\n  ".join(problems[:20]))

    # provenance, outside the package
    prov = crops.drop(columns=[c for c in crops.columns if c.startswith("_")])
    prov = prov.merge(use[["detection_id", "cluster_id", "night"]], on="detection_id", how="left")
    prov.to_csv(f"{pkg}_provenance.csv", index=False)
    if fails:
        pd.DataFrame(fails).to_csv(f"{pkg}_failures.csv", index=False)
    (pkg / DONE).write_text(now + "\n")
    return {"package": str(pkg), "crops": len(use), "screened_out": int(crops["screened_out"].sum()),
            "reserve_used": int((use["reserve"].fillna(False).astype(bool)).sum()),
            "clusters": int(use["cluster_id"].nunique()), "failures": len(fails)}


def check(pkg: Path) -> list[str]:
    """What's wrong with a package folder or .zip (empty list = it should open in Mothbot)."""
    pkg = Path(pkg)
    if pkg.suffix == ".zip":
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(pkg) as z:
                z.extractall(tmp)
            inner = [p.parent for p in Path(tmp).rglob("dataset.json")]
            return check(inner[0]) if len(inner) == 1 else [f"{pkg.name} should hold one package (dataset.json), found {len(inner)}"]
    if not (pkg / "dataset.json").exists() and pkg.with_suffix(".zip").exists():
        return check(pkg.with_suffix(".zip"))               # the folder was emptied when it was zipped
    out = []
    try:
        man = json.loads((pkg / "dataset.json").read_text())
    except Exception as e:  # noqa: BLE001
        return [f"dataset.json unreadable: {e}"]
    if man.get("format") != "mothbox-next-dataset" or man.get("version") != 3:
        out.append("dataset.json isn't a Mothbox Next version 3 manifest")
    rec = {}
    for name, rel in (man.get("records") or {}).items():
        try:
            rec[name] = read_ndjson(pkg / rel)
        except Exception as e:  # noqa: BLE001
            out.append(f"{rel} unreadable: {e}")
    if out:
        return out
    ids = [p["patch_id"] for p in rec["patches"]]
    if len(ids) != len(set(ids)):
        out.append("patch ids repeat")
    missing = [p["asset_path"] for p in rec["patches"] if not (pkg / p["asset_path"]).is_file()
               or (pkg / p["asset_path"]).stat().st_size == 0]
    if missing:
        out.append(f"{len(missing)} patch images missing, e.g. {missing[0]}")
    src = {s["patch_id"]: s for s in rec["patch_sources"]}
    if set(ids) - set(src):
        out.append(f"{len(set(ids) - set(src))} patches have no source record")
    for s in src.values():
        xs, ys = [p[0] for p in s["crop_points"]], [p[1] for p in s["crop_points"]]
        if min(xs) < 0 or min(ys) < 0 or max(xs) > s["source_photo_width"] or max(ys) > s["source_photo_height"]:
            out.append(f"box outside its photo: {s['patch_id']}")
            break
    days = {c["camera_day_id"]: c for c in rec["camera_days"]}
    if {p["camera_day_id"] for p in rec["patches"]} - set(days):
        out.append("some patches' nights are missing from camera-days")
    if {c["deployment_id"] for c in days.values()} - {d["deployment_id"] for d in rec["deployments"]}:
        out.append("some nights' deployments are missing from deployments")
    for f in (pkg / "03_classifications").glob("*.ndjson"):
        try:
            rows = read_ndjson(f)
            unknown = {c["patch_id"] for c in rows} - set(ids)
            if unknown:
                out.append(f"{f.name} labels {len(unknown)} patches that aren't in the package")
            nameless = [c for c in rows if c.get("classification_type") == "taxon"
                        and not (c.get("taxon") or {}).get("scientificName")]
            if nameless:
                out.append(f"{f.name}: {len(nameless)} identifications have no taxon.scientificName")
        except Exception as e:  # noqa: BLE001
            out.append(f"{f.name} unreadable: {e}")
    for rel in man.get("species_lists") or []:
        try:
            t = pd.read_csv(pkg / rel, sep="\t", nrows=5)
            if not {"scientificName", "species"} & set(t.columns) or t.empty:
                out.append(f"{rel} isn't a species list Mothbot can read (no scientificName or species column)")
        except Exception as e:  # noqa: BLE001
            out.append(f"{rel} unreadable: {e}")
    return out


def zip_package(pkg: Path, keep_folder: bool = False) -> Path:
    z = pkg.with_suffix(".zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pkg.rglob("*")):
            if f.is_file() and f.name not in (MARKER, DONE):
                zf.write(f, Path(pkg.name) / f.relative_to(pkg))
    if not keep_folder:
        for f in pkg.rglob("*"):
            if f.is_file() and f.name not in (MARKER, DONE):
                f.unlink()
    return z


# ------------------------------------------------------------------ the species list
def country_of(rows: pd.DataFrame) -> str | None:
    """The package's country (for its GBIF list), from the selection or the results."""
    for c in ("country", "country_folder", "bucket", "bucket_name"):
        if c in rows.columns:
            v = [str(x) for x in rows[c].dropna().unique() if _has(x) and str(x) != "local"]
            if v:
                return v[0]
    return None


def species_for(rows: pd.DataFrame, settings, own: str | None, taxon: str, offline: bool, round_date: str,
                with_global: bool = False) -> dict:
    """The package's species list. The global model's guesses (often species from other continents) are
    only added when its machine IDs are shown (with_global), so they're on the list the expert sees."""
    from .. import gbif
    names = set()
    for c in ("regional_species_rank_1_name",) + (("global_species_rank_1_name",) if with_global else ()):
        if c in rows.columns:
            names |= {str(x) for x in rows[c].dropna().unique() if _has(x)}
    if "species" in rows.columns:
        names |= {str(x) for x in rows["species"].dropna().unique() if _has(x) and not str(x).startswith("not a moth")}
    country = country_of(rows)
    table, about = gbif.build(names, settings, country=country, taxon=taxon, own_list=own, offline=offline)
    if about.get("offline"):
        print("   NOTE: GBIF couldn't be reached and isn't cached for this: the species list has names only. "
              "Run once on a machine with internet (e.g. a sci machine) to fill the cache.", flush=True)
    place = (Path(own).stem if own else (about.get("country_name") or country or "package"))
    place = place.replace("_", " ").title().replace(" ", "")
    name = f"SpeciesList_{place}_{taxon or 'taxa'}-GBIF-backbone-{round_date}.csv"
    return {"table": table, "name": name, "about": {**about, "country": country, "file": f"species/{name}"}}


# ------------------------------------------------------------------ the platform entry point
def prepare(sel: pd.DataFrame, out: Path, settings=None, blind: bool | None = None, bucket: str | None = None,
            source_root: str | None = None, screens: list | None = None, cluster: bool = True,
            cluster_method: str = "leaf", min_cluster_size: int = 3, one_package: bool = False,
            keep_unzipped: bool = False, round_date: str | None = None, species_list: str | None = None,
            species_taxon: str = "Lepidoptera", offline: bool = False, **_) -> dict:
    """species_list: None (built from GBIF for the package's country), a CSV of your own, or "none"."""
    from .. import embeddings as E
    from .. import gbif
    blind = True if blind is None else blind               # experts label without the model's guesses
    bb = gbif.lookup(settings, offline=offline)
    specs = list(screens or []) + list((settings.get("validation.screens") if settings is not None else None) or [])
    loaded = [E.load_screen(s) for s in specs]
    if loaded and not sel["reserve"].fillna(False).astype(bool).any():
        print("NOTE: screens are on but the selection has no reserve units, so screened crops won't be "
              "replaced. Sample with --reserve N to have spares.", flush=True)
    round_date = round_date or date.today().isoformat()
    purpose = str(sel["purpose"].iloc[0])
    groups = [(None, sel)] if one_package else list(sel.groupby("deployment_id", sort=True, observed=True))
    results = []
    with Media(settings, "images", bucket, source_root) as media:
        for dep, rows in groups:
            folder = Path(out) / (str(dep) if dep is not None else "")
            pkg = folder / f"{round_date}_{purpose}"
            dataset_id = f"{dep or 'all'}_{round_date}_{purpose}"
            name = str(rows["deployment_name"].dropna().iloc[0]) if rows["deployment_name"].notna().any() else (dep or "")
            title = f"{name or dataset_id} {purpose} {round_date}".strip()
            print(f"\n== {dataset_id}: {int((~rows['reserve'].fillna(False).astype(bool)).sum())} crops", flush=True)
            species = None
            if not (isinstance(species_list, str) and species_list.lower() == "none") and not (pkg / DONE).exists():
                species = species_for(rows, settings, species_list, species_taxon, offline, round_date,
                                      with_global=not blind)
                Path(f"{pkg}_species_list.json").parent.mkdir(parents=True, exist_ok=True)
                Path(f"{pkg}_species_list.json").write_text(json.dumps(species["about"], indent=2, default=str))
                a = species["about"]
                print(f"   species list: {a['rows']} taxa ({a['with_keys']} with GBIF backbone keys) -> "
                      f"species/{species['name']}", flush=True)
            res = build(rows, pkg, dataset_id, title, settings, blind, media, loaded, cluster,
                        {"method": cluster_method, "min_cluster_size": min_cluster_size}, species, bb)
            if "skipped" not in res:
                res["zip"] = str(zip_package(pkg, keep_unzipped))
            print("   " + ", ".join(f"{k}: {v}" for k, v in res.items()), flush=True)
            results.append(res)
    return {"packages": results, "blind": blind, "screens": [s["name"] for s in loaded]}
