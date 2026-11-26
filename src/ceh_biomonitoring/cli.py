"""cehbio: one command for every pipeline.

  cehbio pipelines                         which pipelines exist, and which are installed
  cehbio check                             settings, credentials and object-store access
  cehbio run bats --folder E:/cards/wood-1 --project my-woods --deployment wood-1
                                           list files, split them into parts, send them to the cluster
                                           (or run them here if this machine has no Slurm)
  cehbio status                            every run, and how far it has got
  cehbio status bats --project my-woods --deployment wood-1 --watch
  cehbio combine bats --project my-woods --deployment wood-1
  cehbio tidy                              move results made before Nov 2026 into the new folders

Settings for a run go in a YAML file (--config) or on the command line (--set key=value).
See `cehbio <command> --help` for details.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")   # hide TensorFlow's start-up chatter
from pathlib import Path

import yaml

from importlib import metadata

from . import __version__, chunks, countries, devices, layout, objectstore, pipelines, progress, runner, slurm
from .settings import USER_SETTINGS, Settings


def _settings(args) -> Settings:
    return Settings.load(profile=getattr(args, "profile", None))


def _device(pipeline, args) -> dict | None:
    if not getattr(args, "device", None):
        return None
    d = devices.get(args.device)
    devices.check_compatible(d, pipeline)
    return d


def config_path(spec: str) -> Path:
    """A settings file: a path, or pkg:<package>/<file> for one shipped in an installed package
    (e.g. a plug-in's tuned settings)."""
    if str(spec).startswith("pkg:"):
        from importlib import resources
        pkg, _, rel = str(spec)[4:].partition("/")
        return Path(str(resources.files(pkg).joinpath(rel)))
    return Path(spec).expanduser()


def _params(pipeline, args, device: dict | None = None) -> dict:
    """pipeline defaults < machine/team settings (pipeline_defaults.<name>) < device < --config < --set"""
    over: dict = dict((_settings(args).get(f"pipeline_defaults.{pipeline.name}") or {}))
    over.update(devices.pipeline_params(device, pipeline.name) if device else {})
    if getattr(args, "config", None):
        cfg = yaml.safe_load(config_path(args.config).read_text(encoding="utf-8")) or {}
        over.update(cfg.get(pipeline.name, cfg))
    for item in getattr(args, "set", None) or []:
        k, _, v = item.partition("=")
        over[k.strip()] = yaml.safe_load(v)
    unknown = sorted(set(over) - set(pipeline.defaults))
    if unknown:
        raise SystemExit(f"Unknown setting(s) for {pipeline.name}: {', '.join(unknown)}. "
                         f"Known: {', '.join(sorted(pipeline.defaults))}")
    return pipeline.params(over)


# ---------------------------------------------------------------------------- commands
def cmd_pipelines(args):
    print(f"ceh-biomonitoring {__version__}\n")
    for name, title, extra, ok, msg in pipelines.available():
        mark = "installed" if ok else f'not installed: run the installer again with {extra}, or in R cehbio_install("{extra}")'
        print(f"  {name:10s} {title}\n  {'':10s} [{mark}]\n")


def cmd_upload(args):
    from . import upload
    upload.run(args, _settings(args))


def cmd_devices(args):
    print("Devices (use with --device):\n")
    for name, d in sorted(devices.available().items()):
        mask = ("  needs a mask per deployment" if d.get("needs_mask") else
                "  ring light found in the photos" if (d.get("params") or {}).get("images", {}).get("ring_light") else "")
        print(f"  {name:12s} {d.get('title', '')}\n  {'':12s} [{d.get('media', '?')}]{mask}\n")


def cmd_check(args):
    s = _settings(args)
    print(f"Machine profile : {s.profile}")
    print(f"Settings file   : {USER_SETTINGS} ({'found' if USER_SETTINGS.exists() else 'not used'})")
    print(f"Results folder  : {s.outputs_root}")
    if s.get("_old_default"):
        print("  NOTE: this is the old default folder, inside ~/ceh-biomonitoring (where the code often is). "
              "`cehbio tidy` moves it to ~/ceh-biomonitoring-results.")
    print(f"Temporary files : {s.tmp_root}")
    print(f"Slurm           : {'yes' if s.get('slurm.enabled') else 'no (chunks run on this machine)'}")
    if s.get("slurm.enabled") and not s.get("slurm.account") and s.profile == "jasmin":
        print(f"  NOTE: set your JASMIN Slurm account in {USER_SETTINGS}:\n        slurm:\n          account: <your account>")
    if "scratch" in str(s.outputs_root):
        print(f"  NOTE: results are going to scratch, which JASMIN clears. Set outputs_root in {USER_SETTINGS}.")
    print(f"Credentials     : {objectstore.credentials_path(s)}")
    ok, msg = objectstore.check_access(s, args.bucket)
    print(f"Object store    : {'OK, ' if ok else 'PROBLEM: '}{msg}")
    for name, title, extra, inst, _ in pipelines.available():
        print(f"Pipeline {name:7s}: {'installed' if inst else 'not installed'}")
    sys.exit(0 if ok else 1)


def _where(s, args, need_source: bool = True) -> dict:
    """Country row, a project bucket, or a local folder. Sets args.country to the output folder name.
    status/combine only read results, so with no place given they look at local-folder runs."""
    folder = getattr(args, "folder", None)
    if not args.country and not args.bucket and not folder:
        if need_source:
            raise SystemExit("Give --folder (files on disk) or --bucket (an object-store bucket).")
        folder = "local"
    if folder or (args.country == "local" and not args.bucket):
        name = args.country or "local"
        c = {"country_name": name, "country_folder": name, "bucket_code": "local"}
    elif args.bucket:
        folder = args.country or args.bucket
        c = {"country_name": folder, "country_folder": folder, "bucket_code": args.bucket}
    else:
        c = countries.get(s, args.country)
    args.country = c["country_folder"]
    args.place = getattr(args, "project", None) or c["country_folder"]
    return c


def _place_args(args, c) -> str:
    """The options that find this run again, for the 'next step' hints."""
    if getattr(args, "project", None):
        return f" --project {args.project}"
    if c.get("bucket_code") == "local":
        return f" --project {args.place}" if args.place != "local" else ""
    if args.bucket:
        return f" --bucket {args.bucket}" + (f" --country {args.country}" if args.country != args.bucket else "")
    return f" --country {args.country}"


def list_local(folder: Path, extensions, max_files=None) -> list[str]:
    exts = {e.lower() for e in extensions}
    files = sorted(str(p.resolve()) for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in exts)
    return files[:max_files] if max_files else files


def _make_keys(s, p, place, deployment, args, c, device=None) -> list[Path]:
    rp = runner.paths(s, p, place, deployment)
    existing = sorted(f for f in rp.file_lists.glob("*.json") if f.name != "manifest.json")
    if existing:
        print(f"Carrying on with the {len(existing)} parts already listed in {rp.file_lists}")
        return existing
    exts = tuple(device.get("extensions") or p.extensions) if device else p.extensions
    extra = {"device": device["name"]} if device else {}
    if getattr(args, "project", None):
        extra["project"] = args.project
    if getattr(args, "timestamp_pattern", None):
        extra["timestamp_pattern"] = args.timestamp_pattern
    sample = None
    if getattr(args, "folder", None):
        folder = Path(args.folder)
        if not folder.is_dir():
            raise SystemExit(f"Folder not found: {folder}")
        print(f"Listing {folder} ...", flush=True)
        keys = list_local(folder, exts, args.max_files)
        data_type, extra["source"], extra["folder"] = "local", "local", str(folder.resolve())
        if not keys:
            raise SystemExit(f"No {', '.join(exts)} files in {folder}")
    else:
        data_type = args.data_type or (device or {}).get("data_type") or p.data_type
        prefix = f"{deployment}/{data_type}/"
        print(f"Listing s3://{c['bucket_code']}/{prefix} ...", flush=True)
        keys = objectstore.list_keys(objectstore.client(s), c["bucket_code"], prefix, exts,
                                     max_keys=args.max_files,
                                     progress=lambda d: print(f"  {d['matching_keys']} files found", flush=True))
        if not keys:
            raise SystemExit(f"No {', '.join(exts)} files under s3://{c['bucket_code']}/{prefix}")
    if device or extra.get("timestamp_pattern"):
        sample = devices.parse_filename(keys[0], device, extra.get("timestamp_pattern"))
        if sample["file_datetime"]:
            print(f"Date/time from file names, e.g. {Path(keys[0]).name} -> {sample['file_datetime']}"
                  + (f" (device {sample['device_serial']})" if sample["device_serial"] else ""))
        else:
            print(f"WARNING: could not read a date/time from {Path(keys[0]).name}. "
                  f"Give the pattern with --timestamp-pattern, e.g. \"SERIAL-YYYYMMDDThhmmss\".")
    per = args.files_per_chunk or p.files_per_chunk or s.get("chunking.files_per_chunk", 100)
    groups = p.group_files(keys, device, extra.get("timestamp_pattern"))
    paths = chunks.write_chunks(rp.file_lists, c, deployment, keys, per, p.key_field, data_type, extra,
                                groups=groups, manifest=rp.manifest)
    print(f"{len(keys)} files -> {len(paths)} parts" + (f" ({len(groups)} nights, never split)" if groups else ""))
    return paths


def cmd_run(args):
    s = _settings(args)
    p = pipelines.get(args.pipeline)
    p.check_installed()
    device = _device(p, args)
    params = _params(p, args, device)
    c = _where(s, args)
    place, dep = args.place, args.deployment
    rp = runner.paths(s, p, place, dep)
    if rp.legacy:
        print(f"(This run is in the old folder layout, {rp.root}. `cehbio tidy` moves it.)")
    layout.readme_top(s)
    paths = _make_keys(s, p, place, dep, args, c, device)
    runner.save_run_params(s, p, place, dep, params)
    if not rp.legacy:
        layout.readme_run(rp, p.name, place, dep)
    where = _place_args(args, c)
    print("Settings:", json.dumps(params))
    print(f"Results folder: {rp.root}")
    if not s.get("slurm.enabled") or args.here:
        print(f"Running {len(paths)} parts on this machine, one after another. "
              f"If it stops, run the same command again: finished parts are kept.\n")
        for i, chunk in enumerate(paths, 1):
            runner.run_chunk(s, p, chunk, params, keep_temp=args.keep_temp)
            print(f"[{i}/{len(paths)}] " + progress.summary_line(progress.run_progress(rp, check_slurm=False)),
                  flush=True)
        _finished(runner.combine(s, p, place, dep), rp, dep)
        return
    gpu = True if args.gpu else False if args.cpu else None
    script = slurm.write_job(s, p, place, dep, paths, rp.jobs, use_gpu=gpu)
    if args.dry_run:
        print(f"Job script written (not submitted): {script}\n")
        print(script.read_text())
        return
    job = slurm.submit(script)
    record = {"job_id": job, "submitted_at": chunks.now_utc(), "n_tasks": len(paths), "script": str(script),
              "logs": str(rp.jobs / "logs")}
    if not args.no_auto_combine:
        argv = ["combine", p.name, "--deployment", dep, *where.split()]
        cscript = slurm.write_command_job(s, f"combine_{p.name}_{dep}", argv, rp.jobs)
        record["combine_job_id"] = slurm.submit(cscript, after=job)
    chunks.write_json(rp.jobs / "job.json", record)
    progress.write_progress_file(rp, p.name, place, dep, where)
    print(f"Sent to the cluster as job {job}: {len(paths)} parts, up to "
          f"{(s.get('slurm') or {}).get('max_parallel', 25)} at a time.")
    if record.get("combine_job_id"):
        print("The results are joined automatically when the last part finishes.")
    print(f"\nHow far has it got?   cehbio status {p.name}{where} --deployment {dep}   (add --watch to follow it)")
    print(f"Or open               {rp.progress_file}")
    if args.no_auto_combine:
        print(f"When it has finished: cehbio combine {p.name}{where} --deployment {dep}")


def _finished(qa: dict, rp, dep: str) -> None:
    failed = qa.get("files_by_status", {}).get("failed", 0)
    print(f"\n{'Finished' if qa.get('complete') else 'NOT finished'}: {qa.get('files_expected', 0):,} files, "
          f"{qa.get('n_detections', 0):,} detections"
          + (f"; {failed:,} files couldn't be read (they're listed in {dep}_files.csv)" if failed else ""))
    print(f"Results: {rp.root}")
    if not qa.get("complete"):
        print(f"{len(qa['chunks_missing'])} parts are missing. Run the same `cehbio run` command again to finish them.")


def cmd_run_chunk(args):
    s = _settings(args)
    p = pipelines.get(args.pipeline)
    runner.run_chunk(s, p, Path(args.chunk_json), keep_temp=args.keep_temp, force=args.force)


BUSY = ("running", "waiting", "finished: joining")


def _status_once(s, args) -> bool:
    """Print the status. True when nothing shown is still going (so --watch can stop)."""
    runs = layout.all_runs(s.outputs_root)
    if args.pipeline:
        runs = [r for r in runs if r[0] == args.pipeline]
    want = args.project or args.country or args.bucket
    if want:
        runs = [r for r in runs if r[1] == want]
    if args.deployment:
        runs = [r for r in runs if r[2] == args.deployment]
        if not runs:
            print(f"No run called {args.deployment} in {s.outputs_root}. `cehbio status` lists every run.")
            return True
        if len(runs) == 1:
            pipe, place, dep, rp = runs[0]
            info = progress.run_progress(rp)
            print(progress.describe(rp, pipe, place, dep, info, f" --project {place}"))
            return not info["state"].startswith(BUSY)
    busy = False
    if not runs:
        print(f"No runs yet in {s.outputs_root}")
    else:
        print(f"Runs in {s.outputs_root}\n")
        names = [f"{r[0]} / {r[1]} / {r[2]}" for r in runs]
        w = max(map(len, names))
        for name, (pipe, place, dep, rp) in zip(names, runs):
            info = progress.run_progress(rp)
            busy |= info["state"].startswith(BUSY)
            print(f"  {name:{w}s}  {progress.summary_line(info)}" + ("   (old layout)" if rp.legacy else ""))
        print("\nOne run in detail: cehbio status <pipeline> --project <project> --deployment <deployment>")
    jobs = progress.other_jobs(s)
    if jobs:
        print("\nOther jobs (last 14 days):")
        for j in jobs:
            busy |= j["state"].startswith(BUSY)
            print(f"  job {j['job_id']:>9s}  {j['what']:50s} {j['state']}\n  {'':13s} logs: {j['logs']}")
    return not busy


def cmd_status(args):
    import time
    s = _settings(args)
    if not args.watch:
        _status_once(s, args)
        return
    try:
        while True:
            print("\033[2J\033[H", end="")            # clear the screen
            done = _status_once(s, args)
            if done:
                print("\nNothing left running.")
                return
            print(f"\n(Checking every {args.watch} s. Ctrl+C stops watching; the jobs carry on.)")
            time.sleep(args.watch)
    except KeyboardInterrupt:
        print()


def cmd_combine(args):
    s = _settings(args)
    _where(s, args, need_source=False)
    p = pipelines.get(args.pipeline)
    qa = runner.combine(s, p, args.place, args.deployment)
    _finished(qa, runner.paths(s, p, args.place, args.deployment), args.deployment)


def cmd_models(args):
    from . import modelstore
    from .pipelines.images import MODEL_LIST, NOTICE, latest
    ml = modelstore.load_list(MODEL_LIST)
    s = _settings(args)
    print(NOTICE)
    print("* = newest: used unless you choose another. Keep up to date with: cehbio update")
    print()
    newest = {latest(st, models=ml) for st in ("detector", "binary", "order")}
    newest |= {latest("species", m["region"], ml) for m in ml["models"].values() if m.get("stage") == "species"}
    titles = {"detector": "Finding insects", "binary": "Moth or not", "order": "Order",
              "species": "Species (choose with --set region=...)"}
    for stage, title in titles.items():
        print(title)
        for name, m in ml["models"].items():
            if m.get("stage") != stage:
                continue
            w = m["files"]["weights"]
            here = (modelstore.cache_dir(s) / (w.get("asset") or w["name"])).exists() or any(
                modelstore._local_index(d).get(w["name"]) for d in modelstore.search_dirs(s))
            region = f"region={m['region']:<13}" if m.get("region") else " " * 20
            print(f" {'*' if name in newest else ' '} {name:30s} {region} {str(m.get('released', '')):10s} "
                  f"{m.get('licence', '')[:30]:30s} {'(on this machine)' if here else ''}")
        print()


# ---------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="machine profile, e.g. jasmin or local (default: detected)")

    dep = argparse.ArgumentParser(add_help=False)
    dep.add_argument("pipeline", help="e.g. birds, bats")
    dep.add_argument("--country", help="country (needs a country table from a plug-in)")
    dep.add_argument("--bucket", help="an object-store bucket")
    dep.add_argument("--folder", help="files on disk instead of the object store (originals are never changed)")
    dep.add_argument("--project", help="the folder the results go in, e.g. my-woods-2026 (default: the bucket "
                                       "or country, or 'local' for files on disk)")
    dep.add_argument("--deployment", required=True, help="deployment ID, e.g. dep000081")

    ap =argparse.ArgumentParser(prog="cehbio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("pipelines", parents=[common], help="list pipelines").set_defaults(func=cmd_pipelines)

    c = sub.add_parser("check", parents=[common], help="check settings, credentials and object store")
    c.add_argument("--bucket", help="also check this bucket, e.g. gbr")
    c.set_defaults(func=cmd_check)

    sub.add_parser("devices", parents=[common], help="list device profiles").set_defaults(func=cmd_devices)

    u = sub.add_parser("upload", parents=[common], help="upload recordings/images to UKCEH (asks step by step)",
                       description="Upload files to UKCEH through the UKCEH upload service. With no options it asks "
                                   "each question; give options to run unattended. Run again to resume.")
    u.add_argument("--folder", help="folder with the files, e.g. the SD card")
    u.add_argument("--country", help="country as listed by the service, or Test")
    u.add_argument("--deployment", help='deployment as "<location> - <camera id>" (part of it is enough)')
    u.add_argument("--data-type", help="snapshot_images, audible_recordings, ultrasound_recordings, ...")
    u.add_argument("--name", help="your full name")
    u.add_argument("--test", action="store_true", help="upload 10 random files only")
    u.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    u.add_argument("--skip-remote-check", action="store_true", help="don't ask the service whether each file exists")
    u.add_argument("--parallel", type=int, default=5, help="files at once (default 5)")
    u.add_argument("--log-dir", help="where to keep the upload log (default: <outputs>/upload_logs)")
    u.set_defaults(func=cmd_upload)

    from .uploaded import add_command as _add_uploaded
    _add_uploaded(sub, common)
    from .specieslist import add_command as _add_species_list
    _add_species_list(sub, common)

    r = sub.add_parser("run", parents=[common, dep], help="run a pipeline on a deployment")
    r.add_argument("--device", help="recorder, e.g. audiomoth, song-meter (see `cehbio devices`)")
    r.add_argument("--timestamp-pattern", metavar="PATTERN",
                   help='how dates appear in file names, e.g. "SERIAL-YYYYMMDDThhmmss" or "*_YYYYMMDD_hhmmss" '
                        "(YYYY MM DD hh mm ss = date/time, SERIAL = device ID, * = anything)")
    r.add_argument("--config", help="YAML file of settings for this pipeline")
    r.add_argument("--set", action="append", metavar="KEY=VALUE", help="one setting, e.g. --set model=perch")
    r.add_argument("--files-per-chunk", type=int)
    r.add_argument("--max-files", type=int, help="only the first N files (for testing)")
    r.add_argument("--data-type", help="object-store folder, if not the pipeline's usual one")
    r.add_argument("--here", action="store_true", help="run on this machine even if Slurm is available")
    r.add_argument("--dry-run", action="store_true", help="write the Slurm script but don't submit it")
    r.add_argument("--gpu", action="store_true", help="force a GPU job")
    r.add_argument("--cpu", action="store_true", help="force a CPU job")
    r.add_argument("--keep-temp", action="store_true", help="keep downloaded files (debugging)")
    r.add_argument("--no-auto-combine", action="store_true",
                   help="on a cluster: don't join the results automatically when the last part finishes")
    r.set_defaults(func=cmd_run)

    rc = sub.add_parser("run-chunk", parents=[common], help="run one chunk (used inside Slurm jobs)")
    rc.add_argument("pipeline")
    rc.add_argument("--chunk-json", required=True)
    rc.add_argument("--force", action="store_true", help="redo even if already complete")
    rc.add_argument("--keep-temp", action="store_true")
    rc.set_defaults(func=cmd_run_chunk)

    mo = sub.add_parser("models", parents=[common], help="list image models (detector, moth/non-moth, order, species)")
    mo.set_defaults(func=cmd_models)

    up = sub.add_parser("update", parents=[common], help="get the newest code, packages and models for every pipeline")
    up.add_argument("--no-pull", action="store_true", help="don't git pull, just upgrade packages and models")
    up.add_argument("--no-models", action="store_true", help="don't fetch models now (they download when first used)")
    up.set_defaults(func=lambda a: __import__("ceh_biomonitoring.update", fromlist=["update"]).update(
        pull=not a.no_pull, fetch_models=not a.no_models))
    sub.add_parser("versions", parents=[common], help="package and model versions in use").set_defaults(
        func=lambda a: __import__("ceh_biomonitoring.update", fromlist=["show_versions"]).show_versions())

    from .pipelines.images.masktool import add_command as _add_mask
    _add_mask(sub, common)

    from .sites import add_command as _add_deployments
    _add_deployments(sub, common)

    from .examples import add_command as _add_examples
    _add_examples(sub, common)

    from .validation import add_command as _add_validate
    _add_validate(sub, common)

    st = sub.add_parser("status", parents=[common], help="how far your runs have got (all of them, or one)",
                        description="With nothing else: every run and how far it has got. Name a pipeline, "
                                    "project or deployment to narrow it down; one deployment shows the details.")
    st.add_argument("pipeline", nargs="?", help="only this pipeline, e.g. bats")
    st.add_argument("--project", help="only this project folder")
    st.add_argument("--bucket", help="only runs from this bucket")
    st.add_argument("--country", help="only runs for this country")
    st.add_argument("--deployment", help="one deployment, in detail")
    st.add_argument("--watch", nargs="?", type=int, const=60, metavar="SECONDS",
                    help="keep checking (every 60 s, or as given) until nothing is running")
    st.set_defaults(func=cmd_status)
    from .tidy import add_command as _add_tidy
    _add_tidy(sub, common)
    from .clockcheck import add_command as _add_clock
    _add_clock(sub, common)
    from .reporting.data import add_command as _add_report_data
    _add_report_data(sub, common)
    from .reporting.copernicus import add_command as _add_weather_setup
    _add_weather_setup(sub, common)
    from .videos.night import add_command as _add_video
    _add_video(sub, common)
    from .videos.soundscape import add_command as _add_soundscape
    _add_soundscape(sub, common)
    from .reporting.html import add_command as _add_report
    _add_report(sub, common)
    sub.add_parser("combine", parents=[common, dep], help="merge chunk outputs + QA").set_defaults(func=cmd_combine)

    # Plug-ins (e.g. the internal repo) add commands via entry-point group "ceh_biomonitoring.commands":
    # each entry point is a function add(subparsers, common_parser) that registers its own sub-command.
    for ep in metadata.entry_points(group="ceh_biomonitoring.commands"):
        try:
            ep.load()(sub, common)
        except Exception as e:  # noqa: BLE001 - a broken plug-in must not break the core command
            print(f"[warning] plug-in command '{ep.name}' could not load: {e}", file=sys.stderr)
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
