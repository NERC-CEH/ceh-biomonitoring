"""Where everything goes. One place for every folder name, so the layout is the same for every pipeline.

<outputs_root>/                       (default ~/ceh-biomonitoring-results)
    READ ME.txt
    birds/ bats/ images/              one folder per pipeline
        <project>/                    --project, or the bucket or country (or "local" for folders on disk)
            <deployment>/
                READ ME.txt           what each file is
                PROGRESS.txt          how far the run has got (updated as it goes)
                <deployment>_detections.parquet, .csv, _files.csv, _qa.json     the results
                working/              the pipeline's own files: nobody needs to open these
                    file_lists/       which files are in which chunk (+ manifest.json)
                    chunks/           each chunk's results, before they are joined
                    jobs/             cluster job scripts and their logs
                    run_params.json   the settings used
    labelling/                        cehbio validate
        <birds|bats|images>/<project>/
            1_sample/  2_for_experts/  3_answers/ (returned/ inside it: what the experts send back)
    examples/  upload_logs/

Runs made before November 2026 used <pipeline>/<place>/inference/<deployment>/ with the file lists in
<pipeline>/<place>/keys/. They are still found where they are; `cehbio tidy` moves them.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

RESERVED = {"inference", "keys", "working", "labelling", "examples", "upload_logs"}
LABELLING_STEPS = ("1_sample", "2_for_experts", "3_answers")


@dataclass(frozen=True)
class RunPaths:
    root: Path          # results live here
    working: Path
    file_lists: Path    # chunk JSONs
    manifest: Path
    chunks: Path        # per-chunk outputs
    jobs: Path          # Slurm scripts and logs
    params: Path
    legacy: bool = False

    @property
    def progress_file(self) -> Path:
        return self.root / "PROGRESS.txt"


def new_paths(outputs_root: Path, pipeline: str, place: str, deployment: str) -> RunPaths:
    root = Path(outputs_root) / pipeline / place / deployment
    w = root / "working"
    return RunPaths(root, w, w / "file_lists", w / "file_lists" / "manifest.json", w / "chunks", w / "jobs",
                    w / "run_params.json")


def old_paths(outputs_root: Path, pipeline: str, place: str, deployment: str) -> RunPaths:
    base = Path(outputs_root) / pipeline / place
    root = base / "inference" / deployment
    return RunPaths(root, root, base / "keys" / "chunks" / deployment,
                    base / "keys" / "manifests" / deployment / "manifest.json", root / "chunks", root / "slurm",
                    root / "run_params.json", legacy=True)


def run_paths(settings, pipeline: str, place: str, deployment: str) -> RunPaths:
    """The folders for one deployment's run: the old layout if that's where an existing run is."""
    if deployment in RESERVED:
        raise SystemExit(f"'{deployment}' is used for the toolkit's own folders: choose another deployment name.")
    new = new_paths(settings.outputs_root, pipeline, place, deployment)
    if new.working.exists():
        return new
    old = old_paths(settings.outputs_root, pipeline, place, deployment)
    if old.root.exists() or old.file_lists.exists():
        return old
    return new


def all_runs(outputs_root: Path) -> list[tuple[str, str, str, RunPaths]]:
    """Every run under outputs_root, new and old layouts: (pipeline, place, deployment, paths)."""
    out = []
    root = Path(outputs_root)
    if not root.exists():
        return out
    for m in sorted(root.glob("*/*/*/working/file_lists/manifest.json")):
        dep_dir = m.parents[2]
        pipe, place, dep = dep_dir.parent.parent.name, dep_dir.parent.name, dep_dir.name
        out.append((pipe, place, dep, new_paths(root, pipe, place, dep)))
    for m in sorted(root.glob("*/*/keys/manifests/*/manifest.json")):
        dep, place, pipe = m.parent.name, m.parents[3].name, m.parents[4].name
        out.append((pipe, place, dep, old_paths(root, pipe, place, dep)))
    return out


# ------------------------------------------------------------------ labelling
def labelling_dir(settings, group: str, project: str) -> Path:
    return settings.outputs_root / "labelling" / group / project


def find_labelling_project(settings, project: str, group: str | None = None) -> Path:
    base = settings.outputs_root / "labelling"
    found = [base / group / project] if group else sorted(p for p in base.glob(f"*/{project}") if p.is_dir())
    found = [p for p in found if p.is_dir()]
    if not found:
        raise SystemExit(f"No labelling project '{project}' in {base}. Start it with "
                         f"`cehbio validate sample <birds|bats|images> ... --project {project}`.")
    if len(found) > 1:
        raise SystemExit(f"'{project}' is a labelling project for {', '.join(p.parent.name for p in found)}: "
                         f"give the selection file instead.")
    return found[0]


def newest(folder: Path, pattern: str) -> Path | None:
    files = [p for p in folder.glob(pattern) if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


# ------------------------------------------------------------------ READ ME files
TOP_README = """\
CEH Biomonitoring: your results
===============================

