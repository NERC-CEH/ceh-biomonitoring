"""Write and submit a Slurm array job: one task per chunk JSON.

The job calls the same Python that created it, so nobody has to activate an
environment inside the job script.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from .pipelines.base import Pipeline
from .settings import Settings

TEMPLATE = """#!/bin/bash
#SBATCH --job-name={job_name}
{sbatch_lines}
#SBATCH --array=1-{n_tasks}%{max_parallel}
#SBATCH --output={log_dir}/%x_%A_%a.out
set -euo pipefail
CHUNK=$(sed -n "${{SLURM_ARRAY_TASK_ID}}p" {chunk_list})
echo "[$(date -Is)] task ${{SLURM_ARRAY_TASK_ID}} -> $CHUNK on $(hostname)"
{env_lines}{python} -m ceh_biomonitoring.cli run-chunk {pipeline} --chunk-json "$CHUNK"{profile_flag}
"""


def write_job(settings: Settings, pipeline: Pipeline, country: str, deployment: str,
              chunk_jsons: list[Path], job_dir: Path, use_gpu: bool | None = None) -> Path:
    s = settings.get("slurm") or {}
    gpu = pipeline.needs_gpu if use_gpu is None else use_gpu
    g = s.get("gpu") or {}
    if gpu and not g.get("partition"):
        print("No GPU partition on this machine: running on CPU (slower).", flush=True)
        gpu = False
    opts = {
        "account": (g.get("account") if gpu else None) or s.get("account"),
        "partition": g.get("partition") if gpu else s.get("partition"),
        "qos": (g.get("qos") if gpu else None) or s.get("qos"),
        "time": s.get("time"), "mem": s.get("mem"), "cpus-per-task": s.get("cpus"),
        "gres": g.get("gres") if gpu else None,
    }
    sbatch_lines = "\n".join(f"#SBATCH --{k}={v}" for k, v in opts.items() if v not in (None, ""))
    job_dir.mkdir(parents=True, exist_ok=True)
    log_dir = job_dir / "logs"
    log_dir.mkdir(exist_ok=True)
    chunk_list = job_dir / f"{deployment}_chunks.txt"
    chunk_list.write_text("".join(f"{p}\n" for p in chunk_jsons))
    env_lines = "".join(f"export {k}={shlex.quote(str(v))}\n" for k, v in (s.get("env") or {}).items())
    script = TEMPLATE.format(
        job_name=f"{pipeline.name}_{country}_{deployment}", sbatch_lines=sbatch_lines,
        n_tasks=len(chunk_jsons), max_parallel=s.get("max_parallel", 25), log_dir=log_dir,
        chunk_list=chunk_list, env_lines=env_lines, python=shlex.quote(sys.executable), pipeline=pipeline.name,
        profile_flag=f" --profile {settings.profile}",
    )
    path = job_dir / f"{pipeline.name}_{deployment}.sbatch"
    path.write_text(script)
    return path


def submit(script: Path, after: str | None = None) -> str:
    """Submit a job script; with `after`, it starts once that job has ended (however it ended)."""
    extra = [f"--dependency=afterany:{after}"] if after else []
    res = subprocess.run(["sbatch", "--parsable", *extra, str(script)], capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"sbatch failed: {res.stderr.strip()}")
    return res.stdout.strip().split(";")[0]


COMMAND_TEMPLATE = """#!/bin/bash
#SBATCH --job-name={job_name}
{sbatch_lines}
#SBATCH --output={log_dir}/%x_%j.out
set -euo pipefail
echo "[$(date -Is)] {job_name} on $(hostname)"
{env_lines}{python} -m ceh_biomonitoring {args} --profile {profile}
"""


def write_command_job(settings: Settings, job_name: str, argv: list[str], job_dir: Path,
                      use_gpu: bool = False) -> Path:
    """A one-task job that runs `cehbio <argv>` with this machine's Slurm settings (any cluster)."""
    s = settings.get("slurm") or {}
    g = s.get("gpu") or {}
    if use_gpu and not g.get("partition"):
        print("No GPU partition set for this machine: the job runs on CPU (slower).", flush=True)
        use_gpu = False
    opts = {
        "account": (g.get("account") if use_gpu else None) or s.get("account"),
        "partition": g.get("partition") if use_gpu else s.get("partition"),
        "qos": (g.get("qos") if use_gpu else None) or s.get("qos"),
        "time": s.get("time"), "mem": s.get("mem"), "cpus-per-task": s.get("cpus"),
        "gres": g.get("gres") if use_gpu else None,
    }
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "logs").mkdir(exist_ok=True)
    script = COMMAND_TEMPLATE.format(
        job_name=job_name, sbatch_lines="\n".join(f"#SBATCH --{k}={v}" for k, v in opts.items() if v not in (None, "")),
        log_dir=job_dir / "logs", python=shlex.quote(sys.executable), profile=settings.profile,
        env_lines="".join(f"export {k}={shlex.quote(str(v))}\n" for k, v in (s.get("env") or {}).items()),
        args=" ".join(shlex.quote(a) for a in argv))
    path = job_dir / f"{job_name}.sbatch"
    path.write_text(script)
    return path
