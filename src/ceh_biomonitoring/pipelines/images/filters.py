"""Masks and filters: leaving out things that aren't insects.

MASK  An image the same shape as the camera's photos: black = ignore, white = keep. A detection is
      ignored when at least `mask_overlap` (default half) of its box is in the black area. Use it for a
      ring light, a camera rig or a label that is always in view. Make one with `cehbio mask`.

FILTERS  Your own rules in a YAML file, e.g. to flag geckos or snails:

    filters:
      - name: gecko
        stage: detection          # detection | order | species: when the rule is checked
        action: flag              # flag (default: kept, named in the 'filters' column) | remove
        when:                     # every condition must hold
          relative_area_min: 0.02   # box area as a fraction of the image
          aspect_min: 2.5           # long side / short side

  Conditions:
    relative_area_min / relative_area_max   box area / image area
    aspect_min / aspect_max                 long side / short side of the box
    zone: [x0, y0, x1, y1]                  box centre inside this part of the image (0-1)
    box_score_max                           detector confidence at or below this
    filename_matches                        a regular expression, e.g. "^ami-mini-"
    class_name: [nonmoth]                   moth / nonmoth            (stage order or species)
    order_name: [Vegetation, Araneae]       one of these orders      (stage order or species)
    order_confidence_max                                              (stage order or species)
    species: [Xestia c-nigrum]              top species is one of these (stage species)
    species_confidence_max                                            (stage species)
"""
from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

import numpy as np
import yaml

STAGES = ("detection", "order", "species")
GEOMETRY = {"relative_area_min", "relative_area_max", "aspect_min", "aspect_max", "zone", "box_score_max",
            "filename_matches"}
NEEDS_ORDER = {"class_name", "order_name", "order_confidence_max"}
NEEDS_SPECIES = {"species", "species_confidence_max"}
ALL_CONDITIONS = GEOMETRY | NEEDS_ORDER | NEEDS_SPECIES


def resolve(path: str) -> Path:
    """A file path, or pkg:<package>/<file> for a file shipped inside an installed package."""
    if str(path).startswith("pkg:"):
        pkg, _, rel = str(path)[4:].partition("/")
        return Path(str(resources.files(pkg).joinpath(rel)))
    return Path(path).expanduser()


