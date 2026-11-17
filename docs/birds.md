# Birds: BirdNET or Perch

Finds bird calls and songs in audible recordings (e.g. AudioMoth or Song Meter, 24–48 kHz). You choose the model:

| | **BirdNET** (default) | **Perch** |
|---|---|---|
| Made by | the K. Lisa Yang Center for Conservation Bioacoustics (Cornell) and Chemnitz University of Technology | Google |
| Species | about 6,000 worldwide | about 15,000 worldwide, including some non-birds |
| Location filter | yes: give a latitude, longitude and week to keep only species likely there | no: you can give your own species list |
| Scores | confidence from 0 to 1 | a "logit" score with no fixed range: higher is more certain |
| Licence | model CC BY-NC-SA 4.0: **non-commercial use only** | Apache 2.0: commercial use allowed |

## Install

```bash
./install.sh birds
```

(On Windows, use `[birds]` with the `pip install` line in the [README](../README.md#install).)

The first Perch run downloads the model (about 400 MB) from Kaggle. After that it is reused.

**Keep it on the newest models:** `cehbio update` now and then.

## Run

```bash
cehbio run birds --folder E:/my_recordings --deployment wood-1
cehbio run birds --folder E:/my_recordings --deployment wood-1 --set lat=51.6 --set lon=-1.1 --set week=20
cehbio run birds --folder E:/my_recordings --deployment wood-1 --set model=perch
```

**Test on a few files first:** add `--max-files 20`.

## Settings

| Setting | BirdNET | Perch |
|---|---|---|
| choose the model | `model=birdnet` (default) | `model=perch` |
| location filter | `lat=…`, `lon=…`, `week=1-48`: BirdNET's own filter of likely species. Leave out `week` for the whole year | – |
| cut-off | `min_conf=0.25` (BirdNET's default) | **none by default**: each 5-second window's top species and score are reported. Set `logit_threshold=…` once you have checked scores against recordings you have listened to |
| more species per window | – | `top_n=3` (when there is no cut-off) |
| overlapping windows | `overlap=1.5` (seconds) | `hop_seconds=2.5` (the default, 5, means no overlap) |
| only certain species | `species_list=my_species.csv` (a `species` column of scientific names, and optionally a `month` column so each recording uses its own month's species) | the same |
| re-threshold later without re-running | – | `save_scores=true`: keeps every window's scores |

**Always check a sample of results by listening before trusting a cut-off for your sites.** Scores mean different things at different sites, and both models make mistakes, especially with insects, rain, wind and distant or overlapping calls.

You can keep settings in a file and use `--config my_settings.yml`, e.g.:

```yaml
model: perch
hop_seconds: 2.5
logit_threshold: 12
```

`cehbio run birds --help` lists every option.

## Results

`<deployment>_detections.parquet` has one row per detection:

| Column | Meaning |
|---|---|
| `filename` | the recording |
| `start_time`, `end_time` | seconds into the recording |
| `species_name` | scientific name |
| `common_name` | English name (BirdNET only) |
| `confidence` (BirdNET) or `logit` (Perch) | how sure the model is |
| `file_datetime` | when the recording started, from its file name (see [Recorders](recorders.md)) |

See [Running and results](running.md) for the other files you get.

## Licences and citing

**BirdNET is non-commercial only**; Perch can be used commercially. Licences, sources and what to cite are listed on the [front page](../README.md#models-licences-and-acknowledgements). The exact model versions you used are recorded in each chunk's `_summary.json`.
