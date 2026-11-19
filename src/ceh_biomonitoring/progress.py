"""How far runs have got, in plain words: `cehbio status`, PROGRESS.txt, and the line printed after each chunk.

Reads only the files the runs write (the manifest, each chunk's _summary.json, the job record), so it
works the same on a laptop and on a cluster. On a cluster it also asks Slurm which parts are still waiting
or running, and why any stopped (out of time, out of memory).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .chunks import now_utc, write_json

BAR = 24
STALE_HOURS = 12


def bar(frac: float, width: int = BAR) -> str:
    frac = max(0.0, min(1.0, frac))
    n = round(frac * width)
    return "#" * n + "-" * (width - n)


def _t(s: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def nice_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    m = int(round(seconds / 60))
    if m < 1:
        return "under a minute"
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h} h {m} min" if m else f"{h} h"
    return f"{h // 24} days {h % 24} h"


def _read(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ Slurm
def has_slurm() -> bool:
    return bool(shutil.which("squeue"))


def slurm_tasks(job_id: str) -> dict:
    """{'waiting': n, 'running': n} for a job still in the queue (array tasks counted one by one)."""
    try:
        out = subprocess.run(["squeue", "-h", "-r", "-j", str(job_id), "-o", "%T"], capture_output=True,
                             text=True, timeout=20).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return {}
    return {"waiting": sum(s in ("PENDING", "CONFIGURING") for s in out),
            "running": sum(s in ("RUNNING", "COMPLETING") for s in out)}


def slurm_ended(job_id: str) -> dict[str, str]:
    """{array task index or '': final state} for tasks that have ended, e.g. TIMEOUT, OUT_OF_MEMORY."""
    if not shutil.which("sacct"):
        return {}
    try:
        out = subprocess.run(["sacct", "-n", "-X", "-P", "-j", str(job_id), "-o", "JobID,State"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    res = {}
    for line in out.splitlines():
        jid, _, state = line.partition("|")
        if state and not state.startswith(("RUNNING", "PENDING")):
            res[jid.partition("_")[2]] = state.split()[0]
    return res


WHY = {"TIMEOUT": "ran out of time", "OUT_OF_MEMORY": "ran out of memory", "CANCELLED": "was cancelled",
       "NODE_FAIL": "the computer it was on failed", "FAILED": "stopped with an error", "PREEMPTED": "was bumped"}


# ------------------------------------------------------------------ one run
def run_progress(paths, check_slurm: bool = True) -> dict:
    """Everything `cehbio status` says about one deployment's run."""
    man = _read(paths.manifest)
    n_chunks = man.get("n_chunks")
    total_files = man.get("total_files")
    sums = {p.name.replace("_summary.json", ""): _read(p) for p in paths.chunks.glob("*_summary.json")}
    st = {"complete": [], "running": [], "failed": []}
    for name, s in sums.items():
        st.setdefault(s.get("status", "running"), []).append(name)
    done = [sums[n] for n in st["complete"]]
    files_done = sum(int(s.get("n_files_expected") or 0) for s in done)
    files_failed = sum(int(s.get("n_files_failed") or 0) for s in done)
    detections = sum(int(s.get("n_detections") or 0) for s in done)
    starts = [t for t in (_t(s.get("started_at")) for s in sums.values()) if t]
    ends = [t for t in (_t(s.get("finished_at")) for s in done) if t]
    job = _read(paths.jobs / "job.json")
    info = {"n_chunks": n_chunks, "total_files": total_files, "complete": len(st["complete"]),
            "running": len(st["running"]), "failed": len(st["failed"]), "files_done": files_done,
            "files_failed": files_failed, "detections": detections, "job": job, "slurm": {},
            "stopped": [], "errors": {n: sums[n].get("error", "") for n in st["failed"]},
            "combined": bool(_read(paths.root / f"{paths.root.name}_qa.json").get("complete")),
            "started": min(starts).isoformat() if starts else None}
    if job.get("job_id") and check_slurm and has_slurm():
        info["slurm"] = slurm_tasks(job["job_id"])
        if st["running"] and not info["slurm"].get("running"):
            # parts marked running that Slurm has finished with: they were stopped
            ended = slurm_ended(job["job_id"])
            order = _chunk_order(paths)
            for name in st["running"]:
                idx = order.get(name)
                state = ended.get(str(idx)) if idx else None
                info["stopped"].append((name, WHY.get(state or "", "stopped without finishing")))
        if job.get("combine_job_id"):
            info["combine_waiting"] = bool(slurm_tasks(job["combine_job_id"]))
    if not job.get("job_id") and st["running"]:
        # run on this machine: a part that hasn't moved for 12 hours was interrupted (laptop shut, Ctrl+C)
        for name in st["running"]:
            f = paths.chunks / f"{name}_summary.json"
            try:
                idle = datetime.now(timezone.utc).timestamp() - f.stat().st_mtime
            except OSError:
                continue
            if idle > STALE_HOURS * 3600:
                info["stopped"].append((name, "interrupted (no progress for over 12 hours)"))
    elapsed = (datetime.now(timezone.utc) - min(starts)).total_seconds() if starts else None
    info["elapsed_s"] = elapsed
    left = (total_files or 0) - files_done
    if ends and files_done and left > 0 and elapsed:
        span = (max(ends) - min(starts)).total_seconds() or elapsed
        info["eta_s"] = left / (files_done / span)
    else:
        info["eta_s"] = None
    info["state"] = _state(info)
    return info


def _chunk_order(paths) -> dict[str, int]:
    """Chunk name -> Slurm array task number, from the job's chunk list."""
    lists = sorted(paths.jobs.glob("*_chunks.txt"))
    if not lists:
        return {}
    names = [Path(x).stem for x in lists[-1].read_text().split()]
    return {n: i + 1 for i, n in enumerate(names)}


