"""cehbio species-list: a candidate species list for a place, from several sources, to check and then use.

A list of the species likely at your site makes the moth (or bird) results much better: guesses are only
chosen from it (`--set species_list=...`), and experts label from it. This builds a first version:

  * GBIF: species with records in the country, or within --radius-km of a point (--lat, --lon). Only
    records marked present, with no location problems GBIF has flagged, and not fossils; --since keeps
    only recent records. With --by-month, also a month-by-month list (the 'month' and 'likelihood'
    columns the pipelines read) from when each species has been recorded.
  * The AMBER species model for your region (--region): which species it can recognise. Species recorded
    here that it can't name are flagged (it will never suggest them); species it knows with no records
    here are left out unless you add --include-model-only.
  * Your own checklist (--checklist): a national or regional list, which is the best source where one
    exists. Species on it are always included.

Every row says where it came from and whether it needs checking. THIS IS A STARTING POINT, NOT A
CHECKLIST: GBIF records include misidentified, old, vagrant and introduced species, and miss species
nobody has recorded or shared. Have someone who knows the local fauna look over it before you use it.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from .validation import gbif

FEW = gbif.FEW_RECORDS


def area_counts(bb: "gbif.Backbone", area: dict, higher_key: int, since: int | None = None,
                month: int | None = None) -> dict[str, int] | None:
    """{speciesKey: records} for a higher taxon in an area: {'country': 'CR'} or {'geoDistance': 'lat,lon,50km'}."""
    tag = "_".join(f"{k}-{v}" for k, v in sorted(area.items())).replace(",", "_").replace(".", "p")
    f = bb.dir / "areas" / f"{tag}_{higher_key}_since{since or 0}_m{month or 0}.json"
    if f.exists():
        d = json.loads(f.read_text(encoding="utf-8"))
        if (date.today() - date.fromisoformat(d["fetched"][:10])).days <= gbif.MAX_AGE_DAYS or bb.offline:
            return d["counts"]
    filters = dict(occurrenceStatus="PRESENT", hasGeospatialIssue="false", basisOfRecord=gbif.RECORD_KINDS, **area)
    if since:
        filters["year"] = f"{int(since)},{date.today().year}"
    if month:
        filters["month"] = int(month)
    counts, offset, step = {}, 0, 1000
    while True:
        r = bb._get("occurrence/search", taxonKey=higher_key, limit=0, facet="speciesKey", facetLimit=step,
                    facetOffset=offset, **filters)
        if r is None:
            return json.loads(f.read_text(encoding="utf-8"))["counts"] if f.exists() else None
        got = (r.get("facets") or [{}])[0].get("counts", [])
        counts.update({c["name"]: int(c["count"]) for c in got})
        if len(got) < step:
            break
        offset += step
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"fetched": datetime.now(timezone.utc).isoformat(), "counts": counts}), encoding="utf-8")
    return counts


def model_species(settings, region: str) -> tuple[str, list[str]]:
    """(model name, the species names it can recognise) for a region's AMBER species model."""
    from .modelstore import fetch
    from .pipelines.images import model_list, species_model_for
    models = model_list()
    name = species_model_for(region, models)
    labels = fetch(settings, models, name, "labels")
    cmap = json.loads(Path(labels).read_text(encoding="utf-8"))
    return name, sorted(k for k in cmap if len(gbif.norm(k).split()) >= 2)    # species only, not higher groups


