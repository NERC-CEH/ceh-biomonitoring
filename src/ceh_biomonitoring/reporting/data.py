"""cehbio report-data: one project's results as tidy tables, ready for reports in Python or R.

Everything a report needs is worked out here, once, so a report made in Python and one made in R give
the same numbers. Written to <results>/<pipeline>/<project>/report/data/, as .parquet and .csv:

  deployments    one row per deployment: dates, nights worked, files, failures, place, clock
  nights         one row per deployment and night: first and last file, hours worked, files, failures,
                 individuals, and the weather and moon over the hours it was working
  individuals    one row per individual: an insect followed through photos (a track), a bird's calling
                 event, a bat pass (the same units as cehbio validate uses), with its night, name and score
  species        one row per deployment and species (or insect order): individuals, nights, scores
  about.json     what made it: models, settings, sources, credits, and every assumption (e.g. the clock)
  text.json      the report's words with their numbers (headlines, methods), so Python and R reports match
  entoinsights/  the results in EntoInsights' format (AMI-system/EntoInsights), so its functions work too

A night runs noon to noon on the device's own clock, named by the evening it starts. Weather needs each
deployment's place: from the results (latitude, longitude) or a sites file (--sites) with columns
deployment, latitude, longitude, and optionally timezone (e.g. Europe/London), clock (UTC, local, or
an offset like +08:00), and start and end (the dates the unit went out and came in: nights outside them,
such as set-up tests, are kept in the nights table but marked in_deployment = False and left out of
individuals, species and the totals). With no clock given, `cehbio clock-check` decides where it can; otherwise local
time is assumed, and about.json says so.

R twin: r/R/report_data.R (with units.R, times.R, sky.R, clock.R, weather.R and text.R) makes the same
tables in R with no Python. Change both together: tests/test_r_matches_python.py checks they agree.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .. import __version__, layout, times
from ..chunks import now_utc

NIGHT_START_HOUR = 12


def night_of(t: pd.Series) -> pd.Series:
    """Noon-to-noon night on the device's clock, named by its evening (as the pipelines' recording_session)."""
    t = pd.to_datetime(t, errors="coerce")
    return (t - pd.Timedelta(hours=NIGHT_START_HOUR)).dt.strftime("%Y-%m-%d")


def read_sites(path: str | None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame(columns=["deployment", "latitude", "longitude", "timezone", "clock"])
    s = pd.read_csv(path)
    s.columns = [c.strip().lower() for c in s.columns]
    s = s.rename(columns={"deployment_id": "deployment", "lat": "latitude", "lon": "longitude", "tz": "timezone"})
    if "deployment" not in s.columns:
        raise SystemExit(f"{path} needs a 'deployment' column (and latitude, longitude).")
    s["deployment"] = s["deployment"].astype(str)
    return s


def _site(dep: str, sites: pd.DataFrame, det: pd.DataFrame) -> dict:
    row = sites[sites["deployment"] == dep]
    r = row.iloc[0].to_dict() if len(row) else {}
    for k, c in (("latitude", "latitude"), ("longitude", "longitude")):
        if pd.isna(r.get(k)) and c in det.columns and det[c].notna().any():
            r[k] = float(pd.to_numeric(det[c], errors="coerce").dropna().iloc[0])
    day = lambda v: str(pd.Timestamp(v).date()) if isinstance(v, str) and v.strip() else None   # noqa: E731
    core = {"latitude": r.get("latitude"), "longitude": r.get("longitude"),
            "timezone": r.get("timezone") if isinstance(r.get("timezone"), str) else None,
            "clock": str(r.get("clock")).strip() if isinstance(r.get("clock"), str) else None,
            "start": day(r.get("start")), "end": day(r.get("end"))}
    # any other columns (e.g. country, habitat, site_name) are carried into the deployments table
    taken = set(core) | {"deployment", "deployment_id", "pipeline", "project", "first_night", "last_night",
                         "nights_worked", "hours_worked", "files", "files_failed", "files_outside_deployment",
                         "individuals", "taxa", "clock_used"}
    core.update({k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in r.items() if k not in taken})
    return core


def _to_utc(clock_times: pd.Series, clock: str, tz: str | None) -> pd.Series:
    """Device clock times -> UTC."""
    t = pd.to_datetime(clock_times, errors="coerce")
    if clock == "UTC":
        return t
    if clock == "local" and tz:
        return t.dt.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC").dt.tz_localize(None)
    if clock.startswith(("+", "-", "UTC+", "UTC-")):
        c = clock.replace("UTC", "")
        sign = -1 if c.startswith("-") else 1
        hh, _, mm = c[1:].partition(":")
        return t - sign * pd.Timedelta(hours=int(hh or 0), minutes=int(mm or 0))
    return t


def _decide_clock(site: dict, file_times: pd.Series, dep: str, notes: list) -> str:
    """The clock a deployment kept: as given, else from the clock check, else an assumption (noted)."""
    if site["clock"]:
        c = site["clock"]
        return "UTC" if c.upper() == "UTC" else ("local" if c.lower() == "local" else c)
    if site["latitude"] is not None and site["timezone"]:
        from ..clockcheck import check
        try:
            res = check(file_times, float(site["latitude"]), float(site["longitude"]), site["timezone"])
        except Exception:  # noqa: BLE001 - a clock check that can't run just leaves the assumption
            res = {}
        if res.get("clock") in ("UTC", "local"):
            notes.append(f"{dep}: clock taken as {res['clock']} from the clock check ({res['verdict']})")
            return res["clock"]
        if res.get("verdict"):
            notes.append(f"{dep}: the clock check couldn't decide ({res['verdict']}); local time assumed")
        return "local"
    notes.append(f"{dep}: no time zone or clock given, so the device clock is taken as UTC for the weather and "
                 f"moon (give them with --sites)")
    return "UTC"


def _file_times(files: pd.DataFrame, det: pd.DataFrame) -> pd.Series:
    t = pd.Series(pd.NaT, index=files.index, dtype="datetime64[ns]")
    for c in ("image_datetime", "file_datetime"):
        if c in files.columns:
            t = t.fillna(pd.to_datetime(files[c], errors="coerce"))
    missing = t.isna()
    if missing.any():
        t[missing] = pd.to_datetime(files.loc[missing, "source_key"].astype(str).map(
            lambda k: times.from_name(Path(k).name)), errors="coerce")
    return t


def individuals(run_root: Path, group: str) -> pd.DataFrame:
    """One row per individual (track, event, pass), from the validation units."""
    from ..validation import units as U
    try:
        u = U.load([str(run_root)], group)
    except SystemExit:
        return pd.DataFrame()
    if u.empty:
        return pd.DataFrame()
    u = u.sort_values("score", ascending=False, kind="stable").drop_duplicates("unit_id")      # one name per individual
    out = pd.DataFrame({
        "deployment_id": u["deployment_id"].astype(str), "unit_id": u["unit_id"].astype(str),
        "when": pd.to_datetime(u["when"], errors="coerce"),
        "taxon": u["species"].astype(str).str.replace("not a moth: ", "", regex=False),
        "kind": np.where(u["noise_class"].notna(), "other insect", "moth") if group == "images" else group[:-1],
        "score": pd.to_numeric(u["score"], errors="coerce"), "score_type": u["score_type"].astype(str).to_numpy(),
        "unlikely_this_month": u["unlikely"].astype(bool)})
    for c in ("common_name", "order_name", "n_detections", "start_s", "end_s", "image_path", "source_key"):
        if c in u.columns:
            out[c] = u[c].to_numpy()
    if group == "images" and "order_confidence" in u.columns:       # other insects: the order model's score
        oc = pd.to_numeric(u["order_confidence"], errors="coerce").to_numpy()
        other = (out["kind"] == "other insect") & out["score"].isna()
        out.loc[other, "score"] = oc[other.to_numpy()]
        out.loc[other, "score_type"] = "order_confidence"
    out["night"] = night_of(out["when"])
    return out.reset_index(drop=True)


def species_table(ind: pd.DataFrame) -> pd.DataFrame:
    if ind.empty:
        return pd.DataFrame()
    g = ind.groupby(["deployment_id", "kind", "taxon"], observed=True)
    out = g.agg(individuals=("unit_id", "size"), nights=("night", "nunique"), first_night=("night", "min"),
                last_night=("night", "max"), score_mean=("score", "mean"), score_max=("score", "max"),
                unlikely_this_month=("unlikely_this_month", "sum")).reset_index()
    if "common_name" in ind.columns:
        names = ind.dropna(subset=["common_name"]).drop_duplicates("taxon").set_index("taxon")["common_name"]
        out["common_name"] = out["taxon"].map(names)
    return out.sort_values(["deployment_id", "individuals"], ascending=[True, False]).reset_index(drop=True)


def _provenance(paths) -> dict:
    for s in sorted(paths.chunks.glob("*_summary.json")):
        try:
            p = json.loads(s.read_text()).get("provenance")
        except (OSError, ValueError):
            continue
        if p:
            return p
    return {}


def build(settings, pipeline: str, project: str, deployments: list[str] | None = None, sites: str | None = None,
          weather: str = "open-meteo", out: Path | None = None) -> dict:
    runs = [r for r in layout.all_runs(settings.outputs_root) if r[0] == pipeline and r[1] == project
            and (not deployments or r[2] in deployments)]
    if not runs:
        raise SystemExit(f"No {pipeline} runs in project '{project}' under {settings.outputs_root}. "
                         f"`cehbio status` lists them.")
    out = Path(out) if out else settings.outputs_root / pipeline / project / "report" / "data"
    out.mkdir(parents=True, exist_ok=True)
    site_table = read_sites(sites)
    notes, dep_rows, night_parts, ind_parts, prov = [], [], [], [], {}
    for _, _, dep, rp in runs:
        f_files = rp.root / f"{dep}_files.csv"
        f_det = rp.root / f"{dep}_detections.parquet"
        if not f_files.exists():
            notes.append(f"{dep}: not combined yet (no {f_files.name}), left out")
            continue
        files = pd.read_csv(f_files, low_memory=False)
        det = pd.read_parquet(f_det) if f_det.exists() else pd.DataFrame()
        files["when"] = _file_times(files, det)
        files["night"] = night_of(files["when"])
        site = _site(dep, site_table, det)
        clock = _decide_clock(site, files["when"], dep, notes)
        files["when_utc"] = _to_utc(files["when"], clock, site["timezone"])
        ind = individuals(rp.root, pipeline)
        inside = lambda n: ((n >= site["start"]) if site["start"] else True) & (          # noqa: E731
            (n < site["end"]) if site["end"] else True)
        if len(ind) and (site["start"] or site["end"]):
            ind = ind[inside(ind["night"])].reset_index(drop=True)
        ind_parts.append(ind)
        prov = prov or _provenance(rp)
        ok = files["night"].notna() & files["when"].notna()
        g = files[ok].groupby("night")
        nights = pd.DataFrame({
            "deployment_id": dep, "first_file": g["when"].min(), "last_file": g["when"].max(),
            "first_utc": g["when_utc"].min(), "last_utc": g["when_utc"].max(), "files": g.size(),
            "files_failed": g["status"].apply(lambda s: int((s == "failed").sum())),
            "files_with_detections": g["status"].apply(lambda s: int(s.isin(["detections", "processed"]).sum())),
        }).reset_index()
        nights["hours_worked"] = ((nights["last_file"] - nights["first_file"]).dt.total_seconds() / 3600).round(2)
        nights["in_deployment"] = inside(nights["night"]) if (site["start"] or site["end"]) else True
        if len(ind):
            nights["individuals"] = nights["night"].map(ind.groupby("night").size()).fillna(0).astype(int)
        else:
            nights["individuals"] = 0
        nights["individuals_per_hour"] = (nights["individuals"] / nights["hours_worked"].where(
            nights["hours_worked"] > 0)).round(3)
        if site["latitude"] is not None and not pd.isna(site["latitude"]):
            from . import sky
            lat, lon = float(site["latitude"]), float(site["longitude"])
            moon = [sky.moon_over(a.to_pydatetime(), b.to_pydatetime(), lat, lon)
                    for a, b in zip(nights["first_utc"], nights["last_utc"])]
            nights = pd.concat([nights, pd.DataFrame(moon, index=nights.index)], axis=1)
            if weather and weather != "none" and len(nights):
                from . import weather as W
                try:
                    hours = W.hourly(settings, weather, lat, lon, nights["first_utc"].min().date(),
                                     (nights["last_utc"].max() + timedelta(days=1)).date())
                    wx = [W.over(hours, a, b) for a, b in zip(nights["first_utc"], nights["last_utc"])]
                    nights = pd.concat([nights, pd.DataFrame(wx, index=nights.index)], axis=1)
                except SystemExit:
                    raise
                except Exception as e:  # noqa: BLE001 - no weather is a note, not a failed report
                    notes.append(f"{dep}: no weather ({type(e).__name__}: {e})")
        else:
            notes.append(f"{dep}: no latitude and longitude, so no weather or moon (give them with --sites)")
        night_parts.append(nights)
        worked = nights[(nights["files"] > 0) & nights["in_deployment"]]
        if (~nights["in_deployment"]).any():
            notes.append(f"{dep}: {int((~nights['in_deployment']).sum())} nights outside the deployment dates "
                         f"({site['start'] or '...'} to {site['end'] or '...'}) are left out of the totals")
        dep_rows.append({"deployment_id": dep, "pipeline": pipeline, "project": project,
                         "first_night": worked["night"].min() if len(worked) else None,
                         "last_night": worked["night"].max() if len(worked) else None,
                         "nights_worked": int(len(worked)), "hours_worked": float(worked["hours_worked"].sum()),
                         "files": int(worked["files"].sum()), "files_failed": int(worked["files_failed"].sum()),
                         "files_outside_deployment": int(nights.loc[~nights["in_deployment"].astype(bool), "files"].sum()),
                         "individuals": int(len(ind)), "taxa": int(ind["taxon"].nunique()) if len(ind) else 0,
                         **site, "clock_used": clock})
        if pipeline in ("images", "birds"):
            from .entoinsights import export
            got = export(rp.root, dep, pipeline, site, out / "entoinsights")
            if got is None and pipeline == "birds":
                notes.append(f"{dep}: no EntoInsights copy (it reads BirdNET results only)")
    tables = {"deployments": pd.DataFrame(dep_rows),
              "nights": pd.concat(night_parts, ignore_index=True) if night_parts else pd.DataFrame(),
              "individuals": pd.concat(ind_parts, ignore_index=True) if ind_parts else pd.DataFrame()}
    tables["species"] = species_table(tables["individuals"])
    for name, df in tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False)
        df.to_csv(out / f"{name}.csv", index=False)
    from . import weather as W
    about = {"made_at": now_utc(), "toolkit_version": __version__, "pipeline": pipeline, "project": project,
             "deployments": [r["deployment_id"] for r in dep_rows], "night": "noon to noon on the device's clock",
             "individual": {"images": "an insect followed through consecutive photos (a track)",
                            "birds": "a species calling in one recording, pauses of up to 60 s",
                            "bats": "a species in one recording, pauses of up to 1 s (a pass)"}[pipeline],
             "weather": {"source": weather, **W.SOURCES.get(weather, {})} if weather and weather != "none" else None,
             "moon": "Schlyter's low-precision method (about 1 degree)", "models": prov, "notes": notes}
    (out / "about.json").write_text(json.dumps(about, indent=2, default=str))
    from . import text
    text.write(out, tables, about)
    return {"out": str(out), "deployments": len(dep_rows), "nights": len(tables["nights"]),
            "individuals": len(tables["individuals"]), "species": len(tables["species"]), "notes": notes}


def add_command(sub, common) -> None:
    import argparse
    p = sub.add_parser("report-data", parents=[common], help="a project's results as tidy tables for reports (Python or R)",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pipeline", choices=["birds", "bats", "images"])
    p.add_argument("--project", required=True, help="the project folder (as in cehbio run --project)")
    p.add_argument("--deployment", nargs="*", help="only these deployments (default: all in the project)")
    p.add_argument("--sites", help="CSV: deployment, latitude, longitude, timezone, clock")
    p.add_argument("--weather", default="open-meteo", choices=["open-meteo", "era5-land", "none"],
                   help="open-meteo (default; non-commercial only) or era5-land (Copernicus; commercial use allowed, "
                        "needs a free CDS key)")
    p.add_argument("--out", help="folder for the tables (default <results>/<pipeline>/<project>/report/data)")

    def go(a):
        from ..settings import Settings
        r = build(Settings.load(getattr(a, "profile", None)), a.pipeline, a.project, a.deployment, a.sites,
                  a.weather, Path(a.out) if a.out else None)
        print(f"{r['deployments']} deployments, {r['nights']} nights, {r['individuals']:,} individuals, "
              f"{r['species']} species rows -> {r['out']}")
        for n in r["notes"]:
            print("  NOTE " + n)
    p.set_defaults(func=go)
