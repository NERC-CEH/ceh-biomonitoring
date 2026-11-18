"""Manual validation: choosing results for experts to check, packaging them for the platform they use,
and reading their answers back. Works the same for birds, bats and images, on any machine.

  1. SAMPLE   what to check, for one of these purposes (sampling.py has the rules):
                site-lists  per site: confirm or reject each species on the site's list
                model       across all sites of one country: examples to test or retrain its model
                all         everything (e.g. every crop of a deployment)
              cehbio validate sample images --for site-lists results/dep000145 --out sel/sg_sites
              cehbio validate sample images --for model results/* --country Singapore --exclude sel/sg_sites.csv --out sel/sg_model_r1

  2. PREPARE  package a selection for a platform (platforms/): audio-clips (birds, bats), mothbot (images)
              cehbio validate prepare sel/sg_sites.csv --out to_experts/

  3. COLLECT  the experts' answers, next to what the model said
              cehbio validate collect sel/sg_sites.csv to_experts/ --out answers/sg_sites.csv

Add --slurm to sample or prepare to run it as a batch job on a cluster (JASMIN, Polar, ...).
"""
from __future__ import annotations

import argparse
import sys
from importlib import import_module
from pathlib import Path

from .sampling import PURPOSES
from .units import GROUPS


def _slurm(a, step: str, gpu: bool) -> bool:
    """With --slurm: write and submit a job that runs this same command, then stop."""
    if not getattr(a, "slurm", False):
        return False
    from ..settings import Settings
    from .. import slurm
    s = Settings.load(getattr(a, "profile", None))
    argv = [x for x in sys.argv[1:] if x != "--slurm"]
    name = f"validate_{step}_{Path(a.out).stem}"
    script = slurm.write_command_job(s, name, argv, Path(a.out).resolve().parent / "slurm", use_gpu=gpu)
    print(f"Job script: {script}\nSubmitted: job {slurm.submit(script)}")
    return True


def _warm_species_cache(a) -> None:
    """Before a batch job: fetch the GBIF species lists here, where there's internet, so the job finds
    them in the cache."""
    import pandas as pd
    from ..settings import Settings
    try:
        sel = pd.read_csv(a.selection, low_memory=False)
        if str(sel["group"].iloc[0]) != "images":
            return
        from .platforms import mothbot as M
        print("Fetching the GBIF species lists for the job ...", flush=True)
        groups = [sel] if a.one_package else [d for _, d in sel.groupby("deployment_id", sort=True)]
        for rows in groups:
            M.species_for(rows, Settings.load(getattr(a, "profile", None)), a.species_list, a.species_taxon, False, "",
                          with_global=a.blind is False)
    except Exception as e:  # noqa: BLE001 - the job will still try itself
        print(f"  (couldn't fetch them now: {e})", flush=True)