Everything the toolkit makes goes in this folder. Your own recordings and photos are never moved or changed.

  birds/  bats/  images/   results, one folder per pipeline. Inside each: one folder per project,
                           then one folder per deployment (one recorder or trap, one place, one period).
  labelling/               cehbio validate: what experts check, the packages sent to them, their answers.
                           Inside: birds/ bats/ images/, then one folder per labelling project.
  examples/                the small example data sets (cehbio examples).
  upload_logs/             logs of uploads to UKCEH (cehbio upload).

In each deployment folder, PROGRESS.txt says how far a run has got and READ ME.txt says what each file is.
You never need to open the "working" folders: they hold the pipeline's own files.

To see every run and how far it has got:   cehbio status
"""

RUN_README = """\
{pipeline}: {deployment}  ({place})
{line}

PROGRESS.txt                       how far the run has got (updated as it runs)
{deployment}_detections.csv          the results: one row per detection. Opens in Excel
{deployment}_detections.parquet      the same results, smaller and faster (R: arrow::read_parquet; Python: pandas)
{deployment}_files.csv               every file, and whether it had detections, none, or failed
{deployment}_qa.json                 checks: did every part finish, how many files failed
working/                          the pipeline's own files (file lists, each part's results, job logs,
                                  the settings and model versions used). You don't need to open it.

The results files appear when the run has finished. See the {pipeline} guide for what each column means:
https://github.com/NERC-CEH/ceh-biomonitoring/blob/main/docs/{pipeline}.md
"""

LABELLING_README = """\
Labelling: {project}  ({group})
{line}

Work through the folders in order:

  1_sample/        what the experts will check  (cehbio validate sample ... --project {project})
  2_for_experts/   the packages to send them    (cehbio validate prepare --project {project})
  3_answers/       their answers, next to what the model said  (cehbio validate collect --project {project})
    returned/      put the packages or sheets the experts send back in here

Each step uses the newest file from the step before, unless you name one.
"""


def write_once(path: Path, text: str) -> None:
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    except OSError:
        pass     # a read-only results folder must never stop a run


def readme_top(settings) -> None:
    write_once(settings.outputs_root / "READ ME.txt", TOP_README)


def readme_run(paths: RunPaths, pipeline: str, place: str, deployment: str) -> None:
    title = f"{pipeline}: {deployment}  ({place})"
    write_once(paths.root / "READ ME.txt", RUN_README.format(pipeline=pipeline, deployment=deployment,
                                                             place=place, line="=" * len(title)))


def readme_labelling(folder: Path, group: str, project: str) -> None:
    title = f"Labelling: {project}  ({group})"
    write_once(folder / "READ ME.txt", LABELLING_README.format(project=project, group=group,
                                                               line="=" * len(title)))
    for step in LABELLING_STEPS:
        (folder / step).mkdir(parents=True, exist_ok=True)
    (folder / "3_answers" / "returned").mkdir(exist_ok=True)
