"""Reading the experts' answers back, next to what the model said, as one table per selection.

  Mothbot packages   the experts' 03_classifications/<initials>.ndjson (latest answer per crop per expert),
                     from the package folders or their .zip files sent back
  audio clips        the filled-in validation_sheet.csv, or model_check_sheet.csv with its key file

Columns: selection_id, unit_id, site, species (the model's), expert, expert_label, agrees (the model and
the expert name the same species: True/False; empty when the expert didn't name one), plus what the
expert marked (error, morphospecies, notes).
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd


def _two_words(s) -> str:
    return " ".join(str(s or "").split()[:2]).lower()


def _mothbot_answers(paths: list[Path]) -> pd.DataFrame:
    rows = []
    for p in paths:
        files: list[tuple[str, str]] = []
        if p.suffix == ".zip":
            with zipfile.ZipFile(p) as z:
                files = [(n, z.read(n).decode("utf-8")) for n in z.namelist()
                         if "/03_classifications/" in f"/{n}" and n.endswith(".ndjson") and not n.endswith("_bot.ndjson")]
        else:
            for f in p.rglob("03_classifications/*.ndjson"):
                if f.name != "_bot.ndjson":
                    files.append((str(f), f.read_text(encoding="utf-8")))
        for name, text in files:
            for line in text.splitlines():
                if line.strip():
                    c = json.loads(line)
                    if c.get("classifier_type") == "bot":
                        continue
                    t = c.get("taxon") or {}
                    rows.append({"detection_id": c.get("patch_id"), "expert": c.get("classifier_id"),
                                 "expert_label": c.get("label"), "expert_rank": t.get("taxonRank"),
                                 "expert_scientific_name": t.get("scientificName"),
                                 "expert_taxon_key": t.get("taxonID"), "expert_taxon_keys_from": t.get("taxonIDSource"),
                                 "expert_species_list": c.get("species_list"),
                                 "expert_order": t.get("order"), "morphospecies": c.get("morphospecies"),
                                 "marked_error": c.get("is_error"), "classified_at": c.get("classified_at"),
                                 "package": p.name})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return (df.sort_values("classified_at").drop_duplicates(["detection_id", "expert"], keep="last")
            .reset_index(drop=True))


def mothbot(selection: pd.DataFrame, paths: list[Path]) -> pd.DataFrame:
    ans = _mothbot_answers(paths)
    if ans.empty:
        raise SystemExit("No experts' answers found (03_classifications/<initials>.ndjson) in what was given.")
    keep = ["selection_id", "purpose", "unit_id", "detection_id", "site", "deployment_id", "period", "species",
            "score", "why", "noise_class", "image_path"]
    out = ans.merge(selection[[c for c in keep if c in selection.columns]], on="detection_id", how="left")
    named = out["expert_rank"].eq("species")
    out["agrees"] = pd.Series(pd.NA, index=out.index, dtype="boolean")
    out.loc[named, "agrees"] = [_two_words(a) == _two_words(b) for a, b in
                                zip(out.loc[named, "expert_label"], out.loc[named, "species"])]
    return out


def audio(sheet: Path, key: Path | None = None) -> pd.DataFrame:
    s = pd.read_csv(sheet)
    if "what_you_hear" in s.columns:                       # blind: the model's labels are in the key file
        key = key or Path(sheet).with_name("model_labels_KEY_do_not_send.csv")
        k = pd.read_csv(key)
        s = s.merge(k[["clip_id", "species", "english_name", "score", "unit_id"]], on="clip_id", how="left")
        s["expert_label"] = s["what_you_hear"]
        s["agrees"] = [pd.NA if pd.isna(h) or not str(h).strip() else
                       (_two_words(sp) in str(h).lower() or (str(en).lower() in str(h).lower() if en else False))
                       for h, sp, en in zip(s["what_you_hear"], s["species"], s["english_name"].fillna(""))]
    else:
        col = next(c for c in s.columns if c.startswith("correct"))
        v = s[col].astype(str).str.strip().str.upper().str[:1]
        s["agrees"] = v.map({"Y": True, "N": False})
        s["expert_label"] = s[col]
    return s.rename(columns={"clip_id": "selection_id"})
