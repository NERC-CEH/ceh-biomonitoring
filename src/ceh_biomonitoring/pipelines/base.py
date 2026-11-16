"""What a pipeline is.

A pipeline only has to say what files it wants and how to process a folder of them.
Listing files, chunking, downloading, Slurm, combining outputs and provenance are shared.

To add a pipeline: subclass Pipeline in a new module under ceh_biomonitoring/pipelines/,
list it in REGISTRY (pipelines/__init__.py) and add an install extra in pyproject.toml.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass
class ChunkResult:
    detections: pd.DataFrame                                  # one row per detection
    no_detections: list[dict] = field(default_factory=list)   # files processed with nothing found
    failed: list[dict] = field(default_factory=list)          # files that could not be processed
    models: dict = field(default_factory=dict)                # model names / versions actually used


class Pipeline:
    name: str = ""                 # used on the command line: cehbio run <name>
    title: str = ""                # one-line description for `cehbio pipelines`
    extra: str = ""                # pip extra that installs it: pip install -e ".[<extra>]"
    data_type: str = ""            # object-store folder under each deployment
    extensions: tuple[str, ...] = ()
    key_field: str = "keys"        # field name in chunk JSONs (kept for older chunk files)
    output_name: str = "detections"  # what one output row is: e.g. detections
    media: tuple[str, ...] = ()      # which device media it accepts: ("audio",) or ("images",)
    needs_gpu: bool = False
    defaults: dict = {}

    def check_installed(self) -> None:
        """Raise ImportError with a friendly message if this pipeline's extra isn't installed."""

    def params(self, overrides: dict | None = None) -> dict:
        return {**self.defaults, **{k: v for k, v in (overrides or {}).items() if v is not None}}

    def process(self, files: list[tuple[str, Path]], chunk: dict, params: dict, workdir: Path) -> ChunkResult:
        """files: (object-store key, local path) pairs already downloaded into `workdir`."""
        raise NotImplementedError


def require(module: str, extra: str) -> None:
    """Check a package is installed *without importing it* (importing TensorFlow/PyTorch takes ~20 s)."""
    import importlib.util
    if importlib.util.find_spec(module) is None:
        raise ImportError(
            f"This pipeline needs extra packages. Install them with:\n"
            f'    ./install.sh {extra}      (or: pip install -e ".[{extra}]")\n(missing: {module})'
        )