def build(settings=None, country: str | None = None, lat: float | None = None, lon: float | None = None,
          radius_km: float = 50, taxon: str = "Lepidoptera", since: int | None = None, region: str | None = None,
          checklist: str | None = None, include_model_only: bool = False, by_month: bool = False,
          offline: bool = False) -> tuple[pd.DataFrame, pd.DataFrame | None, dict]:
    """(list, month-by-month list or None, summary)."""
    bb = gbif.Backbone(settings, offline=offline)
    higher = bb.match(taxon)
    if not higher:
        raise SystemExit(f"GBIF doesn't know '{taxon}' (or can't be reached)")
    if lat is not None and lon is not None:
        area, where = {"geoDistance": f"{lat},{lon},{radius_km:g}km"}, f"within {radius_km:g} km of {lat}, {lon}"
    elif country:
        iso2 = bb.iso2(country)
        if not iso2:
            raise SystemExit(f"GBIF doesn't know the country '{country}'")
        area, where = {"country": iso2}, bb.country_name(iso2) or country
    else:
        raise SystemExit("Give --country, or --lat and --lon (with --radius-km)")
    counts = area_counts(bb, area, higher["key"], since) or {}
    about = {"made": date.today().isoformat(), "where": where, "taxon": taxon, "since": since, "caution": gbif.CAUTION,
             "gbif_species": len(counts), "sources": [f"GBIF occurrence records {where}"
                                                       + (f", from {since}" if since else "")]}
    rows: dict[str, dict] = {}

    def add(rec, **flags):
        if not rec or rec.get("key") is None:
            return None
        k = str(rec.get("speciesKey") or rec["key"])
        r = rows.setdefault(k, {"species": rec.get("species") or rec.get("canonicalName") or gbif.norm(rec.get("scientificName", "")),
                                "taxonKey": int(k), "family": rec.get("family") or "", "genus": rec.get("genus") or "",
                                "gbif_records": 0, "in_model": "", "on_checklist": ""})
        r.update({kk: v for kk, v in flags.items() if v not in (None, "")})
        return r

    with ThreadPoolExecutor(bb.workers) as ex:
        for (k, n), rec in zip(counts.items(), ex.map(bb.taxon, list(counts))):
            add(rec, gbif_records=n)

    model_note = None
    if region:
        mname, names = model_species(settings, region)
        matched = bb.match_all(names)
        in_model = {str(rec.get("speciesKey") or rec["key"]) for rec in matched.values() if rec and rec.get("key") is not None}
        for r in rows.values():
            r["in_model"] = "yes" if str(r["taxonKey"]) in in_model else "no"
        only = [rec for rec in matched.values() if rec and str(rec.get("speciesKey") or rec.get("key")) not in rows]
        if include_model_only:
            for rec in only:
                add(rec, in_model="yes")
        model_note = {"model": mname, "species": len(names), "recorded_here_but_not_in_model":
                      sum(1 for r in rows.values() if r["in_model"] == "no"), "in_model_but_no_records_here": len(only)}
        about["model"] = model_note
        about["sources"].append(f"species the {mname} model can recognise")

    if checklist:
        head = Path(checklist).read_text(encoding="utf-8-sig", errors="replace").split("\n", 1)[0]
        sep = "\t" if "\t" in head else ";" if ";" in head and "," not in head else ","
        t = pd.read_csv(checklist, sep=sep, encoding="utf-8-sig")
        col = next((c for c in t.columns if c.lower() in ("species", "scientificname", "scientific_name", "name")), None)
        if col is None:
            raise SystemExit(f"{checklist} needs a 'species' (or scientificName) column")
        names = [str(x) for x in t[col].dropna()]
        matched = bb.match_all(names)
        keys = set()
        for n, rec in matched.items():
            r = add(rec, on_checklist="yes")
            if r:
                keys.add(str(r["taxonKey"]))
        for r in rows.values():
            r["on_checklist"] = "yes" if str(r["taxonKey"]) in keys else "no"
        about["checklist"] = {"file": str(checklist), "species": len(names), "matched": len(keys)}
        about["sources"].append(f"checklist {Path(checklist).name}")
    bb.save()

    def check(r):
        notes = []
        if checklist and r["on_checklist"] == "no":
            notes.append("not on your checklist")
        if 0 < int(r["gbif_records"] or 0) < FEW:
            notes.append(f"only {r['gbif_records']} GBIF record{'s' if r['gbif_records'] != 1 else ''} here")
        if not r["gbif_records"]:
            notes.append("no GBIF records here")
        if region and r["in_model"] == "no":
            notes.append("the model can't recognise it")
        return "; ".join(notes)

    out = pd.DataFrame(list(rows.values()), columns=["species", "taxonKey", "family", "genus", "gbif_records", "in_model", "on_checklist"])
    if not len(out):
        return out.assign(check=""), None, about
    out["check"] = out.apply(check, axis=1)
    out["sources"] = out.apply(lambda r: "; ".join(s for s, on in (("GBIF", r["gbif_records"] > 0), ("model", r["in_model"] == "yes"),
                                                                    ("checklist", r["on_checklist"] == "yes")) if on), axis=1)
    out = out.sort_values(["family", "species"]).reset_index(drop=True)
    about["species"], about["to_check"] = len(out), int((out["check"] != "").sum())

    months = None
    if by_month:
        seen = {m: set((area_counts(bb, area, higher["key"], since, month=m) or {}).keys()) for m in range(1, 13)}
        bb.save()
        recs = []
        for _, r in out.iterrows():
            k = str(r["taxonKey"])
            hit = {m for m in range(1, 13) if k in seen[m]}
            for m in range(1, 13):
                near = {m, (m % 12) + 1, ((m - 2) % 12) + 1}          # this month or the next or previous
                # too few records to tell (or none dated): don't rule any month out
                likely = len(hit) == 0 or int(r["gbif_records"] or 0) < FEW or bool(hit & near)
                recs.append({"species": r["species"], "month": m, "likelihood": "likely" if likely else "unlikely"})
        months = pd.DataFrame(recs)
        about["by_month"] = (f"likely = recorded in that month or the month either side; species with fewer than {FEW} "
                             "records, or none dated, are likely in every month; unlikely otherwise")
    return out, months, about


