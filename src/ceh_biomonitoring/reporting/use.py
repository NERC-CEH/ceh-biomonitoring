"""Commercial or not: every project's reports say which, because it decides what may be used.

  noncommercial   weather from Open-Meteo (free for non-commercial use)
  commercial      weather from ERA5-Land (any use, with credit; needs your own free Copernicus key, set up
                  once with `cehbio weather-setup`), and a warning for any model that is licensed for
                  non-commercial use only (BirdNET, BatDetect2, the moth species models)

Give it with --use commercial or --use noncommercial (in R: use = "commercial"). If you don't, you're
asked, and the answer is remembered for the project (in report/data/about.json), so you're asked once.
The R package makes the same choices with the same words (r/R/use.R).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

USES = ("commercial", "noncommercial")
EXPLAIN = ("Is this a commercial project (work for a paying client or business)? It decides what the report may "
           "use: non-commercial projects get weather from Open-Meteo; commercial ones get ERA5-Land weather (needs a "
           "free Copernicus key, set up once) and a warning for any model licensed for non-commercial use only.")
NC_MODELS = [  # (words in the model names, what to call it)
    (("birdnet",), "BirdNET (its model is CC BY-NC-SA 4.0)"),
    (("batdetect",), "BatDetect2 (CC BY-NC 4.0)"),
    (("moth-species", "moth_species", "regional species"), "the moth species models (CC BY-NC 4.0)"),
]


def _interactive() -> bool:
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return ""


def remembered(out: Path) -> str | None:
    try:
        u = json.loads((Path(out) / "about.json").read_text(encoding="utf-8")).get("use")
        return u if u in USES else None
    except (OSError, ValueError):
        return None


def decide(given: str | None, out: Path) -> str:
    """The project's use: as given, else as before for this project, else asked."""
    if given:
        g = given.lower().replace("-", "").replace("_", "").replace(" ", "")
        if g not in USES:
            raise SystemExit(f"--use must be commercial or noncommercial, not '{given}'.")
        return g
    before = remembered(out)
    if before:
        print(f"  This project is {before} (as before). Give --use to change it.")
        return before
    if not _interactive():
        raise SystemExit("Say whether this project is commercial: add --use commercial or --use noncommercial "
                         "(in R: use = \"commercial\" or \"noncommercial\"). " + EXPLAIN)
    print(EXPLAIN)
    while True:
        a = _ask("Commercial project? (yes/no): ")
        if a in ("y", "yes"):
            return "commercial"
        if a in ("n", "no"):
            return "noncommercial"
        print("Please type yes or no.")


def weather_for(use: str, weather: str | None, settings=None) -> str:
    """The weather source for this use: chosen for you, checked, and with ERA5-Land set up if it isn't yet."""
    if weather == "none":
        return "none"
    if use == "noncommercial":
        return weather or "open-meteo"
    if weather == "open-meteo":
        raise SystemExit("This is a commercial project, and Open-Meteo's free weather is for non-commercial use only. "
                         "Use --weather era5-land (or --weather none).")
    from .copernicus import HOW_TO, check_key, saved_key, setup
    if saved_key(settings):
        return "era5-land"
    print("\nCommercial project: the weather comes from ERA5-Land, which needs your own free Copernicus key, and "
          "there isn't one on this computer yet.")
    if not _interactive():
        raise SystemExit(f"No Copernicus key yet. {HOW_TO} Or use --weather none for a report without weather.")
    if _ask("Set it up now? It takes about 5 minutes. (yes/no): ") in ("y", "yes"):
        if setup(settings) == 0 and saved_key(settings) and check_key(saved_key(settings))[0] in ("ok", "no licence"):
            return "era5-land"
    if _ask("Make the tables without weather for now? You can add it later with --refresh. (yes/no): ") in ("y", "yes"):
        return "none"
    raise SystemExit(f"Stopped. {HOW_TO}")


def licence_notes(use: str, model_names: list[str], pipeline: str) -> list[str]:
    """For commercial projects: one note per model whose licence is non-commercial only."""
    if use != "commercial":
        return []
    text = " ".join(model_names).lower() + " " + pipeline
    hit = [label for words, label in NC_MODELS if any(w in text for w in words)]
    if pipeline == "images" and NC_MODELS[2][1] not in hit:
        hit.append(NC_MODELS[2][1])                 # every images run names species with these models
    if pipeline == "bats" and NC_MODELS[1][1] not in hit:
        hit.append(NC_MODELS[1][1])
    return [f"Commercial project: {h} is licensed for non-commercial use only. Check with its makers before using "
            f"these results commercially." for h in hit]
