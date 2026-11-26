"""Species lists on the GBIF Backbone Taxonomy, for labelling packages.

Each Mothbot package carries a species list, so the expert picks names from it, with GBIF backbone keys
(the integer taxonKeys the AMBER models' gbif_id columns use). The list is laid out like a GBIF
species-list download, the layout Mothbot reads, and holds:

  * the species GBIF has records of in the package's country, for one higher taxon (Lepidoptera unless
    --species-taxon says otherwise), with their number of records there
  * every species the regional model named in the package, matched to the backbone, so a correct
    machine identification is always on the list (even one not yet recorded in GBIF there); the global
    model's too when its machine IDs are shown (--no-blind)
  * or your own list (--species-list): a GBIF species-list download, or any CSV with a species column,
    matched to the backbone the same way

A GBIF country list is a STARTING POINT, not a checklist. It's every species with records GBIF holds for the
country, so it can include misidentifications, old or museum records, vagrants and introduced species, and
it misses species nobody has recorded or shared, especially in poorly recorded regions. We keep only
records marked present, with no location problems GBIF has flagged, and not fossils; --species-since
drops older records. Where a national or regional checklist exists, use it (--species-list), and have
someone who knows the local fauna look over the list.

Why the backbone: since October 2026 GBIF's own downloads use the Catalogue of Life (COL XR), with
different keys. The backbone keeps the keys our models and earlier rounds use.

Everything GBIF sends is kept in the model cache (models.cache_dir/gbif-backbone), so later packages,
and compute nodes without internet, use it; `cehbio update` refreshes it. Without internet and without a
cache, the list has names only (no keys), and the package says so.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

API = "https://api.gbif.org/v1/"
# Records that count towards a country list: everything except fossils.
RECORD_KINDS = ["HUMAN_OBSERVATION", "MACHINE_OBSERVATION", "OBSERVATION", "PRESERVED_SPECIMEN", "MATERIAL_SAMPLE",
                "MATERIAL_CITATION", "LIVING_SPECIMEN", "OCCURRENCE"]
FEW_RECORDS = 5                               # species with fewer records than this are worth a second look
CAUTION = ("A GBIF country list is a starting point, not a checklist: it can include misidentified, old, vagrant "
           "or introduced species, and misses species nobody has recorded there. Use a national or regional "
           "checklist where one exists (--species-list), and have someone who knows the local fauna check it.")
BACKBONE = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"
SOURCE = "gbif-backbone"                      # Mothbot's name for this ID system
COLUMNS = ["taxonKey", "scientificName", "acceptedTaxonKey", "acceptedScientificName", "numberOfOccurrences",
           "taxonRank", "taxonomicStatus", "kingdom", "kingdomKey", "phylum", "phylumKey", "class", "classKey",
           "order", "orderKey", "family", "familyKey", "genus", "genusKey", "species", "speciesKey",
           "iucnRedListCategory", "vernacularName"]
RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]
MAX_AGE_DAYS = 180


def norm(name) -> str:
    return " ".join(str(name).replace("_", " ").split()[:2]).strip()


def cache_dir(settings=None) -> Path:
    from .. import modelstore
    base = (modelstore.cache_dir(settings) if settings is not None
            else Path("~/.cache/ceh-biomonitoring/models").expanduser())
    return base / "gbif-backbone"


class Backbone:
    """GBIF backbone look-ups, cached on disk (safe to use from several threads)."""

    def __init__(self, settings=None, offline: bool = False, workers: int = 8):
        self.dir = cache_dir(settings)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.offline, self.workers = offline, workers
        self._lock = threading.Lock()
        self.taxa = self._load("taxa.json")           # taxonKey -> GBIF record (trimmed)
        self.names = self._load("names.json")         # name -> taxonKey (or None: no match)
        self._dirty = False
        self.failed = 0

    # ----------------------------------------------------------------- cache
    def _load(self, name: str) -> dict:
        try:
            return json.loads((self.dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self) -> None:
        if not self._dirty:
            return
        with self._lock:
            for name, d in (("taxa.json", self.taxa), ("names.json", self.names)):
                tmp = self.dir / (name + ".tmp")
                tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.dir / name)
            self._dirty = False

    # ----------------------------------------------------------------- the API
    def _get(self, path: str, **params):
        if self.offline:
            return None
        url = API + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "ceh-biomonitoring (labelling species lists)"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                time.sleep(1 + attempt * 2)
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == 2:
                    self.failed += 1
                    if self.failed >= 3:
                        self.offline = True                # stop waiting on a machine without internet
                    return None
                time.sleep(1 + attempt * 2)
        return None

    @staticmethod
    def _trim(r: dict) -> dict:
        keep = ["key", "scientificName", "canonicalName", "rank", "taxonomicStatus", "acceptedKey", "accepted",
                "vernacularName", *RANKS, *[f"{k}Key" for k in RANKS]]
        return {k: r.get(k) for k in keep if r.get(k) is not None}

    def taxon(self, key) -> dict | None:
        if key is None or str(key) in ("", "nan", "None"):
            return None
        k = str(int(float(key)))
        if k in self.taxa:
            return self.taxa[k]
        r = self._get(f"species/{k}")
        if not r or r.get("datasetKey") not in (None, BACKBONE):
            return None
        rec = self._trim(r)
        with self._lock:
            self.taxa[k] = rec
            self._dirty = True
        return rec

    def match(self, name: str) -> dict | None:
        n = norm(name)
        if not n:
            return None
        if n in self.names:
            return self.taxon(self.names[n]) if self.names[n] else None
        r = self._get("species/match", name=n, kingdom="Animalia", strict="true")
        if r is None:
            return None                                  # unknown, not "no match": asked again next time
        key = None
        if r and r.get("matchType") in ("EXACT", "FUZZY") and r.get("confidence", 0) >= 90 and r.get("usageKey"):
            key = r["usageKey"]
        with self._lock:
            self.names[n] = key
            self._dirty = True
        return self.taxon(key) if key else None

    def match_all(self, names) -> dict[str, dict | None]:
        names = sorted({norm(n) for n in names if norm(n)})
        with ThreadPoolExecutor(self.workers) as ex:
            found = dict(zip(names, ex.map(self.match, names)))
        self.save()
        return found

    def iso2(self, country: str) -> str | None:
        """A two-letter country code from a code or name (GBIF's own country list, cached)."""
        c = str(country or "").strip()
        if len(c) == 2:
            return c.upper()
        table = self._load("countries.json")
        if not table:
            got = self._get("enumeration/country")
            if got:
                table = {r["iso2"]: r for r in got}
                (self.dir / "countries.json").write_text(json.dumps(table), encoding="utf-8")
        want = c.lower().replace("_", " ")
        for iso2, r in table.items():
            if want in (str(r.get("iso3", "")).lower(), str(r.get("title", "")).lower(), iso2.lower()):
                return iso2
        return None

    def country_name(self, iso2: str | None) -> str | None:
        r = self._load("countries.json").get(str(iso2 or "").upper())
        return r.get("title") if r else None

    def country_counts(self, iso2: str, higher_key: int, refresh: bool = False, since: int | None = None) -> dict[str, int] | None:
        """{speciesKey: number of GBIF records} for a higher taxon in a country, or None if unknown. Only records
        marked present, with no location problem GBIF flagged, and not fossils; since: only from that year on."""
        f = self.dir / "countries" / f"{iso2}_{higher_key}_q2{'_since' + str(since) if since else ''}.json"
        if f.exists() and not refresh:
            d = json.loads(f.read_text(encoding="utf-8"))
            if (date.today() - date.fromisoformat(d["fetched"][:10])).days <= MAX_AGE_DAYS or self.offline:
                return d["counts"]
        counts, offset, step = {}, 0, 1000
        while True:
            filters = dict(occurrenceStatus="PRESENT", hasGeospatialIssue="false", basisOfRecord=RECORD_KINDS)
            if since:
                filters["year"] = f"{int(since)},{date.today().year}"
            r = self._get("occurrence/search", country=iso2, taxonKey=higher_key, limit=0, facet="speciesKey",
                          facetLimit=step, facetOffset=offset, **filters)
            if r is None:
                return (json.loads(f.read_text(encoding="utf-8"))["counts"] if f.exists() else None)
            got = (r.get("facets") or [{}])[0].get("counts", [])
            counts.update({c["name"]: int(c["count"]) for c in got})
            if len(got) < step:
                break
            offset += step
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"fetched": datetime.now(timezone.utc).isoformat(), "country": iso2,
                                 "taxonKey": higher_key, "counts": counts}), encoding="utf-8")
        return counts


