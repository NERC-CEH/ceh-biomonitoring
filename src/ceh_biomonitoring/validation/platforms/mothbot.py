"""Mothbot: packages for the Mothbot labelling site (https://mothbot-classify.vercel.app), in its
"Mothbox Next" format (version 3). Moved here from the UKCEH expert-labelling pipeline (2026).

Each package is one labelling round:

  <out>/<deployment>/<YYYY-MM-DD>_<purpose>.zip        (one per deployment; --one-package for one in all)
     dataset.json              the manifest: deployment > night hierarchy
     01_patches/<id>.jpg       a crop per selected detection, cut from the original photo with the
                               detector's box (no re-detection; the photo itself isn't included)
     02_records/               patches, patch-sources (photo, box, size), deployments, camera-days (nights)
     03_classifications/       _bot.ndjson: the model's identifications, ONLY with --no-blind; experts'
                               answers are saved here as <their initials>.ndjson
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


def _taxon(row) -> tuple[str, dict]:
    """The model's identification as Mothbot expects it."""
    nc = row.get("noise_class")
    if nc and str(nc) not in ("nan", "None"):
        return f"ORDER_{nc}", {"kingdom": "Animalia", "phylum": "Arthropoda", "class": "Insecta", "order": str(nc)}
    sp = str(row.get("species") or "")
    parts = sp.split()
    taxon = {"kingdom": "Animalia", "phylum": "Arthropoda", "class": "Insecta",
             "order": str(row.get("order_name") or "Lepidoptera")}
    fam = row.get("global_species_rank_1_backbone_family_name")
    if fam and str(fam) not in ("nan", "None"):
        taxon["family"] = str(fam)
    if parts:
        taxon["genus"] = parts[0]
    if len(parts) > 1:
        taxon.update(species=parts[1], taxonRank="species")
    return sp, taxon


# ------------------------------------------------------------------ building one package
def build(rows: pd.DataFrame, pkg: Path, dataset_id: str, title: str, settings, blind: bool,
          media: Media, screens: list[dict], do_cluster: bool, cluster_opts: dict) -> dict:
    from .. import embeddings as E
    from PIL import Image
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
            with Image.open(src) as im:
                im = im.convert("RGB")
                W, H = im.size
                for r in items.to_dict("records"):
                    x0, y0 = max(0, int(round(r["x_min"]))), max(0, int(round(r["y_min"])))
                    x1, y1 = min(W, int(round(r["x_max"]))), min(H, int(round(r["y_max"])))
                    if x1 <= x0 or y1 <= y0:
                        fails.append({"detection_id": r["detection_id"], "image_path": photo,
                                      "status": "box outside photo", "error": f"{x0},{y0},{x1},{y1} in {W}x{H}"})
                        continue
                    im.crop((x0, y0, x1, y1)).save(patches / f"{r['detection_id']}.jpg", quality=95)
                    made.append({**r, "_box": [x0, y0, x1, y1], "_W": W, "_H": H})
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
    use["captured_at"] = pd.to_datetime(use.get("image_datetime"), errors="coerce")
    use["night"] = [_night(t) for t in use["captured_at"]]
    use["camera_day_id"] = use["deployment_id"].astype(str) + "__" + use["night"]
    p_rows, s_rows, bot = [], [], []
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
            label, taxon = _taxon(r)
            bot.append({"patch_id": pid, "classifier_id": "ceh-biomonitoring", "classifier_type": "bot",
                        "classification_type": "taxon", "label": label, "taxon": taxon,
                        "confidence": None if pd.isna(r.get("score")) else float(r["score"]),
                        "classified_at": None, "source_bot_detection_id": f"{pid}::detector"})
    deps = use.groupby("deployment_id", observed=True).agg(name=("deployment_name", "first")).reset_index()
    rec_dir = pkg / "02_records"
    _ndjson(rec_dir / "patches.ndjson", p_rows)
    _ndjson(rec_dir / "patch-sources.ndjson", s_rows)
    _ndjson(rec_dir / "deployments.ndjson", [
        {"deployment_id": str(d), "dataset_id": dataset_id,
         "deployment_name": str(n) if n and str(n) not in ("nan", "None", "") else str(d)}
        for d, n in zip(deps["deployment_id"], deps["name"])])
    _ndjson(rec_dir / "camera-days.ndjson", [
        {"camera_day_id": c, "dataset_id": dataset_id, "deployment_id": str(d), "night_date": n}
        for c, d, n in use[["camera_day_id", "deployment_id", "night"]].drop_duplicates().sort_values("camera_day_id").itertuples(index=False)])
    (rec_dir / "current-classifications.ndjson").write_text("")
    if bot:
        _ndjson(pkg / "03_classifications" / "_bot.ndjson", bot)
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
                        + ("The model's identifications are in 03_classifications/_bot.ndjson." if not blind else
                           "The model's identifications are left out, so the expert labels without them.")),
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
            unknown = {c["patch_id"] for c in read_ndjson(f)} - set(ids)
            if unknown:
                out.append(f"{f.name} labels {len(unknown)} patches that aren't in the package")
        except Exception as e:  # noqa: BLE001
            out.append(f"{f.name} unreadable: {e}")
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


# ------------------------------------------------------------------ the platform entry point
def prepare(sel: pd.DataFrame, out: Path, settings=None, blind: bool | None = None, bucket: str | None = None,
            source_root: str | None = None, screens: list | None = None, cluster: bool = True,
            cluster_method: str = "leaf", min_cluster_size: int = 3, one_package: bool = False,
            keep_unzipped: bool = False, round_date: str | None = None, **_) -> dict:
    from .. import embeddings as E
    blind = True if blind is None else blind               # experts label without the model's guesses
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
            res = build(rows, pkg, dataset_id, title, settings, blind, media, loaded, cluster,
                        {"method": cluster_method, "min_cluster_size": min_cluster_size})
            if "skipped" not in res:
                res["zip"] = str(zip_package(pkg, keep_unzipped))
            print("   " + ", ".join(f"{k}: {v}" for k, v in res.items()), flush=True)
            results.append(res)
    return {"packages": results, "blind": blind, "screens": [s["name"] for s in loaded]}
