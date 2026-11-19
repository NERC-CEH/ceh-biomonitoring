"""Run one chunk, and combine a deployment's chunks. Shared by every pipeline.

Outputs under <outputs_root>/<pipeline>/<project>/<deployment>/ (layout.py has the whole layout):
    working/run_params.json                         settings used for this deployment
    working/chunks/<dep>_chunk_00001_detections.parquet
    working/chunks/<dep>_chunk_00001_files.csv      every file: detections / no_detections / failed
    working/chunks/<dep>_chunk_00001_summary.json   status, counts, provenance
    working/chunks/<dep>_chunk_00001_keep/          extra files a pipeline keeps (e.g. Perch scores)
    PROGRESS.txt                                    updated after every chunk
and after `cehbio combine`:
    <dep>_detections.parquet (+ .csv up to a million rows), <dep>_files.csv, <dep>_qa.json
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from . import devices, layout, objectstore, progress, provenance
from .chunks import now_utc, read_chunk, write_json
from .pipelines.base import Pipeline
from .settings import Settings


def link_or_copy(src: Path, dest: Path) -> Path:
    """Symlink src to dest (fast, no extra space); copy if links aren't allowed (e.g. Windows)."""
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    try:
        dest.symlink_to(src.resolve())
    except OSError:
        shutil.copy2(src, dest)
    return dest


CSV_MAX_ROWS = 1_000_000     # bigger results are parquet only (a CSV that size won't open in Excel anyway)


def paths(settings: Settings, pipeline: Pipeline, place: str, deployment: str) -> layout.RunPaths:
    return layout.run_paths(settings, pipeline.name, place, deployment)


def deployment_dir(settings: Settings, pipeline: Pipeline, place: str, deployment: str) -> Path:
    """The folder a deployment's results are in."""
    return paths(settings, pipeline, place, deployment).root


def save_run_params(settings, pipeline, place, deployment, params) -> Path:
    p = paths(settings, pipeline, place, deployment).params
    write_json(p, {"saved_at": now_utc(), "pipeline": pipeline.name, "params": params})
    return p


def load_run_params(settings, pipeline, place, deployment) -> dict:
    p = paths(settings, pipeline, place, deployment).params
    return json.loads(p.read_text())["params"] if p.exists() else pipeline.params()


def run_chunk(settings: Settings, pipeline: Pipeline, chunk_json: Path, params: dict | None = None,
              keep_temp: bool = False, force: bool = False) -> dict:
    chunk = read_chunk(chunk_json)
    country, dep, idx = chunk["country_folder"], chunk["deployment_id"], int(chunk["chunk_index"])
    place = chunk.get("project") or country
    params = params or load_run_params(settings, pipeline, place, dep)
    run_id = f"{dep}_chunk_{idx:05d}"
    rp = paths(settings, pipeline, place, dep)
    out = rp.chunks
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / f"{run_id}_summary.json"
    if summary_path.exists() and not force:
        prev = json.loads(summary_path.read_text())
        if prev.get("status") == "complete":
            print(f"{run_id} already complete; skipping (use --force to redo)", flush=True)
            return prev

    pipeline.check_installed()
    stage = settings.tmp_root / pipeline.name / place / dep / run_id
    summary = {"status": "running", "started_at": now_utc(), "chunk_json": str(chunk_json),
               "country_folder": country, "deployment_id": dep, "chunk_index": idx,
               "n_files_expected": len(chunk["keys"])}
    write_json(summary_path, summary)
    try:
        files, failed_dl = [], []
        if chunk.get("source") == "local":
            # Local folder: never move or delete the originals. Work on links (or copies) in the stage folder.
            stage.mkdir(parents=True, exist_ok=True)
            for key in chunk["keys"]:
                src = Path(key)
                if not src.exists():
                    failed_dl.append({"source_key": key, "filename": src.name, "status": "failed",
                                      "error": "file not found"})
                    continue
                files.append((key, link_or_copy(src, stage / src.name)))
        else:
            s3 = objectstore.client(settings)
            for key, local, err in objectstore.download(s3, chunk["bucket_code"], chunk["keys"], stage):
                if err:
                    failed_dl.append({"source_key": key, "filename": Path(key).name, "status": "failed",
                                      "error": f"download: {err}"})
                else:
                    files.append((key, local))
        result = pipeline.process(files, chunk, params, stage)

        det = result.detections.copy()
        for col, val in (("country_folder", country), ("deployment_id", dep), ("chunk_index", idx)):
            det[col] = val
        device = devices.get(chunk["device"]) if chunk.get("device") else None
        override = chunk.get("timestamp_pattern")
        if (device or override) and len(det) and "source_key" in det:
            parsed = {k: devices.parse_filename(str(k), device, override) for k in det["source_key"].unique()}
            det["file_datetime"] = det["source_key"].map(lambda k: parsed[k]["file_datetime"])
            det["device_serial"] = det["source_key"].map(lambda k: parsed[k]["device_serial"])
        det.to_parquet(out / f"{run_id}_{pipeline.output_name}.parquet", index=False)

        n_det = det.groupby("source_key").size() if len(det) else pd.Series(dtype=int)
        ok_label = "detections" if pipeline.output_name == "detections" else "processed"
        status = [{"source_key": k, "filename": Path(k).name, "status": ok_label,
                   "n_detections": int(n_det.get(k, 0))} for k in n_det.index]
        status += [{**r, "n_detections": 0} for r in result.no_detections + result.failed + failed_dl]
        files_df = pd.DataFrame(status)
        files_df.to_csv(out / f"{run_id}_files.csv", index=False)

        keep = stage / "keep"
        if keep.exists():
            dest = out / f"{run_id}_keep"
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(keep, dest)

        n_failed = len(result.failed) + len(failed_dl)
        summary.update({
            "status": "complete" if n_failed < len(chunk["keys"]) else "failed",
            "finished_at": now_utc(),
            "n_files_processed": len(files) - len(result.failed),
            "n_files_with_detections": int(len(n_det)),
            "n_files_no_detections": len(result.no_detections),
            "n_files_failed": n_failed,
            "n_detections": int(len(det)),
            "provenance": provenance.record(pipeline.name, params, result.models),
        })
    except Exception as e:  # noqa: BLE001
        summary.update({"status": "failed", "finished_at": now_utc(), "error": f"{type(e).__name__}: {e}"})
        raise
    finally:
        write_json(summary_path, summary)
        progress.write_progress_file(rp, pipeline.name, place, dep)
        if not keep_temp and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
    print(f"{run_id}: {summary['status']} - {summary.get('n_detections', 0)} detections, "
          f"{summary.get('n_files_failed', 0)} files failed", flush=True)
    return summary