def run(args, settings) -> None:
    out_path = Path(args.out or "species_list.csv")
    table, months, about = build(settings, country=args.country, lat=args.lat, lon=args.lon, radius_km=args.radius_km,
                                 taxon=args.taxon, since=args.since, region=args.region, checklist=args.checklist,
                                 include_model_only=args.include_model_only, by_month=args.by_month, offline=args.offline)
    table.to_csv(out_path, index=False)
    out_path.with_suffix(".json").write_text(json.dumps(about, indent=1), encoding="utf-8")
    print(f"{len(table)} species {about['where']} -> {out_path}")
    if about.get("model"):
        m = about["model"]
        print(f"  {m['model']} knows {m['species']} species: {m['recorded_here_but_not_in_model']} recorded here it can't "
              f"recognise; {m['in_model_but_no_records_here']} it knows with no records here"
              + (" (added)" if args.include_model_only else " (left out; --include-model-only adds them)"))
    print(f"  {about.get('to_check', 0)} species marked to check (column 'check')")
    if months is not None:
        mp = out_path.with_name(out_path.stem + "_by_month.csv")
        months.to_csv(mp, index=False)
        print(f"  month by month -> {mp} (use it as species_list for month-aware guesses)")
    print("\nNOTE: " + gbif.CAUTION.replace("(--species-list)", "(--checklist)"))
    print(f"Use it: cehbio run images ... --set species_list={out_path}   or   cehbio validate ... --species-list {out_path}")


def add_command(sub, common) -> None:
    import argparse
    p = sub.add_parser("species-list", parents=[common], help="build a candidate species list for a place (GBIF, model, checklist)",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--country", help="e.g. 'Costa Rica'")
    p.add_argument("--lat", type=float, help="instead of a country: a point...")
    p.add_argument("--lon", type=float)
    p.add_argument("--radius-km", type=float, default=50, help="...and the distance around it (default 50)")
    p.add_argument("--taxon", default="Lepidoptera", help="the group (default Lepidoptera; e.g. Aves for birds)")
    p.add_argument("--since", type=int, metavar="YEAR", help="only GBIF records from this year on, e.g. 1980")
    p.add_argument("--region", help="the AMBER species model's region, to see what it can recognise (cehbio models)")
    p.add_argument("--include-model-only", action="store_true", help="also add species the model knows with no records here")
    p.add_argument("--checklist", help="your national or regional checklist (CSV with a species column): the best source")
    p.add_argument("--by-month", action="store_true", help="also a month-by-month list (month and likelihood columns)")
    p.add_argument("--offline", action="store_true", help="use only what's cached")
    p.add_argument("--out", help="the CSV to write (default species_list.csv)")
    p.set_defaults(func=lambda a: run(a, __import__("ceh_biomonitoring.cli", fromlist=["_settings"])._settings(a)))
