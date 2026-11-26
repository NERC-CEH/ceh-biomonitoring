"""cehbio species-list: GBIF records in an area, the region's model, your checklist, and month by month."""
from __future__ import annotations

import pandas as pd
import pytest

from ceh_biomonitoring import specieslist as SL
from ceh_biomonitoring.validation import gbif

TAXA = {
    797: {"key": 797, "scientificName": "Lepidoptera", "canonicalName": "Lepidoptera", "rank": "ORDER"},
    1: {"key": 1, "canonicalName": "Agrius convolvuli", "species": "Agrius convolvuli", "family": "Sphingidae", "genus": "Agrius", "rank": "SPECIES"},
    2: {"key": 2, "canonicalName": "Utetheisa ornatrix", "species": "Utetheisa ornatrix", "family": "Erebidae", "genus": "Utetheisa", "rank": "SPECIES"},
    3: {"key": 3, "canonicalName": "Rare vagrans", "species": "Rare vagrans", "family": "Erebidae", "genus": "Rare", "rank": "SPECIES"},
    4: {"key": 4, "canonicalName": "Model onlyus", "species": "Model onlyus", "family": "Noctuidae", "genus": "Model", "rank": "SPECIES"},
}
# records by month: species 1 only in June-July (many), 2 all year, 3 a single record in March
MONTHS = {1: {6: 40, 7: 30}, 2: {m: 10 for m in range(1, 13)}, 3: {3: 1}}


@pytest.fixture(autouse=True)
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(gbif, "cache_dir", lambda settings=None: tmp_path / "cache")
    by_name = {t["canonicalName"]: k for k, t in TAXA.items()}
    asked = []

    def get(self, path, **p):
        if path == "species/match":
            k = by_name.get(p["name"])
            return {"usageKey": k, "matchType": "EXACT", "confidence": 99} if k else {"matchType": "NONE"}
        if path.startswith("species/"):
            t = TAXA.get(int(path.split("/")[1]))
            return dict(t, datasetKey=gbif.BACKBONE) if t else None
        if path == "enumeration/country":
            return [{"iso2": "AI", "iso3": "AIA", "title": "Anguilla"}]
        if path == "occurrence/search":
            asked.append(p)
            m = p.get("month")
            got = [{"name": str(k), "count": (v.get(m, 0) if m else sum(v.values()))} for k, v in MONTHS.items()]
            return {"facets": [{"counts": [g for g in got if g["count"]][p["facetOffset"]:]}]}
        return None
    monkeypatch.setattr(gbif.Backbone, "_get", get)
    monkeypatch.setattr(SL, "model_species", lambda settings, region: ("moth-species-test-v1",
                                                                         ["Agrius convolvuli", "Model onlyus", "Erebidae"]))
    return asked


def test_list_from_gbif_model_and_checklist(tmp_path, fake):
    ck = tmp_path / "checklist.csv"
    pd.DataFrame({"species": ["Agrius convolvuli", "Utetheisa ornatrix"]}).to_csv(ck, index=False)
    t, months, about = SL.build(country="Anguilla", region="test", checklist=str(ck), by_month=True)
    row = {r.species: r for r in t.itertuples()}
    assert set(row) == {"Agrius convolvuli", "Utetheisa ornatrix", "Rare vagrans"}          # model-only left out
    assert row["Agrius convolvuli"].in_model == "yes" and row["Utetheisa ornatrix"].in_model == "no"
    assert "the model can't recognise it" in row["Utetheisa ornatrix"].check
    assert "only 1 GBIF record here" in row["Rare vagrans"].check and "not on your checklist" in row["Rare vagrans"].check
    assert row["Agrius convolvuli"].check == "" and row["Agrius convolvuli"].sources == "GBIF; model; checklist"
    assert about["model"]["in_model_but_no_records_here"] == 1 and "starting point" in about["caution"]
    m = months.set_index(["species", "month"])["likelihood"]
    assert m["Agrius convolvuli", 6] == "likely" and m["Agrius convolvuli", 5] == "likely" and m["Agrius convolvuli", 1] == "unlikely"
    assert (months[months.species == "Rare vagrans"].likelihood == "likely").all()          # too few records to tell
    q = fake[0]
    assert q["country"] == "AI" and q["occurrenceStatus"] == "PRESENT" and "FOSSIL_SPECIMEN" not in q["basisOfRecord"]


def test_radius_and_model_only(fake):
    t, _, about = SL.build(lat=18.2, lon=-63.05, radius_km=20, region="test", include_model_only=True, since=1990)
    assert "Model onlyus" in set(t.species) and "no GBIF records here" in t.set_index("species").loc["Model onlyus", "check"]
    assert fake[0]["geoDistance"] == "18.2,-63.05,20km" and fake[0]["year"].startswith("1990,")
    assert about["where"].startswith("within 20 km")