def add_command(sub, common) -> None:
    p = sub.add_parser("validate", help="choose results for experts to check, package them, read answers back",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    vsub = p.add_subparsers(dest="step", required=True)

    # ------------------------------------------------------------------ sample
    s = vsub.add_parser("sample", parents=[common], help="choose what experts check",
                        formatter_class=argparse.RawDescriptionHelpFormatter,
                        description=import_module(".sampling", __name__).__doc__ + "\n"
                        + import_module(".units", __name__).__doc__)
    s.add_argument("group", choices=list(GROUPS))
    s.add_argument("inputs", nargs="+", help="results folders (from cehbio run) or their .parquet files, "
                                            "any number of deployments")
    s.add_argument("--for", dest="purpose", required=True, choices=PURPOSES)
    s.add_argument("--out", required=True, help="file name for the selection (.csv, plus _record.json)")
    s.add_argument("--per-species", type=int,
                   help="site-lists: per species per site (birds, bats 2; images 3); model: per species per "
                        "country (birds, bats 50; images 100)")
    s.add_argument("--how", choices=["best", "spread"],
                   help="site-lists: best (best unit, then best on another day) or spread (over the score range "
                        "and time). Default: best for birds and bats, spread for images")
    s.add_argument("--species-table", nargs="*",
                   help="site-lists: CSVs of the species to check per site (columns species, and site and listed "
                        "if they have them), e.g. bird-results' <site>_site_species.csv")
    s.add_argument("--exclude", nargs="*", help="earlier selection CSVs: their units aren't chosen again")
    s.add_argument("--reserve", type=int, default=0,
                   help="spare units per species (and site), used if a platform drops a pick (e.g. Mothbot screens)")
    s.add_argument("--no-unusual-months", action="store_true",
                   help="don't add species detected in a month their species list marks unlikely")
    s.add_argument("--noise", type=int, help="images, site-lists: non-moth insects per deployment (default 100)")
    s.add_argument("--country", help="model: the country these results are from, if the results don't say. "
                                     "Each country (species model) gets its own selection")
    s.add_argument("--max-gap", type=float, help="birds, bats: seconds of quiet that end an event or pass "
                                                 "(birds 60, bats 1)")
    s.add_argument("--min-crop-area", type=float, help="images: leave out smaller crops (pixels)")
    s.add_argument("--max-crop-area", type=float, help="images: leave out larger crops (pixels)")
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--slurm", action="store_true", help="run as a batch job on this machine's cluster")

    def run_sample(a):
        if _slurm(a, "sample", gpu=False):
            return
        from ..settings import Settings
        from . import sampling as S
        from . import units as U
        settings = Settings.load(getattr(a, "profile", None))
        units = U.load(a.inputs, a.group, a.max_gap, per_crop=a.purpose == "all",
                       min_crop_area=a.min_crop_area, max_crop_area=a.max_crop_area)
        excl = S.excluded_units(a.exclude)
        if a.purpose == "site-lists":
            sel = S.site_lists(units, a.group, a.per_species, a.how, not a.no_unusual_months, a.noise, a.seed,
                               excl, S.species_table(a.species_table), a.reserve)
        elif a.purpose == "model":
            sel = S.model(units, a.group, a.per_species, excl, a.country, settings, a.reserve)
        else:
            sel = S.everything(units, a.group, excl)
        record = {"group": a.group, "purpose": a.purpose, "inputs": a.inputs, "units_available": len(units),
                  "per_species": a.per_species, "how": a.how, "species_tables": a.species_table or [],
                  "excluded_selections": a.exclude or [], "excluded_units": len(excl), "reserve": a.reserve,
                  "seed": a.seed, "unusual_months": not a.no_unusual_months, "max_gap_s": a.max_gap,
                  "crop_area": [a.min_crop_area, a.max_crop_area]}
        # a model sample is one per species model (country): never one file across countries
        parts = ([(g, d) for g, d in sel.groupby("model_group")] if a.purpose == "model" and len(sel)
                 and sel["model_group"].nunique() > 1 else [(None, sel)])
        from .platforms import DEFAULT_FOR
        for g, d in parts:
            out = Path(a.out) if g is None else Path(str(Path(a.out).with_suffix("")) + f"_{g}")
            f, _ = S.write(d, out, {**record, "model_group": g if g is not None else (
                d["model_group"].iloc[0] if a.purpose == "model" and len(d) else None)})
            main = d[~d["reserve"].fillna(False).astype(bool)] if len(d) else d
            print(f"{len(main)} units ({len(d) - len(main)} spare), {main['species'].nunique() if len(main) else 0} "
                  f"species, {main['site'].nunique() if len(main) else 0} sites -> {f}")
            print(f"Next: cehbio validate prepare {f} --platform {DEFAULT_FOR[a.group]} --out <folder>")
    s.set_defaults(func=run_sample)

    # ------------------------------------------------------------------ prepare
    from .platforms import DEFAULT_FOR, PLATFORMS
    q = vsub.add_parser("prepare", parents=[common], help="package a selection for a labelling platform",
                        description=import_module(".platforms", __name__).__doc__,
                        formatter_class=argparse.RawDescriptionHelpFormatter)
    q.add_argument("selection", help="a selection CSV from cehbio validate sample")
    q.add_argument("--platform", choices=list(PLATFORMS), help="default: audio-clips (birds, bats), mothbot (images)")
    q.add_argument("--out", required=True, help="folder for the package(s)")
    q.add_argument("--bucket", help="object-store bucket the recordings or photos are in, if the results don't say")
    q.add_argument("--source-root", help="a folder holding the recordings or photos (searched by file name)")
    q.add_argument("--blind", dest="blind", action="store_true", default=None,
                   help="hide the models' identifications from the expert (default: audio model selections, and "
                        "all Mothbot packages; --no-blind shows them)")
    q.add_argument("--no-blind", "--show-machine-ids", dest="blind", action="store_false",
                   help="show them: Mothbot gets each model's identification in its machine-ID format")
    q.add_argument("--species-list", help="mothbot: your own species list for the package (a GBIF species-list "
                                          "download, or any CSV with a species column). Default: GBIF's list for "
                                          "the country plus every species the models named, on the GBIF backbone")
    q.add_argument("--no-species-list", action="store_true", help="mothbot: don't add a species list")
    q.add_argument("--species-taxon", default="Lepidoptera",
                   help="mothbot: the group the country list covers (default Lepidoptera; e.g. Insecta)")
    q.add_argument("--offline", action="store_true",
                   help="mothbot: don't ask GBIF, use only what's cached (compute nodes without internet)")
    q.add_argument("--clip-seconds", type=float, help="audio-clips: clip length (birds 30; bats: the pass)")
    q.add_argument("--pad-seconds", type=float, default=1.0, help="audio-clips, bats: added either side of a pass")
    q.add_argument("--screen", nargs="*", default=[], help="mothbot: reference .npz files of things to leave out "
                                                           "(also the validation.screens setting)")
    q.add_argument("--no-cluster", action="store_true", help="mothbot: don't group similar crops")
    q.add_argument("--cluster-method", choices=["leaf", "eom"], default="leaf",
                   help="mothbot: leaf (many small, tight clusters; default) or eom (fewer, larger)")
    q.add_argument("--min-cluster-size", type=int, default=3)
    q.add_argument("--one-package", action="store_true", help="mothbot: one package for all deployments")
    q.add_argument("--keep-unzipped", action="store_true", help="mothbot: keep the package folder as well as the .zip")
    q.add_argument("--slurm", action="store_true", help="run as a batch job (on a GPU if the machine has one)")

    def run_prepare(a):
        import pandas as pd
        if getattr(a, "slurm", False) and not a.no_species_list and not a.offline:
            _warm_species_cache(a)                         # compute nodes may have no internet
        if _slurm(a, "prepare", gpu=True):
            return
        from ..settings import Settings
        sel = pd.read_csv(a.selection, low_memory=False)
        if sel.empty:
            raise SystemExit(f"{a.selection} has no units, so there is nothing to package. "
                             f"(Often because --exclude already took everything there was.)")
        group = str(sel["group"].iloc[0])
        platform = a.platform or DEFAULT_FOR[group]
        mod = import_module(PLATFORMS[platform])
        if group not in mod.GROUPS:
            raise SystemExit(f"{platform} is for {', '.join(mod.GROUPS)}; this selection is {group}")
        res = mod.prepare(sel, Path(a.out), settings=Settings.load(getattr(a, "profile", None)), blind=a.blind,
                          bucket=a.bucket, source_root=a.source_root, clip_seconds=a.clip_seconds,
                          pad_seconds=a.pad_seconds, screens=a.screen, cluster=not a.no_cluster,
                          cluster_method=a.cluster_method, min_cluster_size=a.min_cluster_size,
                          one_package=a.one_package, keep_unzipped=a.keep_unzipped,
                          species_list="none" if a.no_species_list else a.species_list,
                          species_taxon=a.species_taxon, offline=a.offline)
        print(f"\nDone: {res}")
        print(f"When the experts are finished: cehbio validate collect {a.selection} {a.out} --out <answers.csv>")
    q.set_defaults(func=run_prepare)

    # ------------------------------------------------------------------ collect
    c = vsub.add_parser("collect", parents=[common], help="the experts' answers, next to what the model said",
                        description=import_module(".collect", __name__).__doc__,
                        formatter_class=argparse.RawDescriptionHelpFormatter)
    c.add_argument("selection", help="the selection CSV the packages were made from")
    c.add_argument("returned", nargs="+", help="Mothbot packages (folders or .zip) or audio sheets sent back")
    c.add_argument("--out", required=True, help="CSV for the answers")

    def run_collect(a):
        import pandas as pd
        from . import collect as K
        sel = pd.read_csv(a.selection, low_memory=False)
        paths = [Path(x) for x in a.returned]
        if all(p.suffix == ".csv" for p in paths):
            res = pd.concat([K.audio(p) for p in paths], ignore_index=True)
        else:
            res = K.mothbot(sel, [p for p in paths if p.suffix != ".csv"])
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        res.to_csv(a.out, index=False)
        judged = res["agrees"].dropna() if "agrees" in res.columns else []
        print(f"{len(res)} answers -> {a.out}" + (f"; the model agrees with the expert on {int(judged.sum())} of "
                                                   f"{len(judged)} species identifications" if len(judged) else ""))
    c.set_defaults(func=run_collect)

    # ------------------------------------------------------------------ check, reference
    k = vsub.add_parser("check", parents=[common], help="check Mothbot package folders open correctly")
    k.add_argument("packages", nargs="+")

    def run_check(a):
        from .platforms.mothbot import check
        bad = 0
        for p in a.packages:
            probs = check(Path(p))
            bad += bool(probs)
            print(f"{'OK     ' if not probs else 'PROBLEM'} {p}" + "".join(f"\n        {x}" for x in probs))
        if bad:
            raise SystemExit(1)
    k.set_defaults(func=run_check)

    r = vsub.add_parser("reference", parents=[common], help="make a screen from example crops (e.g. geckos)",
                        description=import_module(".embeddings", __name__).__doc__,
                        formatter_class=argparse.RawDescriptionHelpFormatter)
    r.add_argument("crops", help="a folder of example crops (.jpg/.png) of the thing to leave out")
    r.add_argument("--name", required=True, help="what it is, e.g. gecko")
    r.add_argument("--out", required=True, help="the reference file to write (.npz)")
    r.add_argument("--threshold", type=float, help="distance below which a crop is screened out "
                                                   "(default: the distance that takes in 95%% of the examples)")

    def run_reference(a):
        from ..settings import Settings
        from .embeddings import build_reference
        files = sorted(f for f in Path(a.crops).rglob("*") if f.suffix.lower() in (".jpg", ".jpeg", ".png"))
        if not files:
            raise SystemExit(f"No .jpg or .png crops in {a.crops}")
        res = build_reference(files, a.name, Path(a.out), Settings.load(getattr(a, "profile", None)), a.threshold)
        print(", ".join(f"{k}: {v}" for k, v in res.items()))
        print(f"Use it with: cehbio validate prepare <selection> --screen {a.out}   (or add it to validation.screens)")
    r.set_defaults(func=run_reference)
