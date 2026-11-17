"""Bats: BatDetect2 on ultrasonic recordings.

Ported from ultrasonic/batdetect_ultrasonic/scripts/run_batdetect_chunk.py:
same command (batdetect2 detect <dir> <out> <threshold>), same output columns.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

from .base import ChunkResult, Pipeline, require

COLUMNS = ["source_key", "filename", "start_time", "end_time", "detection_probability",
           "class_probability", "species_name", "event", "low_freq", "high_freq"]


class BatDetect(Pipeline):
    name = "bats"
    title = "Bat calls with BatDetect2 (ultrasonic recordings)"
    extra = "bats"
    data_type = "ultrasound_recordings"
    extensions = (".wav", ".flac")
    key_field = "audio_keys"
    media = ("audio",)
    defaults = {"detection_threshold": 0.3,
                "species_list": "",              # CSV with a 'species' column (e.g. bats recorded near the site)
                "species_list_action": "flag"}   # flag (column in_species_list) | remove

    def check_installed(self) -> None:
        require("batdetect2", self.extra)

    def process(self, files, chunk, params, workdir):
        audio_dir = workdir / "audio"
        out_dir = workdir / "batdetect_outputs"
        audio_dir.mkdir(parents=True, exist_ok=True)
        for _, path in files:
            if path.parent != audio_dir:
                shutil.move(str(path), audio_dir / path.name)
        # Use the batdetect2 from this environment, even when it isn't activated (e.g. in Slurm jobs).
        here = Path(sys.executable).parent / "batdetect2"
        exe = str(here) if here.exists() else (shutil.which("batdetect2") or "batdetect2")
        cmd = [exe, "detect", str(audio_dir), str(out_dir), str(params["detection_threshold"])]
        print("Running:", " ".join(cmd), flush=True)
        subprocess.run(cmd, check=True)

        key_by_name = {Path(k).name: k for k, _ in files}
        rows, none, seen = [], [], set()
        for pred_file in sorted(out_dir.glob("*.json")):
            pred = json.loads(pred_file.read_text())
            audio_file = pred.get("audio_file") or pred.get("id")
            if audio_file is None:
                continue
            fname = Path(audio_file).name
            seen.add(fname)
            dets = pred.get("annotation", [])
            if not dets:
                none.append({"source_key": key_by_name.get(fname), "filename": fname, "status": "no_detections"})
                continue
            for d in dets:
                rows.append({
                    "source_key": key_by_name.get(fname), "filename": fname,
                    "start_time": d.get("start_time"), "end_time": d.get("end_time"),
                    "detection_probability": d.get("det_prob"), "class_probability": d.get("class_prob"),
                    "species_name": d.get("class"), "event": d.get("event"),
                    "low_freq": d.get("low_freq"), "high_freq": d.get("high_freq"),
                })
        failed = [{"source_key": k, "filename": Path(k).name, "status": "failed",
                   "error": "BatDetect2 wrote no result for this file"}
                  for k, _ in files if Path(k).name not in seen]
        try:
            from importlib.metadata import version
            models = {"batdetect2": version("batdetect2")}
        except Exception:  # noqa: BLE001
            models = {}
        det = pd.DataFrame(rows, columns=COLUMNS)
        if params.get("species_list"):
            from ..species_lists import norm, read
            wanted = read(params["species_list"])
            det["in_species_list"] = det["species_name"].map(lambda x: norm(x) in wanted)
            if params.get("species_list_action") == "remove":
                det = det[det["in_species_list"]]
            models["species_list"] = params["species_list"]
        return ChunkResult(det, none, failed, models)