# --------------------------------------------------------------------- rows and Mothbot taxa
def row(rec: dict, n_records: int | None = None) -> dict:
    """A GBIF record as a species-list row (the layout of a GBIF species-list download)."""
    status = rec.get("taxonomicStatus") or ""
    syn = "SYNONYM" in status
    out = {"taxonKey": rec.get("key"), "scientificName": rec.get("scientificName") or rec.get("canonicalName"),
           "acceptedTaxonKey": rec.get("acceptedKey") if syn else rec.get("key"),
           "acceptedScientificName": rec.get("accepted") if syn else rec.get("scientificName"),
           "numberOfOccurrences": n_records or 0, "taxonRank": rec.get("rank"), "taxonomicStatus": status,
           "iucnRedListCategory": "", "vernacularName": rec.get("vernacularName") or ""}
    for k in RANKS:
        out[k], out[f"{k}Key"] = rec.get(k) or "", rec.get(f"{k}Key")
    return out


def mothbot_taxon(rec: dict | None, name: str = "", extra_ranks: dict | None = None) -> dict | None:
    """A GBIF record (or just a name) as Mothbot's taxon (TaxonRecord): the binomial as scientificName,
    the epithet in 'species', and the backbone key as taxonID."""
    if rec:
        rank = str(rec.get("rank") or "").lower()
        canon = rec.get("canonicalName") or norm(rec.get("scientificName", ""))
        t = {"scientificName": canon, "taxonRank": rank or None, "taxonID": rec.get("key"), "taxonIDSource": SOURCE,
             "taxonomicStatus": rec.get("taxonomicStatus")}
        for k in RANKS[:-1]:
            if rec.get(k):
                t[k] = rec[k]
        if rank in ("species", "subspecies") and len(canon.split()) > 1:
            t["genus"], t["species"] = canon.split()[0], canon.split()[1]
        if "SYNONYM" in str(rec.get("taxonomicStatus")) and rec.get("acceptedKey"):
            t["acceptedTaxonKey"], t["acceptedScientificName"] = rec["acceptedKey"], rec.get("accepted")
        if rec.get("vernacularName"):
            t["vernacularName"] = rec["vernacularName"]
        t["extras"] = {f"{k}Key": rec[f"{k}Key"] for k in RANKS if rec.get(f"{k}Key")}
        return {k: v for k, v in t.items() if v not in (None, "")}
    n = norm(name)
    if not n:
        return None
    parts = n.split()
    t = {"scientificName": n, "kingdom": "Animalia", "phylum": "Arthropoda", "class": "Insecta", **(extra_ranks or {})}
    if len(parts) > 1:
        t.update(genus=parts[0], species=parts[1], taxonRank="species")
    return t


