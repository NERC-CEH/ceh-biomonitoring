"""Birds: BirdNET or Perch on audible recordings. Choose with  model: birdnet | perch.

Licences (matter for commercial projects):
  BirdNET weights and its location filter: CC BY-NC-SA 4.0, NON-COMMERCIAL use only.
  Perch v2: Apache 2.0, fine for commercial use.

BirdNET  the official BirdNET-Analyzer, with its own optional location/week filter.
Perch    Google's Perch v2: 5 s windows at 32 kHz. By default each window's top species and score
         are reported with no cut-off: choose a threshold for your own sites and check it against
         recordings you have listened to. Scores can be saved so you can re-threshold later
         without re-running the model.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from .base import ChunkResult, Pipeline, require

BIRDNET_COLUMNS = ["source_key", "filename", "start_time", "end_time", "species_name", "common_name", "confidence"]
PERCH_COLUMNS = ["source_key", "filename", "start_time", "end_time", "species_name", "logit"]


class Birds(Pipeline):
    name = "birds"
    title = "Birds with BirdNET or Perch (audible recordings)"
    extra = "birds"
    data_type = "audible_recordings"
    extensions = (".wav", ".flac", ".mp3")
    key_field = "audio_keys"
    media = ("audio",)
    defaults = {
        "model": "birdnet",          # birdnet | perch
        # BirdNET
        "lat": None, "lon": None,    # deployment location: BirdNET uses it for its geo model
        "week": None,                # 1-48; empty = year-round
        "min_conf": 0.25,
        "overlap": 0.0,
        # Perch
        "perch_model": "",           # folder with the Perch saved model; empty = download from Kaggle
        "perch_kaggle_handle": "google/bird-vocalization-classifier/tensorFlow2/perch_v2_cpu",
        "hop_seconds": 5.0,          # step between windows; 5 = no overlap
        "logit_threshold": None,     # empty = report each window's top species; set a number to filter
        "top_n": 1,                  # species per window when no threshold is set
        "species_list": "",          # CSV with a 'species' column: only these species are reported (both models)
        "species_list_unlikely": "flag",  # species the list marks unlikely that month: flag (unlikely_this_month) | remove
        "save_scores": False,        # keep per-window scores + embeddings (.npz) to re-threshold later
    }

    def check_installed(self) -> None:
        require("tensorflow", self.extra)
        require("soundfile", self.extra)

    # ------------------------------------------------------------------ dispatch
    def process(self, files, chunk, params, workdir):
        model = str(params.get("model", "birdnet")).lower()
        if model == "birdnet":
            return self._birdnet(files, chunk, params, workdir)
        if model == "perch":
            return self._perch(files, chunk, params, workdir)
        raise SystemExit(f"Unknown bird model '{model}': use birdnet or perch")

    # ------------------------------------------------------------------ BirdNET
    def _birdnet(self, files, chunk, params, workdir):
        """Official BirdNET-Analyzer. Recordings are analysed in groups that share a species list: one
        group per month with a monthly list, one per BirdNET week when its own location filter follows
        each recording's date, otherwise all together (one call uses all the job's CPUs)."""
        require("birdnet_analyzer", self.extra)
        import shutil
        print("NOTE: BirdNET's model and location filter are licensed CC BY-NC-SA 4.0: NON-COMMERCIAL use only. "
              "For commercial work use model: perch.", flush=True)
        from birdnet_analyzer.analyze import analyze  # type: ignore
        from ..species_lists import SpeciesList, birdnet_week, file_date, flag_unlikely, keep_unlikely

        lat = params.get("lat", chunk.get("lat"))
        lon = params.get("lon", chunk.get("lon"))
        slist = SpeciesList(params["species_list"]) if params.get("species_list") else None
        geo = slist is None and lat is not None and lon is not None
        fixed_week = int(params["week"]) if params.get("week") else None

        # which group each recording belongs to
        groups: dict = {}
        for key, path in files:
            d = file_date(key, chunk)
            if slist is not None:
                g = ("month", d.month if (d and slist.monthly) else None)
            elif geo:
                g = ("week", fixed_week if fixed_week else birdnet_week(d))
            else:
                g = ("all", None)
            groups.setdefault(g, []).append((key, path))

        out_dir = workdir / "birdnet_results"
        threads = int(os.environ.get("SLURM_CPUS_PER_TASK") or os.cpu_count() or 1)
        used = []
        for (kind, value), members in sorted(groups.items(), key=lambda kv: str(kv[0])):
            audio_dir = workdir / f"audio_{kind}_{value if value is not None else 'any'}"
            audio_dir.mkdir(parents=True, exist_ok=True)
            for _, path in members:
                if path.parent != audio_dir:
                    shutil.move(str(path), audio_dir / path.name)
            kwargs = {"min_conf": float(params["min_conf"]), "overlap": float(params["overlap"]), "rtype": "csv",
                      "threads": threads}
            if kind == "month":
                kwargs["slist"] = str(self._birdnet_slist(slist, value, workdir, keep_unlikely(params)))
            elif kind == "week":
                kwargs.update(lat=float(lat), lon=float(lon), week=int(value))
            analyze(str(audio_dir), str(out_dir), **kwargs)
            used.append({kind: value, "files": len(members)})

        frames, none, failed = [], [], []
        for key, path in files:
            res = out_dir / f"{path.stem}.BirdNET.results.csv"
            if not res.exists():
                failed.append({"source_key": key, "filename": path.name, "status": "failed",
                               "error": "BirdNET wrote no results file"})
                continue
            df = pd.read_csv(res)
            if df.empty:
                none.append({"source_key": key, "filename": path.name, "status": "no_detections"})
                continue
            df = df.rename(columns={"Start (s)": "start_time", "End (s)": "end_time", "Scientific name": "species_name",
                                    "Common name": "common_name", "Confidence": "confidence"}).drop(columns=["File"], errors="ignore")
            df.insert(0, "filename", path.name)
            df.insert(0, "source_key", key)
            frames.append(df)
        det = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=BIRDNET_COLUMNS)
        if slist is not None:
            det = flag_unlikely(det, slist, chunk)
        try:
            from importlib.metadata import version
            models = {"birdnet-analyzer": version("birdnet-analyzer")}
        except Exception:  # noqa: BLE001
            models = {}
        models.update({"geo_model": geo, "species_list": params.get("species_list") or None,
                       "species_list_kind": slist.describe() if slist else None, "groups": used,
                       "licence": "CC BY-NC-SA 4.0"})
        return ChunkResult(det, none, failed, models)

    @staticmethod
    def _birdnet_slist(slist, month, workdir: Path, unlikely: bool = True) -> Path:
        """BirdNET's own species-list file ('Scientific_Common' lines) for one month of our list."""
        import birdnet_analyzer.config as cfg
        from ..species_lists import norm
        wanted = slist.allowed(month, unlikely)
        lines = [l.strip() for l in open(cfg.BIRDNET_LABELS_FILE, encoding="utf-8") if l.strip()]
        keep = [l for l in lines if norm(l.split("_")[0]) in wanted]
        if not keep:
            raise SystemExit(f"None of the species in {slist.path} ({'month ' + str(month) if month else 'all year'}) "
                             f"are in BirdNET's list")
        out = workdir / f"birdnet_species_list_{month or 'all'}.txt"
        out.write_text("".join(line + "\n" for line in keep), encoding="utf-8")
        print(f"Species list {'for month ' + str(month) if month else '(all year)'}: {len(keep)} of BirdNET's species",
              flush=True)
        return out

    # ------------------------------------------------------------------ Perch
    _net = None
    _labels = None

    def _load_perch(self, params):
        if self._net is not None:
            return
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        import tensorflow as tf

        folder = params.get("perch_model")
        if not folder:
            require("kagglehub", self.extra)
            import kagglehub
            folder = kagglehub.model_download(params["perch_kaggle_handle"])
        folder = Path(folder)
        self._net = tf.saved_model.load(str(folder)).signatures["serving_default"]
        labels = next(iter(folder.rglob("labels.csv")), None)
        if labels is None:
            raise SystemExit(f"No labels.csv found under {folder}")
        self._labels = pd.read_csv(labels).iloc[:, 0].astype(str).to_numpy()
        self._model_dir = str(folder)

    def _perch(self, files, chunk, params, workdir):
        import soundfile as sf
        import tensorflow as tf
        from scipy.signal import resample_poly

        self._load_perch(params)
        sr_model, win, batch = 32_000, 160_000, 32
        hop = int(float(params["hop_seconds"]) * sr_model)
        thr = None if params.get("logit_threshold") in (None, "") else float(params["logit_threshold"])
        top_n = max(1, int(params.get("top_n") or 1))
        from ..species_lists import SpeciesList, file_month, flag_unlikely, keep_unlikely, norm
        slist = SpeciesList(params["species_list"]) if params.get("species_list") else None
        with_unlikely = keep_unlikely(params)
        label_names = [norm(lab) for lab in self._labels]
        masks: dict = {}

        def keep_for(key):
            m = file_month(key, chunk) if (slist and slist.monthly) else None
            if m not in masks:
                allowed = slist.allowed(m, with_unlikely) if slist else None
                masks[m] = np.array([allowed is None or lab in allowed for lab in label_names])
            return masks[m]

        rows, none, failed = [], [], []
        score_dir = workdir / "keep" / "perch_scores"   # anything under keep/ is saved with the outputs
        for key, path in files:
            try:
                x, sr = sf.read(path, dtype="float32")
                x = x.mean(axis=1) if x.ndim > 1 else x
                if sr != sr_model:
                    g = np.gcd(sr, sr_model)
                    x = resample_poly(x, sr_model // g, sr // g).astype(np.float32)
                starts = np.arange(0, max(len(x) - win, 0) + 1, hop)
                logits, emb = [], []
                for i in range(0, len(starts), batch):
                    audio = np.stack([np.pad(x[s:s + win], (0, max(0, win - len(x[s:s + win]))))
                                      for s in starts[i:i + batch]])
                    res = self._net(inputs=tf.constant(audio))
                    logits.append(res["label"].numpy())
                    emb.append(res["embedding"].numpy().astype(np.float16))
                lab = np.concatenate(logits) if logits else np.zeros((0, len(self._labels)), np.float32)
                lab_kept = np.where(keep_for(key)[None, :], lab, -np.inf)
                if thr is not None:                       # your own cut-off
                    w_idx, c_idx = np.nonzero(lab_kept >= thr)
                else:                                     # no cut-off: each window's top species
                    order = np.argsort(-lab_kept, axis=1)[:, :top_n] if len(lab_kept) else np.zeros((0, top_n), int)
                    w_idx = np.repeat(np.arange(len(order)), order.shape[1])
                    c_idx = order.reshape(-1)
                for w, c in zip(w_idx, c_idx):
                    s = starts[w] / sr_model
                    rows.append({"source_key": key, "filename": path.name, "start_time": float(s),
                                 "end_time": float(s + win / sr_model), "species_name": self._labels[c],
                                 "logit": float(lab[w, c])})
                if len(w_idx) == 0:
                    none.append({"source_key": key, "filename": path.name, "status": "no_detections",
                                 "windows": int(len(starts))})
                if params.get("save_scores"):
                    score_dir.mkdir(parents=True, exist_ok=True)
                    np.savez_compressed(score_dir / f"{path.stem}.npz", source_key=key,
                                        starts_s=(starts / sr_model).astype(np.float32),
                                        logits=lab.astype(np.float16), embedding=np.concatenate(emb) if emb else np.zeros((0, 0)))
            except Exception as e:  # noqa: BLE001
                failed.append({"source_key": key, "filename": path.name, "status": "failed", "error": str(e)})
        det = pd.DataFrame(rows, columns=PERCH_COLUMNS)
        if slist is not None:
            det = flag_unlikely(det, slist, chunk)
        return ChunkResult(det, none, failed, {"perch_model": getattr(self, "_model_dir", ""),
                                                "hop_seconds": params["hop_seconds"],
                                                "logit_threshold": thr, "top_n": None if thr is not None else top_n,
                                                "species_list": params.get("species_list") or None,
                                                "species_list_kind": slist.describe() if slist else None,
                                                "licence": "Apache 2.0"})
