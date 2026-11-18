"""cehbio update / cehbio versions: keep every pipeline on the newest models.

update
  1. gets the newest code and model lists (git pull, for installs from a clone, including plug-ins
     such as the UKCEH in-house package)
  2. upgrades the packages of every installed pipeline to their newest releases: BirdNET, Perch's
     runtime, BatDetect2, flat-bug and the image libraries
  3. fetches the newest Perch model and the newest image models now, so the next run doesn't wait;
     refreshes the GBIF backbone species lists used in labelling packages, and says whether Mothbot
     (the labelling site) has changed since the package format was last checked against it
  4. shows what changed
Every run still records the exact versions it used, so results stay reproducible.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from importlib import metadata
from pathlib import Path

PACKAGES = ["ceh-biomonitoring", "ceh-biomonitoring-internal", "birdnet-analyzer", "tensorflow", "kagglehub",
            "batdetect2", "torch", "torchvision", "timm", "flat-bug", "ultralytics", "scikit-maad"]
EXTRAS = ("birds", "bats", "images")


def versions() -> dict:
    out = {}
    for p in PACKAGES:
        try:
            out[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            pass
    return out


def _source_dir(dist_name: str) -> Path | None:
    """The folder a package was installed from with `pip install -e`, if it is a git clone."""
    try:
        d = metadata.distribution(dist_name)
        info = json.loads(d.read_text("direct_url.json") or "{}")
    except (metadata.PackageNotFoundError, ValueError):
        return None
    url = info.get("url", "")
    if info.get("dir_info", {}).get("editable") and url.startswith("file://"):
        path = Path(url[7:].lstrip("/") if os.name == "nt" else url[7:])
        return path if (path / ".git").exists() else None
    return None


def _run(cmd: list[str], **kw) -> int:
    print("  $ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, **kw)


def _fresh_versions() -> dict:
    """Versions as a new Python process sees them (after upgrading)."""
    code = "import json; from ceh_biomonitoring.update import versions; print(json.dumps(versions()))"
    try:
        return json.loads(subprocess.check_output([sys.executable, "-c", code], text=True).strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return {}


def update(pull: bool = True, fetch_models: bool = True) -> None:
    from . import pipelines
    before = versions()
    env = dict(os.environ)
    if Path("/var/tmp").is_dir() and ("jasmin" in socket.getfqdn() or Path("/gws").is_dir()):
        env["TMPDIR"] = f"/var/tmp/{os.environ.get('USER', 'user')}/cehbio-update"   # JASMIN's /tmp is too small
        Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)

    # 1. newest code and model lists
    core_dir = _source_dir("ceh-biomonitoring")
    plugin_dirs = [d for d in (_source_dir(dist.metadata["Name"]) for dist in metadata.distributions()
                               if (dist.metadata["Name"] or "").startswith("ceh-biomonitoring-")) if d]
    if pull:
        for d in [core_dir, *plugin_dirs]:
            if d:
                print(f"Getting the newest code in {d} ...")
                if _run(["git", "-C", str(d), "pull", "--ff-only"]) != 0:
                    print("  (could not update this folder automatically: local changes? Continuing.)")

    # 2. newest packages for the installed pipelines
    installed = [n for n, _, extra, ok, _ in pipelines.available() if ok and n in EXTRAS]
    extras = f"[{','.join(installed)}]" if installed else ""
    if core_dir:
        target = ["-e", f"{core_dir}{extras}"]
    else:
        target = [f"ceh-biomonitoring{extras} @ https://github.com/NERC-CEH/ceh-biomonitoring/archive/refs/heads/main.zip"]
    print(f"Upgrading: {', '.join(installed) or 'core only'} ...")
    _run([sys.executable, "-m", "pip", "install", "--upgrade", "--upgrade-strategy", "eager", "--quiet", *target], env=env)
    for d in plugin_dirs:
        _run([sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "--no-deps", "-e", str(d)], env=env)

    # 3. newest models, fetched now
    if fetch_models:
        if "birds" in installed:
            print("Fetching the newest Perch model ...")
            _run([sys.executable, "-c", "import kagglehub; from ceh_biomonitoring.pipelines.birds import Birds; "
                  "print('  Perch:', kagglehub.model_download(Birds.defaults['perch_kaggle_handle']))"], env=env)
        if "images" in installed:
            print("Fetching the newest image models ...")
            _run([sys.executable, "-c", "from ceh_biomonitoring.update import fetch_image_models; fetch_image_models()"],
                 env=env)
        print("Refreshing the GBIF backbone species lists used for labelling ...")
        _run([sys.executable, "-c", "from ceh_biomonitoring.update import refresh_labelling; refresh_labelling()"],
             env=env)

    # 4. what changed
    after = _fresh_versions() or versions()
    changed = {k: (before.get(k), v) for k, v in after.items() if before.get(k) != v}
    print("\nUpdated:" if changed else "\nEverything was already up to date.")
    for k, (a, b) in changed.items():
        print(f"  {k:28s} {a or '(new)'} -> {b}")


def fetch_image_models() -> None:
    from . import modelstore
    from .pipelines.images import latest, model_list
    from .settings import Settings
    ml, s = model_list(), Settings.load()
    for stage in ("detector", "binary", "order"):
        name = latest(stage, models=ml)
        for part in ml["models"][name]["files"]:
            p = modelstore.fetch(s, ml, name, part)
            print(f"  {name:32s} {part:8s} {p or '(the package fetches it itself)'}")
    print("  Species models are fetched the first time each region is used.")


def refresh_labelling() -> None:
    """Labelling (cehbio validate): newer GBIF species lists, and whether Mothbot has changed."""
    from .settings import Settings
    from .validation import gbif
    from .validation.platforms.mothbot import mothbot_status
    gbif.refresh(Settings.load())
    for line in mothbot_status():
        print("  " + line)


def show_versions() -> None:
    v = versions()
    print("Packages:")
    for k in PACKAGES:
        if k in v:
            print(f"  {k:28s} {v[k]}")
    try:
        from .pipelines.images import latest, model_list
        ml = model_list()
        print("\nNewest image models (used unless you choose another):")
        for stage in ("detector", "binary", "order"):
            n = latest(stage, models=ml)
            print(f"  {stage:9s} {n:32s} released {ml['models'][n].get('released', '?')}")
    except Exception:  # noqa: BLE001
        pass
    try:
        from .validation.platforms.mothbot import MOTHBOT
        print(f"\nMothbot packages ({MOTHBOT['format']}): checked against Mothbot Classify of "
              f"{MOTHBOT['classify']['checked']} and Mothbot Process {MOTHBOT['process']['checked']}")
    except Exception:  # noqa: BLE001
        pass
    print("\nEach run records the exact versions it used in its chunks/*_summary.json.")
