"""Pipeline registry. Modules are imported only when used, so a bats-only install never
needs TensorFlow and a birds-only install never needs PyTorch.

Plug-ins (e.g. the private internal repo) add pipelines through the Python entry-point group
"ceh_biomonitoring.pipelines", e.g. in their pyproject.toml:

    [project.entry-points."ceh_biomonitoring.pipelines"]
    report = "ceh_internal.report:Report"
"""
from __future__ import annotations

import importlib
from importlib import metadata

from .base import Pipeline

# name -> "module:Class"
BUILT_IN = {
    "bats": "ceh_biomonitoring.pipelines.bats:BatDetect",
    "birds": "ceh_biomonitoring.pipelines.birds:Birds",
    "images": "ceh_biomonitoring.pipelines.images:Images",
}


def registry() -> dict[str, str]:
    out = dict(BUILT_IN)
    for ep in metadata.entry_points(group="ceh_biomonitoring.pipelines"):
        out[ep.name] = ep.value
    return out


def get(name: str) -> Pipeline:
    reg = registry()
    if name not in reg:
        raise SystemExit(f"Unknown pipeline '{name}'. Available: {', '.join(sorted(reg))}")
    module, cls = reg[name].split(":")
    return getattr(importlib.import_module(module), cls)()


def available() -> list[tuple[str, str, str, bool, str]]:
    """(name, title, extra, installed, message) for every registered pipeline."""
    rows = []
    for name in sorted(registry()):
        p = get(name)
        try:
            p.check_installed()
            rows.append((name, p.title, p.extra, True, ""))
        except ImportError as e:
            rows.append((name, p.title, p.extra, False, str(e)))
    return rows
