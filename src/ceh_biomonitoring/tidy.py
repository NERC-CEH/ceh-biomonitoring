"""Move results made before November 2026 into the new folder layout.

Before, a run's results were in <pipeline>/<place>/inference/<deployment>/ and its file lists in
<pipeline>/<place>/keys/. Now everything for a deployment is in one folder, <pipeline>/<place>/<deployment>/,
with the pipeline's own files in working/ inside it (see `cehbio status` and the READ ME in your results folder).

`cehbio tidy` lists every move first and only moves after you say yes. Nothing is deleted: only folders
left empty by the moves are removed. A deployment that already has a new-layout folder is left alone.
Runs still going on a cluster are skipped: tidy them when they have finished.

If your results are in the old default folder (~/ceh-biomonitoring/outputs, often inside the code folder),
tidy offers to move the whole folder to ~/ceh-biomonitoring-results first.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import layout, progress
from .settings import NEW_DEFAULT_OUTPUTS

def plan_run(root: Path, pipe: str, place: str, dep: str) -> tuple[list[tuple[Path, Path]], str | None]:
    """The moves for one old-layout run, or why it's skipped."""
    old, new = layout.old_paths(root, pipe, place, dep), layout.new_paths(root, pipe, place, dep)
    if new.root.exists():
        return [], f"{new.root} already exists"
    info = progress.run_progress(old)
    if info["state"].startswith(("running", "waiting")):
        return [], "still running"
    moves = []
    if old.root.exists():
        for f in sorted(old.root.iterdir()):
            if f.name == "chunks":
                moves.append((f, new.chunks))
            elif f.name == "slurm":
                moves.append((f, new.jobs))
            elif f.name == "run_params.json":
                moves.append((f, new.params))
            else:                                      # results, and anything else people put there
                moves.append((f, new.root / f.name))
    if old.file_lists.exists():
        moves += [(f, new.file_lists / f.name) for f in sorted(old.file_lists.iterdir())]
    if old.manifest.exists():
        moves.append((old.manifest, new.manifest))
    return moves, None


def _remove_empty(folder: Path, stop: Path) -> None:
    while folder != stop and folder.exists() and not any(folder.iterdir()):
        folder.rmdir()
        folder = folder.parent


def _ask(question: str, yes: bool) -> bool:
    if yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        print("(No answer possible here: nothing moved. Add --yes to move without asking.)")
        return False


def tidy(settings, yes: bool = False) -> None:
    root = settings.outputs_root
    if settings.get("_old_default"):
        dest = Path(NEW_DEFAULT_OUTPUTS).expanduser()
        print(f"Your results are in the old default folder:\n  {root}\nThe new default is:\n  {dest}\n")
        if dest.exists():
            print(f"{dest} already exists, so the folder is left where it is. Move what you need by hand.")
        elif _ask("Move the whole folder there?", yes):
            shutil.move(str(root), str(dest))
            _remove_empty(root.parent, Path.home())
            print(f"Moved. Your results are now in {dest}\n")
            root = dest
        else:
            print("Left where it is.\n")
    old_runs = [(pipe, place, dep) for pipe, place, dep, rp in layout.all_runs(root) if rp.legacy]
    # old runs whose file lists have gone but whose results remain
    for d in sorted(root.glob("*/*/inference/*")):
        key = (d.parents[2].name, d.parents[1].name, d.name)
        if d.is_dir() and key not in old_runs:
            old_runs.append(key)
    if not old_runs:
        print(f"Nothing to tidy in {root}: every run is in the new layout.")
        return
    plans, skipped = [], []
    for pipe, place, dep in old_runs:
        moves, why = plan_run(root, pipe, place, dep)
        (skipped.append((pipe, place, dep, why)) if why else plans.append((pipe, place, dep, moves)))
    for pipe, place, dep, moves in plans:
        print(f"{pipe} / {place} / {dep}  ->  {root / pipe / place / dep}")
        for src, dst in moves:
            print(f"    {src.relative_to(root)}  ->  {dst.relative_to(root)}")
    for pipe, place, dep, why in skipped:
        print(f"{pipe} / {place} / {dep}: left alone ({why})")
    if not plans:
        return
    print(f"\n{len(plans)} runs to move. Your own scripts that point at the old folders will need the new paths.")
    if not _ask("Move them?", yes):
        print("Nothing moved.")
        return
    for pipe, place, dep, moves in plans:
        for src, dst in moves:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        new = layout.new_paths(root, pipe, place, dep)
        if new.manifest.exists():                      # keep the manifest's note of where the lists are
            m = json.loads(new.manifest.read_text())
            m["chunk_dir"] = str(new.file_lists)
            new.manifest.write_text(json.dumps(m, indent=2))
        old = layout.old_paths(root, pipe, place, dep)
        for f in (old.root, old.file_lists, old.manifest.parent):
            _remove_empty(f, root)
        layout.readme_run(new, pipe, place, dep)
        progress.write_progress_file(new, pipe, place, dep, f" --project {place}")
    layout.readme_top(settings if root == settings.outputs_root else type(settings)(
        profile=settings.profile, values={**settings.values, "outputs_root": str(root)}))
    print(f"Done: {len(plans)} runs moved. `cehbio status` shows them all.")


def add_command(sub, common) -> None:
    import argparse
    t = sub.add_parser("tidy", parents=[common], help="move results made before Nov 2026 into the new folders",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    t.add_argument("--yes", action="store_true", help="move without asking (it still lists everything first)")

    def go(a):
        from .settings import Settings
        tidy(Settings.load(getattr(a, "profile", None)), a.yes)
    t.set_defaults(func=go)