# --------------------------------------------------------------------- building a list
def build(names, settings=None, country: str | None = None, taxon: str = "Lepidoptera",
          own_list: str | None = None, offline: bool = False, since: int | None = None) -> tuple[pd.DataFrame, dict]:
    """The package's species list. names: the species the models named in it. Returns (list, about)."""
    bb = Backbone(settings, offline=offline)
    about = {"taxonomy": "GBIF Backbone Taxonomy", "checklist_key": BACKBONE, "made": date.today().isoformat(),
             "parts": []}
    rows: dict = {}
    loose: set[str] = set()

    def add(rec, n_records=None):
        if rec and rec.get("key") is not None:
            k = str(rec["key"])
            r = rows.get(k) or row(rec, n_records)
            if n_records:
                r["numberOfOccurrences"] = max(int(r.get("numberOfOccurrences") or 0), int(n_records))
            rows[k] = r

    if own_list:
        t = pd.read_csv(own_list, sep=None, engine="python")
        key_col = next((c for c in ("taxonKey", "speciesKey", "usageKey") if c in t.columns), None)
        name_col = next((c for c in t.columns if c.lower() in ("species", "scientificname", "scientific_name")), None)
        if key_col is None and name_col is None:
            raise SystemExit(f"{own_list} needs a taxonKey or species/scientificName column")
        keys = t[key_col].dropna().astype(str).tolist() if key_col else []
        numeric = sum(k.replace(".0", "").isdigit() for k in keys)
        if keys and numeric >= len(keys) / 2:            # backbone keys: use them as they are
            with ThreadPoolExecutor(bb.workers) as ex:
                for rec in ex.map(bb.taxon, keys):
                    add(rec)
        else:                                             # names (or Catalogue of Life keys): match by name
            for n, rec in bb.match_all(t[name_col].dropna()).items():
                add(rec) if rec else loose.add(n)
        about["parts"].append({"own_list": str(own_list), "rows": len(t)})

    if country:
        iso2 = bb.iso2(country)
        higher = bb.match(taxon) if taxon else None
        counts = bb.country_counts(iso2, higher["key"], since=since) if iso2 and higher else None
        if counts is None:
            about["parts"].append({"country": country, "taxon": taxon, "note": "GBIF not reachable and nothing "
                                   "cached: the list has only the species the models named"})
        else:
            with ThreadPoolExecutor(bb.workers) as ex:
                for (k, n), rec in zip(counts.items(), ex.map(bb.taxon, list(counts))):
                    add(rec, n)
            about["country_name"] = bb.country_name(iso2)
            about["parts"].append({"country": country, "iso2": iso2, "taxon": taxon, "taxon_key": higher["key"],
                                   "species": len(counts), "since": since,
                                   "few_records": sum(1 for n in counts.values() if int(n) < FEW_RECORDS),
                                   "filters": "occurrenceStatus=PRESENT, no geospatial issues, no fossils"
                                              + (f", records from {since} on" if since else ""),
                                   "source": f"{API}occurrence/search?country={iso2}"
                                   f"&taxonKey={higher['key']}&facet=speciesKey"})
            about["caution"] = CAUTION

    named = bb.match_all(names)
    for n, rec in named.items():
        add(rec) if rec else loose.add(n)
    about["parts"].append({"model_names": len(named), "matched": sum(v is not None for v in named.values())})
    bb.save()

    out = pd.DataFrame(list(rows.values()), columns=COLUMNS)
    if loose:                                             # names GBIF doesn't know (or couldn't be asked about)
        extra = pd.DataFrame([{"scientificName": n, "taxonRank": "SPECIES" if len(n.split()) > 1 else "",
                               "kingdom": "Animalia", "phylum": "Arthropoda", "class": "Insecta",
                               "genus": n.split()[0], "species": n if len(n.split()) > 1 else "",
                               "taxonomicStatus": "", "numberOfOccurrences": 0} for n in sorted(loose)],
                             columns=COLUMNS)
        out = pd.concat([out, extra], ignore_index=True)
        about["not_on_backbone"] = sorted(loose)
    for c in [c for c in COLUMNS if c.endswith("Key") or c == "acceptedTaxonKey"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").astype("Int64")
    out = out.sort_values(["order", "family", "scientificName"], na_position="last").reset_index(drop=True)
    about["rows"], about["with_keys"] = len(out), int(out["taxonKey"].notna().sum())
    about["offline"] = bb.offline
    return out, about


def lookup(settings=None, offline: bool = False) -> Backbone:
    return Backbone(settings, offline=offline)


def refresh(settings=None) -> None:
    """For cehbio update: re-fetch every country list in the cache, and retry names that couldn't be
    looked up before."""
    bb = Backbone(settings)
    files = sorted((bb.dir / "countries").glob("*.json")) if (bb.dir / "countries").is_dir() else []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        got = bb.country_counts(d["country"], d["taxonKey"], refresh=True)
        print(f"  GBIF backbone list {d['country']} (taxon {d['taxonKey']}): "
              + (f"{len(got)} species" if got is not None else "GBIF not reachable, kept the cached list"))
    if not files:
        print("  No GBIF species lists cached yet (they're fetched the first time a package needs one).")
