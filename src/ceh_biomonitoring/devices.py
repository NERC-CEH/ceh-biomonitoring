"""Device profiles: what differs between recording hardware.

A device profile (YAML) says what kind of files the device makes, where they live, how to read
the date and time from a file name, whether it needs a mask, and default settings per pipeline.

Settings are layered:  pipeline defaults < device < project config (--config) < --set on the command line.

Built-in devices are in ceh_biomonitoring/device_profiles/*.yml. Add your own by dropping a YAML file in
~/.config/ceh-biomonitoring/devices/, or ship them in a plug-in (e.g. the internal repo).
"""
from __future__ import annotations

import re
from datetime import datetime
from importlib import metadata, resources
from pathlib import Path

import yaml

from .settings import CONFIG_DIR


def _sources() -> list[Path]:
    out = [Path(str(resources.files("ceh_biomonitoring.device_profiles")))]
    for ep in metadata.entry_points(group="ceh_biomonitoring.devices"):
        out.append(Path(str(resources.files(ep.value))))
    out.append(CONFIG_DIR / "devices")
    return out


def available() -> dict[str, dict]:
    found = {}
    for folder in _sources():
        if folder.is_dir():
            for f in sorted(folder.glob("*.yml")):
                d = yaml.safe_load(f.read_text()) or {}
                d.setdefault("name", f.stem)
                d["_file"] = str(f)
                found[d["name"]] = d          # later sources override earlier ones
    return found


def get(name: str) -> dict:
    devs = available()
    if name not in devs:
        raise SystemExit(f"Unknown device '{name}'. Known: {', '.join(sorted(devs))}")
    return devs[name]


def check_compatible(device: dict, pipeline) -> None:
    media = device.get("media")
    if media and pipeline.media and media not in pipeline.media:
        raise SystemExit(f"Device '{device['name']}' records {media}; pipeline '{pipeline.name}' needs "
                         f"{' or '.join(pipeline.media)}.")


def pipeline_params(device: dict, pipeline_name: str) -> dict:
    return dict((device.get("params") or {}).get(pipeline_name) or {})


_TOKENS = {"YYYY": r"(?P<Y>\d{4})", "MM": r"(?P<m>\d{2})", "DD": r"(?P<d>\d{2})",
           "hh": r"(?P<H>\d{2})", "mm": r"(?P<M>\d{2})", "ss": r"(?P<S>\d{2})",
           "SERIAL": r"(?P<serial>[A-Za-z0-9]+)", "*": r".*?"}


def pattern_to_regex(pattern: str) -> re.Pattern:
    """Plain-language file-name pattern -> regex.

    YYYY MM DD hh mm ss = date and time parts, SERIAL = device ID, * = anything, everything else literal.
      "SERIAL-YYYYMMDDThhmmss"  matches 123456789012345-20260806T025318.jpg
      "*_YYYYMMDD_hhmmss"       matches SMA01234_20240705_043000.wav
    Note: MM is month and mm is minutes, as in date formats.
    """
    out, i = "", 0
    keys = sorted(_TOKENS, key=len, reverse=True)
    while i < len(pattern):
        for k in keys:
            if pattern.startswith(k, i):
                out += _TOKENS[k]
                i += len(k)
                break
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out)


def patterns_for(device: dict | None, override: str | None = None) -> list[str]:
    ts = (device or {}).get("timestamp") or {}
    pats = list(ts.get("patterns") or [])
    return ([override] if override else []) + pats


def parse_filename(filename: str, device: dict | None, override: str | None = None) -> dict:
    """{'file_datetime': 'YYYY-MM-DD hh:mm:ss' or None, 'device_serial': ... or None}. No timezone shifting."""
    name = Path(filename).name
    for pat in patterns_for(device, override):
        m = pattern_to_regex(pat).search(name)
        if not m:
            continue
        g = m.groupdict()
        try:
            dt = datetime(int(g["Y"]), int(g["m"]), int(g["d"]), int(g.get("H") or 0),
                          int(g.get("M") or 0), int(g.get("S") or 0))
        except (KeyError, TypeError, ValueError):
            continue
        return {"file_datetime": dt.isoformat(sep=" "), "device_serial": g.get("serial")}
    return {"file_datetime": None, "device_serial": None}


def parse_timestamp(filename: str, device: dict | None, override: str | None = None) -> str | None:
    return parse_filename(filename, device, override)["file_datetime"]
