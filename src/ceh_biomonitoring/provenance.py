"""Record exactly what produced each output: package versions, models, settings, machine.

We always install the newest releases (minimum versions, not pins), so every summary
file carries this record. That keeps results reproducible even as models update.
"""
from __future__ import annotations

import getpass
import platform
import socket
import sys
from importlib import metadata

from . import __version__

TRACKED = ("ceh-biomonitoring", "numpy", "pandas", "pyarrow", "boto3", "tensorflow", "birdnet-analyzer",
           "birdnet", "kagglehub", "torch", "torchvision", "batdetect2", "flat-bug", "ultralytics", "timm",
           "scikit-maad", "librosa", "soundfile")


def package_versions() -> dict:
    out = {}
    for name in TRACKED:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    return out


def record(pipeline: str, params: dict, models: dict | None = None) -> dict:
    return {
        "toolkit_version": __version__,
        "pipeline": pipeline,
        "params": params,
        "models": models or {},
        "packages": package_versions(),
        "python": sys.version.split()[0],
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "user": getpass.getuser(),
    }