def _state(i: dict) -> str:
    n = i["n_chunks"] or 0
    if n and i["complete"] == n:
        return "finished" if i["combined"] else "finished: joining the results"
    if i["stopped"] or i["failed"]:
        if i["slurm"].get("running") or i["slurm"].get("waiting"):
            return "running, with problems"
        return "stopped: needs attention"
    if i["slurm"].get("running") or i["running"]:
        return "running"
    if i["slurm"].get("waiting"):
        return "waiting for the cluster"
    if i["complete"]:
        return "paused (run the same command again to carry on)"
    return "not started"


def summary_line(i: dict) -> str:
    n = i["n_chunks"] or 0
    frac = i["complete"] / n if n else 0.0
    bits = [f"[{bar(frac)}] {round(100 * frac):3d}%", i["state"]]
    if n and i["complete"] < n:
        bits.append(f"{i['complete']} of {n} parts")
        if i["eta_s"] is not None:
            bits.append(f"about {nice_duration(i['eta_s'])} left")
    return "  ".join([bits[0], " · ".join(bits[1:])])


def describe(paths, pipeline: str, place: str, deployment: str, info: dict, place_args: str = "") -> str:
    """The full report for one run, as printed by `cehbio status` and kept in PROGRESS.txt."""
    n = info["n_chunks"] or "?"
    L = [f"{pipeline} · {place} · {deployment}", summary_line(info), ""]
    tf = info["total_files"]
    L.append(f"Files done        : {info['files_done']:,} of {tf:,}" if tf else
             f"Files done        : {info['files_done']:,}")
    L.append(f"Parts             : {info['complete']} finished, {info['running']} running, "
             f"{info['failed']} failed, of {n}")
    if info["slurm"]:
        L.append(f"On the cluster    : {info['slurm'].get('running', 0)} running, "
                 f"{info['slurm'].get('waiting', 0)} waiting their turn  (job {info['job'].get('job_id')})")
    L.append(f"Found so far      : {info['detections']:,} detections"
             + (f"; {info['files_failed']:,} files couldn't be read" if info["files_failed"] else ""))
    if info["elapsed_s"] is not None:
        L.append(f"Running for       : {nice_duration(info['elapsed_s'])}"
                 + (f"; about {nice_duration(info['eta_s'])} left" if info["eta_s"] is not None else ""))
    problems = [(k, v.split(":")[0] if v else "error") for k, v in info["errors"].items()] + info["stopped"]
    if problems:
        L += ["", "Problems:"]
        L += [f"  {name}: {why}" for name, why in problems[:10]]
        if len(problems) > 10:
            L.append(f"  ... and {len(problems) - 10} more")
        L.append(f"  Job logs: {paths.jobs / 'logs'}")
    L += ["", "Results folder    : " + str(paths.root)]
    nxt = next_step(info, pipeline, deployment, place_args)
    if nxt:
        L.append("Next              : " + nxt)
    return "\n".join(L)


def next_step(info: dict, pipeline: str, deployment: str, place_args: str) -> str:
    st = info["state"]
    again = f"cehbio run {pipeline}{place_args} --deployment {deployment}"
    if st == "finished":
        return "the results are ready in the folder above"
    if st == "finished: joining the results":
        if info.get("combine_waiting"):
            return "nothing: the results will be joined automatically in a moment"
        return f"cehbio combine {pipeline}{place_args} --deployment {deployment}"
    if st.startswith("stopped"):
        return f"look at the problems above, then run the same command again ({again}); finished parts are kept"
    if st.startswith("paused"):
        return again
    if st.startswith(("running", "waiting")):
        return f"nothing: check again later with `cehbio status {pipeline}{place_args} --deployment {deployment}`"
    return ""


def write_progress_file(paths, pipeline: str, place: str, deployment: str, place_args: str = "",
                        check_slurm: bool = False) -> None:
    """PROGRESS.txt in the results folder, so people can see progress without a command."""
    try:
        info = run_progress(paths, check_slurm=check_slurm)
        text = describe(paths, pipeline, place, deployment, info, place_args)
        text += f"\n\n(Updated {now_utc()[:19].replace('T', ' ')} UTC. For live cluster details: cehbio status)\n"
        paths.root.mkdir(parents=True, exist_ok=True)
        tmp = paths.progress_file.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(paths.progress_file)
    except OSError:
        pass


# ------------------------------------------------------------------ jobs register (labelling and other one-off jobs)
def register_job(settings, job_id: str, what: str, logs: Path, **extra) -> None:
    """Keep a note of a submitted job, so `cehbio status` can list it."""
    write_json(settings.outputs_root / "working" / "jobs" / f"{job_id}.json",
               {"job_id": str(job_id), "what": what, "submitted_at": now_utc(), "logs": str(logs), **extra})


def other_jobs(settings, days: int = 14) -> list[dict]:
    folder = settings.outputs_root / "working" / "jobs"
    out = []
    now = datetime.now(timezone.utc)
    for p in sorted(folder.glob("*.json")):
        j = _read(p)
        t = _t(j.get("submitted_at"))
        if not j or not t or (now - t).days > days:
            continue
        if has_slurm():
            q = slurm_tasks(j["job_id"])
            if q.get("running"):
                j["state"] = "running"
            elif q.get("waiting"):
                j["state"] = "waiting for the cluster"
            else:
                ended = slurm_ended(j["job_id"]).get("", "")
                j["state"] = "finished" if ended in ("", "COMPLETED") else f"stopped: {WHY.get(ended, ended.lower())}"
        else:
            j["state"] = "?"
        out.append(j)
    return out