# --------------------------------------------------------------------------- masks
class Mask:
    def __init__(self, path: str, overlap: float = 0.5):
        from PIL import Image
        self.path = str(resolve(path))
        img = Image.open(self.path).convert("L")
        self.keep = np.asarray(img) >= 128                 # True = keep
        self.overlap = float(overlap)
        self._sized: dict[tuple[int, int], np.ndarray] = {}

    def _integral(self, w: int, h: int) -> np.ndarray:
        if (w, h) not in self._sized:
            from PIL import Image
            ignore = Image.fromarray((~self.keep).astype(np.uint8) * 255).resize((w, h), Image.NEAREST)
            ig = (np.asarray(ignore) > 0).astype(np.int64)
            self._sized[(w, h)] = np.pad(ig.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        return self._sized[(w, h)]

    def ignored(self, box, w: int, h: int) -> bool:
        """True if at least `overlap` of the box lies in the ignore (black) area."""
        s = self._integral(w, h)
        x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
        x1, y1 = min(w, int(np.ceil(box[2]))), min(h, int(np.ceil(box[3])))
        if x1 <= x0 or y1 <= y0:
            return False
        inside = s[y1, x1] - s[y0, x1] - s[y1, x0] + s[y0, x0]
        return inside / ((x1 - x0) * (y1 - y0)) >= self.overlap


class CircleMask:
    """Circles to ignore, e.g. a ring light and its screws, as in a masks.json:
        {"image_size": [2592, 1944], "circles": [{"label": "light housing", "x": 1207, "y": 649, "r": 316}, ...]}
    A box is ignored when its centre is inside a circle. Circles are scaled if photos are a different size."""

    def __init__(self, spec: dict, source: str = ""):
        self.path = source
        self.size = spec.get("image_size")
        self.circles = spec["circles"]

    def ignored(self, box, w: int, h: int) -> bool:
        sx, sy = (w / self.size[0], h / self.size[1]) if self.size else (1.0, 1.0)
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        return any(((cx - c["x"] * sx) ** 2 + (cy - c["y"] * sy) ** 2) ** 0.5 <= c["r"] * max(sx, sy)
                   for c in self.circles)


class SiteMasks:
    """A masks.json with one entry per site: the site is the photo's folder name, unless given."""

    def __init__(self, table: dict, source: str, site: str | None = None):
        self.path, self.table, self.site = source, table, site

    def for_photo(self, key: str):
        name = self.site if self.site in self.table else Path(str(key)).parent.name
        spec = self.table.get(name)
        return CircleMask(spec, self.path) if spec else None


def load_mask(spec: str | None, overlap: float = 0.5, site: str | None = None):
    """A mask image (black = ignore), a circles file, or a masks.json of several sites."""
    if not spec:
        return None
    path = resolve(spec)
    if path.suffix.lower() == ".json":
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        if "circles" in data:
            return CircleMask(data, str(path))
        return SiteMasks(data, str(path), site)
    return Mask(str(path), overlap)


# --------------------------------------------------------------------------- rules
def load_rules(spec) -> list[dict]:
    """spec: a YAML path, a list of paths, or a list of rules already loaded."""
    if not spec:
        return []
    items = spec if isinstance(spec, list) else [spec]
    rules: list[dict] = []
    for item in items:
        if isinstance(item, dict):
            rules.append(item)
            continue
        data = yaml.safe_load(resolve(item).read_text(encoding="utf-8")) or {}
        rules += data.get("filters", data if isinstance(data, list) else [])
    for r in rules:
        r.setdefault("action", "flag")
        r.setdefault("when", {})
        stage = r.setdefault("stage", "detection")
        if stage not in STAGES:
            raise SystemExit(f"Filter '{r.get('name')}': stage must be one of {', '.join(STAGES)}")
        if r["action"] not in ("flag", "remove"):
            raise SystemExit(f"Filter '{r.get('name')}': action must be flag or remove")
        unknown = set(r["when"]) - ALL_CONDITIONS
        if unknown:
            raise SystemExit(f"Filter '{r.get('name')}': unknown condition(s) {', '.join(sorted(unknown))}")
        if stage == "detection" and set(r["when"]) & (NEEDS_ORDER | NEEDS_SPECIES):
            raise SystemExit(f"Filter '{r.get('name')}' uses classification results: give it stage: order or species")
        if stage == "order" and set(r["when"]) & NEEDS_SPECIES:
            raise SystemExit(f"Filter '{r.get('name')}' uses species results: give it stage: species")
    return rules


def matches(rule: dict, crop: dict, w: int, h: int) -> bool:
    """crop: x_min, y_min, x_max, y_max, box_score, filename and, later, class/order/species results."""
    c = rule["when"]
    bw, bh = crop["x_max"] - crop["x_min"], crop["y_max"] - crop["y_min"]
    rel = (bw * bh) / float(w * h) if w and h else 0.0
    aspect = max(bw, bh) / min(bw, bh) if min(bw, bh) > 0 else float("inf")
    cx, cy = (crop["x_min"] + bw / 2) / w, (crop["y_min"] + bh / 2) / h
    checks = {
        "relative_area_min": lambda v: rel >= v,
        "relative_area_max": lambda v: rel <= v,
        "aspect_min": lambda v: aspect >= v,
        "aspect_max": lambda v: aspect <= v,
        "zone": lambda v: v[0] <= cx <= v[2] and v[1] <= cy <= v[3],
        "box_score_max": lambda v: crop["box_score"] <= v,
        "filename_matches": lambda v: re.search(v, crop.get("filename", "")) is not None,
        "class_name": lambda v: crop.get("class_name") in v,
        "order_name": lambda v: crop.get("order_name") in v,
        "order_confidence_max": lambda v: (crop.get("order_confidence") or 0) <= v,
        "species": lambda v: crop.get("regional_species_rank_1_name") in v,
        "species_confidence_max": lambda v: (crop.get("regional_species_rank_1_confidence") or 0) <= v,
    }
    return all(checks[k](v) for k, v in c.items())


def apply(rules: list[dict], stage: str, crop: dict, w: int, h: int) -> tuple[bool, list[str]]:
    """(remove?, names of rules that matched) for the rules of one stage."""
    remove, names = False, []
    for r in rules:
        if r["stage"] == stage and matches(r, crop, w, h):
            names.append(r.get("name", "unnamed"))
            remove = remove or r["action"] == "remove"
    return remove, names
