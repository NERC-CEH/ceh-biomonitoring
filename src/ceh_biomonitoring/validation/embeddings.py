"""Image embeddings (DINOv2), used to cluster similar crops for the expert and to screen out things that
look like a reference set (geckos, leaves, snails...).

DINOv2 (Meta, Apache 2.0) is downloaded once into the toolkit's model cache (models.cache_dir/torch_hub).
Compute nodes without internet use that copy: run any `cehbio validate prepare --platform mothbot` (or
`cehbio validate reference`) once on a machine with internet, e.g. a JASMIN sci machine, first.

Screens: a reference (.npz) holds the embeddings of example crops of something to leave out, their
centroid, and a distance threshold. A crop closer to the centroid than the threshold is screened out.
Make one with `cehbio validate reference <folder of example crops> --name gecko --out gecko.npz`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

MODEL = ("facebookresearch/dinov2", "dinov2_vits14")
DIM = 384


def _hub_dir(settings) -> Path:
    custom = settings.get("validation.torch_hub_dir") if settings is not None else None
    base = Path(custom) if custom else Path(settings.get("models.cache_dir", "~/.cache/ceh-biomonitoring/models")).expanduser() / "torch_hub"
    base.mkdir(parents=True, exist_ok=True)
    return base


def load_model(settings, device=None):
    import torch
    torch.hub.set_dir(str(_hub_dir(settings)))
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    local = _hub_dir(settings) / "facebookresearch_dinov2_main"
    try:
        if local.exists():                    # no internet needed once downloaded
            model = torch.hub.load(str(local), MODEL[1], source="local")
        else:
            model = torch.hub.load(*MODEL, trust_repo=True, skip_validation=True)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"Could not load DINOv2 ({type(e).__name__}: {e}). It is downloaded once into "
                         f"{_hub_dir(settings)}: run this once on a machine with internet (e.g. a JASMIN sci "
                         f"machine) and try again.") from e
    return model.to(device).eval(), device


def embed(paths: list[Path], settings, batch_size: int = 64, model=None) -> np.ndarray:
    """One 384-number embedding per image, in the order given."""
    import torch
    import torchvision.transforms as T
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    if not paths:
        return np.zeros((0, DIM), dtype=np.float32)
    model, device = model or load_model(settings)
    tf = T.Compose([T.Resize(256), T.CenterCrop(224), T.ToTensor(), T.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])
    out = np.zeros((len(paths), DIM), dtype=np.float32)
    with torch.no_grad():
        for i in range(0, len(paths), batch_size):
            batch = []
            for p in paths[i:i + batch_size]:
                with Image.open(p) as im:
                    batch.append(tf(im.convert("RGB")))
            out[i:i + len(batch)] = model(torch.stack(batch).to(device)).cpu().numpy().astype(np.float32)
            if len(paths) > batch_size:
                print(f"  embeddings {min(i + batch_size, len(paths))}/{len(paths)}", flush=True)
    return out


def cluster(emb: np.ndarray, min_cluster_size: int = 3, min_samples: int = 1, epsilon: float = 0.05,
            method: str = "leaf") -> np.ndarray:
    """HDBSCAN cluster numbers (-1 = in no cluster). 'leaf' gives many small, tight clusters (easier for
    an expert to accept in one go); 'eom' fewer, larger ones."""
    from sklearn.cluster import HDBSCAN
    if len(emb) < max(2, min_cluster_size):
        return np.full(len(emb), -1)
    return HDBSCAN(min_cluster_size=min_cluster_size, min_samples=min_samples, cluster_selection_epsilon=epsilon,
                   cluster_selection_method=method, metric="euclidean").fit_predict(emb)


# ------------------------------------------------------------------ screens
def load_screen(spec) -> dict:
    """spec: a path to a reference .npz, or {name, file, threshold} from settings."""
    from ..pipelines.images.filters import resolve
    if isinstance(spec, (str, Path)):
        spec = {"file": str(spec)}
    ref = np.load(resolve(spec["file"]), allow_pickle=True)                 # a path, or pkg:<package>/<file>
    thr = spec.get("threshold") or (float(ref["threshold"]) if "threshold" in ref.files else None)
    if thr is None:
        raise SystemExit(f"{spec['file']} has no threshold: give one in the settings (threshold: ...)")
    name = spec.get("name") or (str(ref["name"]) if "name" in ref.files else Path(spec["file"]).stem)
    return {"name": name, "centroid": ref["centroid"].astype(np.float32), "threshold": float(thr),
            "file": str(spec["file"])}


def screen(emb: np.ndarray, screens: list[dict]) -> tuple[np.ndarray, list[str], np.ndarray]:
    """(screened out?, which screen, distance to its centroid) for each embedding."""
    hit = np.zeros(len(emb), dtype=bool)
    which = [""] * len(emb)
    dist = np.full(len(emb), np.nan)
    for s in screens:
        d = np.linalg.norm(emb - s["centroid"], axis=1)
        new = (d <= s["threshold"]) & ~hit
        for i in np.flatnonzero(new):
            which[i] = s["name"]
        dist = np.where(np.isnan(dist) | (d < dist), d, dist)
        hit |= new
    return hit, which, dist


def build_reference(paths: list[Path], name: str, out: Path, settings, threshold: float | None = None) -> dict:
    """A screen from example crops: their embeddings, centroid, and a threshold (default: the distance
    that takes in 95% of the examples). Check the suggested threshold on a package before relying on it."""
    emb = embed(paths, settings)
    centroid = emb.mean(axis=0)
    d = np.linalg.norm(emb - centroid, axis=1)
    thr = float(threshold) if threshold is not None else float(np.percentile(d, 95))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, name=name, embeddings=emb, centroid=centroid, threshold=thr,
                        files=np.array([p.name for p in paths], dtype=object), model=f"{MODEL[0]}:{MODEL[1]}")
    return {"name": name, "examples": len(paths), "threshold": thr, "distance_median": float(np.median(d)),
            "distance_max": float(d.max()), "file": str(out)}