def combine(settings: Settings, pipeline: Pipeline, country: str, deployment: str) -> dict:
    """Join a deployment's chunks into its results files. `country` is the project (place) folder."""
    rp = paths(settings, pipeline, country, deployment)
    ddir, cdir = rp.root, rp.chunks
    if not rp.manifest.exists():
        raise SystemExit(f"No run of {pipeline.name} for {deployment} in {rp.root.parent}. "
                         f"`cehbio status` lists every run.")
    manifest = json.loads(rp.manifest.read_text())
    summaries = {p.name.replace("_summary.json", ""): json.loads(p.read_text()) for p in cdir.glob("*_summary.json")}
    complete = [k for k, v in summaries.items() if v.get("status") == "complete"]
    expected = [f"{deployment}_chunk_{i:05d}" for i in range(1, manifest["n_chunks"] + 1)]
    missing = [c for c in expected if c not in complete]

    name = pipeline.output_name
    det_parts = [pd.read_parquet(cdir / f"{c}_{name}.parquet") for c in expected if c in complete]
    det = pd.concat(det_parts, ignore_index=True) if det_parts else pd.DataFrame()
    det.to_parquet(ddir / f"{deployment}_{name}.parquet", index=False)
    csv = ddir / f"{deployment}_{name}.csv"
    if len(det) <= CSV_MAX_ROWS:
        det.to_csv(csv, index=False)
    elif csv.exists():
        csv.unlink()
    def _read(p: Path) -> pd.DataFrame:
        try:
            return pd.read_csv(p)
        except (FileNotFoundError, pd.errors.EmptyDataError):
            return pd.DataFrame()
    parts = [_read(cdir / f"{c}_files.csv") for c in expected if c in complete]
    files = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    files.to_csv(ddir / f"{deployment}_files.csv", index=False)

    qa = {
        "combined_at": now_utc(), "pipeline": pipeline.name, "country_folder": country, "deployment_id": deployment,
        "chunks_expected": len(expected), "chunks_complete": len(complete), "chunks_missing": missing,
        "files_expected": manifest["total_files"],
        "files_by_status": files["status"].value_counts().to_dict() if len(files) else {},
        f"n_{name}_rows": int(len(det)),
        "n_detections": int(len(det)),
        "complete": not missing,
    }
    if len(det) or len(files):
        qa.update(pipeline.after_combine(ddir, deployment, det, files,
                                         load_run_params(settings, pipeline, country, deployment)) or {})
    write_json(ddir / f"{deployment}_qa.json", qa)
    progress.write_progress_file(rp, pipeline.name, country, deployment)
    return qa
