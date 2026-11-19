"""The words of a report, with their numbers, written once to report/data/text.json.

The Python report (cehbio report) and the R report (the cehbio R package) both lay out these same words,
so a report says the same thing whichever language made it. Nothing here identifies a person or a
machine: the run records' user and host names are never used.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

GROUP = {"images": {"device": "light trap", "what": "insects", "unit": "individual insects",
                    "unit_one": "individual insect", "file": "photo", "files": "photos", "made": "took"},
         "birds": {"device": "sound recorder", "what": "birds", "unit": "bird calling events",
                   "unit_one": "calling event", "file": "recording", "files": "recordings", "made": "made"},
         "bats": {"device": "bat detector", "what": "bats", "unit": "bat passes", "unit_one": "bat pass",
                  "file": "recording", "files": "recordings", "made": "made"}}

CITATIONS = [
    ("birdnet", "BirdNET: Kahl, S., Wood, C. M., Eibl, M. & Klinck, H. (2021). BirdNET: a deep learning solution "
                "for avian diversity monitoring. Ecological Informatics 61, 101236. Non-commercial use only."),
    ("perch", "Perch: Google DeepMind / Google Research, https://github.com/google-research/perch"),
    ("batdetect", "BatDetect2: Mac Aodha, O. et al. (2022). Towards a general approach for bat echolocation "
                  "detection and classification. bioRxiv. Non-commercial use only."),
    ("flat", "flat-bug insect detector: Svenning, Geissmann et al., https://github.com/darsa-group/flat-bug"),
    ("moth-vs", "Moth or not: Rolnick lab, Mila (AMI project), https://github.com/RolnickLab/ami-data-companion"),
    ("order", "Insect order: Bjerge, K. et al. (2025). Towards edge processing of images from insect camera traps. "
              "Remote Sensing in Ecology and Conservation. doi:10.1002/rse2.70007"),
    ("moth-species", "Moth species models: The Alan Turing Institute and UKCEH, for the AMBER project. "
                     "Non-commercial use only."),
]

HOW = {
    "images": ("A camera photographed the light trap's sheet through the night. A computer model found every insect "
               "in each photo, a second said whether it was a moth, a third gave its insect order, and for moths a "
               "fourth suggested the species. The same insect was then followed from photo to photo, so one moth "
               "sitting on the sheet for an hour counts once."),
    "birds": ("A sound recorder recorded on a schedule. A computer model listened to each recording in short pieces "
              "and named the birds it heard. Calls of the same species in one recording, with pauses of up to a "
              "minute, count as one calling event."),
    "bats": ("A bat detector recorded the ultrasonic calls of passing bats. A computer model found each call and "
             "suggested the species. Calls of the same species in one recording, with pauses of up to a second, "
             "count as one bat pass."),
}

CAVEAT = ("These identifications were made by computer models that are still in development. Treat every species "
          "as a suggestion until an expert has checked it. The score next to each one is the model's own "
          "confidence, not a measure of how often it is right: a low score means it was unsure, and a name from "
          "outside the region (the models know some species that don't live here) is a sign of that too.")


def _date(s) -> str:
    try:
        return pd.Timestamp(s).strftime("%-d %B %Y")
    except ValueError:
        return pd.Timestamp(s).strftime("%#d %B %Y")      # Windows


def _n(x) -> str:
    return f"{int(x):,}" if pd.notna(x) else "0"


def model_names(models) -> list[str]:
    """The models a run used, by name, from its provenance. Only model names, makers and licences: never
    paths (Perch's is a folder on the computer that ran it), user names or machine names."""
    m = models.get("models", models) if isinstance(models, dict) else {}
    out = []
    for k, v in (m.items() if isinstance(m, dict) else []):
        if isinstance(v, dict) and v.get("model"):
            out.append(f"{v['model']}" + (f", by {v['by']}" if v.get("by") else "")
                       + (f" (licence: {v['licence']})" if v.get("licence") else ""))
        elif k == "birdnet-analyzer" and v:
            out.append(f"BirdNET Analyzer {v} (code MIT, model CC BY-NC-SA 4.0: non-commercial)")
        elif k == "geo_model" and v:
            out.append("BirdNET's location filter (which species to expect where and when)")
        elif k == "batdetect2" and v:
            out.append(f"BatDetect2 {v} (CC BY-NC 4.0: non-commercial)")
        elif k == "perch_model" and v:
            parts = [x for x in Path(str(v)).parts if x.lower().startswith(("perch", "bird-vocal"))]
            out.append("Perch, by Google DeepMind" + (f" ({parts[-1]})" if parts else "") + " (licence: Apache 2.0)")
    return out


def citations(names: list[str], pipeline: str) -> list[str]:
    text = " ".join(names).lower() + " " + pipeline
    picked = [c for key, c in CITATIONS if key in text]
    if pipeline == "images":
        picked += [c for key, c in CITATIONS if key in ("flat", "moth-vs", "order", "moth-species") and c not in picked]
    return list(dict.fromkeys(picked))


def build(tables: dict, about: dict) -> dict:
    """Headline sentences per deployment and for the project, and the methods text."""
    pipe = about["pipeline"]
    g = GROUP[pipe]
    deps, nights, species = tables["deployments"], tables["nights"], tables["species"]
    per = {}
    for d in deps.itertuples():
        n = nights[(nights["deployment_id"] == d.deployment_id) & nights.get("in_deployment", True)]
        sp = species[species["deployment_id"] == d.deployment_id] if len(species) else species
        main = sp[sp["kind"] != "other insect"] if pipe == "images" and len(sp) else sp
        lines = []
        if d.nights_worked:
            lines.append(f"The {g['device']} worked on {d.nights_worked} nights between {_date(d.first_night)} and "
                         f"{_date(d.last_night)}, for {round(d.hours_worked):,} hours in all, and {g['made']} "
                         f"{_n(d.files)} {g['files']}.")
        if d.files_failed:
            lines.append(f"{_n(d.files_failed)} {g['files'] if d.files_failed != 1 else g['file']} couldn't be read.")
        lines.append(f"It recorded {_n(d.individuals)} {g['unit']}" +
                     (f" of {len(main):,} different {'moth species' if pipe == 'images' else 'species'}"
                      if len(main) else "") + ".")
        if pipe == "images" and len(sp):
            moths = int(sp.loc[sp["kind"] == "moth", "individuals"].sum())
            others = sp[sp["kind"] == "other insect"].sort_values("individuals", ascending=False)
            if d.individuals:
                lines.append(f"{round(100 * moths / d.individuals)}% of the insects were moths" +
                             (f"; the commonest other group was {others['taxon'].iloc[0]}" if len(others) else "") + ".")
        if len(n) and n["individuals"].max() > 0:
            best = n.sort_values("individuals", ascending=False).iloc[0]
            lines.append(f"The busiest night was {_date(best['night'])}, with {_n(best['individuals'])} "
                         f"{g['unit']}" + (f" at {best['temperature_mean_c']:.0f} °C on average"
                                           if pd.notna(best.get("temperature_mean_c")) else "") + ".")
        if len(main):
            top = main.sort_values("individuals", ascending=False).head(3)
            names = [f"{(r.common_name + ' (' + r.taxon + ')') if isinstance(getattr(r, 'common_name', None), str) else r.taxon}"
                     for r in top.itertuples()]
            lines.append("The most often recorded were " + ", ".join(names[:-1]) + (" and " if len(names) > 1 else "")
                         + names[-1] + " (all still to be checked).")
        per[d.deployment_id] = lines
    proj = []
    if len(deps) > 1:
        proj.append(f"{len(deps)} deployments recorded {_n(deps['individuals'].sum())} {g['unit']} over "
                    f"{_n(deps['nights_worked'].sum())} nights.")
        if len(species):
            main = species[species["kind"] != "other insect"] if pipe == "images" else species
            proj.append(f"Together they recorded {main['taxon'].nunique():,} different "
                        f"{'moth species' if pipe == 'images' else 'species'}; "
                        f"{int((main.groupby('taxon')['deployment_id'].nunique() == len(deps)).sum()):,} were "
                        f"recorded at every deployment.")
    names = model_names(about.get("models") or {})
    w = about.get("weather") or {}
    methods = {
        "how": HOW[pipe],
        "caveat": CAVEAT,
        "night": ("A night runs from noon to noon on the device's own clock and is named by the evening it starts. "
                  "Activity is given per hour the device was working, so nights of different lengths can be compared."),
        "unit": f"Counts are of {g['unit']}: each is {about.get('individual')}." if about.get("individual") else "",
        "weather": (f"Weather for each night covers only the hours the device was working. {w.get('credit', '')}."
                    if w else "No weather was added."),
        "moon": "How full the moon was, and how long it was above the horizon while the device worked, are worked out "
                "from astronomical formulas.",
        "models": names,
        "citations": citations(names, pipe),
        "notes": about.get("notes", []),
        "made_with": f"Made with the UKCEH ceh-biomonitoring toolkit, version {about.get('toolkit_version')}, on "
                     f"{_date(about.get('made_at', '')[:10])}.",
    }
    from .html import STYLE                      # colours and font, so the R report matches exactly
    return {"pipeline": pipe, "project": about["project"], "labels": g, "deployments": per, "project_summary": proj,
            "methods": methods, "style": STYLE}


def write(out: Path, tables: dict, about: dict) -> dict:
    t = build(tables, about)
    (Path(out) / "text.json").write_text(json.dumps(t, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return t
