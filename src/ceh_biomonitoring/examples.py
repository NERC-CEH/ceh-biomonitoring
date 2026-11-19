"""Small example data for trying each pipeline, and a one-line check that it works.

    cehbio examples                     list the example sets
    cehbio examples run birds           get the files, run the pipeline on this machine, check the result
    cehbio examples run all             every installed pipeline
    cehbio examples get images          just get the files (prints where they are)

The files and their licences are listed in examples.yml (and examples/README.md). Files in this
repository are used from there; others are downloaded once and kept in <outputs>/examples/<pipeline>.
Every file is checked against its sha256.
"""
from __future__ import annotations

import hashlib
import shutil
import urllib.request
from pathlib import Path

import yaml

MANIFEST = Path(__file__).with_name("examples.yml")
REPO_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"     # present in a git clone


def manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def get(pipeline: str, settings) -> Path:
    """The folder holding the pipeline's example files, all present and checked."""
    m = manifest()
    if pipeline not in m:
        raise SystemExit(f"No examples for '{pipeline}'. There are: {', '.join(m)}")
    dest = settings.outputs_root / "examples" / pipeline / "data"
    dest.mkdir(parents=True, exist_ok=True)
    listed = {f["name"] for f in m[pipeline]["files"]}
    for old in dest.iterdir():                 # files from an earlier version of the examples
        if old.is_file() and old.name not in listed:
            old.unlink()
    for f in m[pipeline]["files"]:
        target = dest / f["name"]
        if target.exists() and _sha(target) == f["sha256"]:
            continue
        local = REPO_EXAMPLES / pipeline / f["name"]
        if f.get("in_repo") and local.exists():
            shutil.copyfile(local, target)
        else:
            print(f"Downloading {f['name']} ...", flush=True)
            with urllib.request.urlopen(f["url"], timeout=120) as r, open(target, "wb") as out:
                shutil.copyfileobj(r, out)
        if _sha(target) != f["sha256"]:
            target.unlink()
            raise SystemExit(f"{f['name']} doesn't match its checksum: the source may have changed. Tell the maintainers.")
    return dest


def check(pipeline: str, det, expect: dict) -> tuple[bool, str]:
    n = len(det)
    if n < expect.get("min_detections", 1):
        return False, f"only {n} detections (expected at least {expect.get('min_detections', 1)})"
    msg = f"{n} detections"
    species_col = next((c for c in ("species_name", "regional_species_rank_1_name") if c in det.columns), None)
    if species_col:
        found = sorted(det[species_col].dropna().astype(str).unique())
        msg += f"; species: {', '.join(found[:8])}{' ...' if len(found) > 8 else ''}"
        wanted = expect.get("any_species")
        if wanted and not {" ".join(s.split()[:2]).lower() for s in found} & {s.lower() for s in wanted}:
            return False, msg + f" (expected at least one of: {', '.join(wanted)})"
    if "track_id" in det.columns:
        msg += f"; {det['track_id'].nunique()} tracks"
    return True, msg


def fingerprint(pipeline: str, extra: list[str] = ()) -> str:
    """Short id of the example files and run options: when they change, the example runs afresh
    instead of reusing results from the old files."""
    m = manifest()[pipeline]
    text = "|".join(sorted(f["sha256"] for f in m["files"])) + "|" + " ".join([*m.get("run", []), *extra])
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def run(pipeline: str, settings, extra: list[str], profile: str | None = None) -> bool:
    import pandas as pd
    import subprocess
    import sys
    from . import pipelines, runner
    p = pipelines.get(pipeline)
    try:
        p.check_installed()
    except SystemExit as e:
        print(f"{pipeline}: not installed here, skipped ({e})")
        return True
    folder = get(pipeline, settings)
    dep = f"example-{pipeline}-{fingerprint(pipeline, extra)}"
    print(f"\n=== {pipeline}: {manifest()[pipeline]['about']}\n    files: {folder}", flush=True)
    # each example in its own process: the pipelines' libraries (TensorFlow, numba, torch) each bring
    # their own LLVM, and loading them all into one process crashes
    subprocess.run([sys.executable, "-m", "ceh_biomonitoring", "run", pipeline, "--folder", str(folder),
                    "--project", "examples", "--deployment", dep, "--here", *(["--profile", profile] if profile else []),
                    *manifest()[pipeline].get("run", []), *extra], check=False)
    out = runner.deployment_dir(settings, p, "examples", dep) / f"{dep}_{p.output_name}.parquet"
    det = pd.read_parquet(out) if out.exists() else pd.DataFrame()
    ok, msg = check(pipeline, det, manifest()[pipeline].get("expect", {}))
    print(f"\n{'PASS' if ok else 'PROBLEM'} {pipeline}: {msg}\n    results: {out.parent}")
    return ok


def add_command(sub, common) -> None:
    import argparse
    p = sub.add_parser("examples", parents=[common], help="try each pipeline on small example data",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", nargs="?", choices=["list", "get", "run"], default="list")
    p.add_argument("pipeline", nargs="?", default="all", help="birds, bats, images, or all (default)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="a pipeline setting for the run, e.g. --set model=perch")

    def go(a):
        from .settings import Settings
        m = manifest()
        names = list(m) if a.pipeline == "all" else [a.pipeline]
        if a.action == "list":
            for n in m:
                lic = sorted({f["licence"] for f in m[n]["files"]})
                print(f"{n:8s} {len(m[n]['files'])} files  {m[n]['about']}\n         licences: {'; '.join(lic)}")
            print("\nRun one: cehbio examples run <pipeline>   (credits: examples/README.md)")
            return
        s = Settings.load(getattr(a, "profile", None))
        if a.action == "get":
            for n in names:
                print(f"{n}: {get(n, s)}")
            return
        extra = [x for kv in a.set for x in ("--set", kv)]
        results = {n: run(n, s, extra, getattr(a, "profile", None)) for n in names}
        if not all(results.values()):
            raise SystemExit("Some examples didn't give the expected result: see PROBLEM above.")
    p.set_defaults(func=go)
