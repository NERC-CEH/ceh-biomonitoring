"""Settings: built-in defaults < machine profile < plug-in profile < your own settings file < command line.

The machine profile (e.g. jasmin or local) is picked automatically from where you are running,
or set it yourself with the CEHBIO_PROFILE environment variable or --profile.
Plug-ins (e.g. an organisation's internal package) can add machine profiles or fill in their own
values for existing ones, through the entry-point group "ceh_biomonitoring.profiles".

Your own settings live in ~/.config/ceh-biomonitoring/settings.yml (optional). Example:

    outputs_root: /gws/<your-group-workspace>/<you>/ceh-biomonitoring-results
    slurm:
      account: <your-jasmin-slurm-account>
"""
from __future__ import annotations

import copy
import getpass
import os
import socket
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(os.environ.get("CEHBIO_CONFIG_DIR", Path.home() / ".config" / "ceh-biomonitoring"))
USER_SETTINGS = CONFIG_DIR / "settings.yml"
# Results used to default to ~/ceh-biomonitoring/outputs, which is also where `git clone` puts the code.
NEW_DEFAULT_OUTPUTS = "~/ceh-biomonitoring-results"
OLD_DEFAULT_OUTPUTS = "~/ceh-biomonitoring/outputs"


def _profile_dirs() -> list:
    """Built-in profiles first, then plug-ins (later ones override earlier ones)."""
    from importlib import metadata
    dirs = [resources.files("ceh_biomonitoring.profiles")]
    for ep in metadata.entry_points(group="ceh_biomonitoring.profiles"):
        dirs.append(resources.files(ep.value))
    return dirs


def available_profiles() -> list[str]:
    names = set()
    for d in _profile_dirs():
        names |= {p.name[:-4] for p in d.iterdir() if p.name.endswith(".yml") and p.name != "defaults.yml"}
    return sorted(names)


def detect_profile() -> str:
    """Each profile can say how to recognise its machine:  detect: {hosts: [...], paths: [...]}"""
    if os.environ.get("CEHBIO_PROFILE"):
        return os.environ["CEHBIO_PROFILE"]
    host = socket.getfqdn().lower()
    for name in available_profiles():
        rule = (load_profile(name).get("detect") or {})
        if any(h in host for h in rule.get("hosts", [])) or any(Path(p).exists() for p in rule.get("paths", [])):
            return name
    return "local"


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(os.path.expanduser(value.replace("{user}", getpass.getuser())))
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def load_profile(name: str) -> dict:
    """Merge this profile from the core and every plug-in that provides it."""
    merged, found = {}, False
    for d in _profile_dirs():
        f = d.joinpath(f"{name}.yml")
        if f.is_file():
            merged = _deep_merge(merged, yaml.safe_load(f.read_text()) or {})
            found = True
    if not found:
        raise SystemExit(f"Unknown machine profile '{name}'. Available: {', '.join(available_profiles())}")
    return merged


@dataclass
class Settings:
    profile: str
    values: dict = field(default_factory=dict)

    @classmethod
    def load(cls, profile: str | None = None, overrides: dict | None = None,
             settings_file: Path | None = None) -> "Settings":
        name = profile or detect_profile()
        merged = _deep_merge(load_profile("defaults"), load_profile(name))
        path = settings_file or USER_SETTINGS
        if path and Path(path).exists():
            merged = _deep_merge(merged, yaml.safe_load(Path(path).read_text()) or {})
        if os.environ.get("CEHBIO_RESULTS"):           # e.g. from R's options(cehbio.results = ...)
            merged["outputs_root"] = os.environ["CEHBIO_RESULTS"]
        merged = _deep_merge(merged, overrides or {})
        values = _expand(merged)
        new, old = (Path(x).expanduser() for x in (NEW_DEFAULT_OUTPUTS, OLD_DEFAULT_OUTPUTS))
        if (Path(str(values.get("outputs_root", ""))) == new and not new.exists() and old.is_dir()
                and any(old.iterdir())):
            values["outputs_root"], values["_old_default"] = str(old), True   # keep finding earlier results
        return cls(profile=name, values=values)

    def get(self, key: str, default: Any = None) -> Any:
        node: Any = self.values
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, key: str) -> Path:
        value = self.get(key)
        if value in (None, ""):
            raise KeyError(f"Setting '{key}' is not set. Add it to {USER_SETTINGS}.")
        return Path(value)

    # Common locations -------------------------------------------------------------
    @property
    def outputs_root(self) -> Path:
        return self.path("outputs_root")

    @property
    def tmp_root(self) -> Path:
        return self.path("tmp_root")

    def pipeline_dir(self, pipeline: str, country: str) -> Path:
        return self.outputs_root / pipeline / country
