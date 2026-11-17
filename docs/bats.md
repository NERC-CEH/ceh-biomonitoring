# Bats: BatDetect2

Finds bat echolocation calls in ultrasonic recordings (e.g. AudioMoth or Song Meter at 192–384 kHz) and suggests the species, using [BatDetect2](https://github.com/macaodha/batdetect2). BatDetect2 was trained on **UK bat species**: elsewhere, treat its species suggestions with great care.

## Install

```bash
./install.sh bats
```

(On Windows, use `[bats]` with the `pip install` line in the [README](../README.md#install).)

**Keep it on the newest models:** `cehbio update` now and then.

## Run

```bash
cehbio run bats --folder E:/my_recordings --deployment wood-1
```

**Test on a few files first:** add `--max-files 20`.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `detection_threshold` | `0.3` | calls scoring below this are left out. Lower finds more calls but more false ones |
| `species_list` | | a CSV with a `species` column (and optionally `month`, so each recording uses its own month's species), e.g. bats recorded near the site: calls of other species are flagged (`in_species_list`) |
| `species_list_action` | `flag` | `remove` drops calls of unlisted species instead |

e.g. `cehbio run bats --folder E:/rec --deployment wood-1 --set detection_threshold=0.5`

## Results

`<deployment>_detections.parquet` has one row per call:

| Column | Meaning |
|---|---|
| `filename` | the recording |
| `start_time`, `end_time` | seconds into the recording |
| `species_name` | BatDetect2's suggested species |
| `class_probability` | how sure it is of the species |
| `detection_probability` | how sure it is that this is a bat call at all |
| `low_freq`, `high_freq` | the call's frequency range (Hz) |
| `event` | the type of sound, e.g. `Echolocation` |
| `file_datetime` | when the recording started, from its file name (see [Recorders](recorders.md)) |

**Check a sample of calls before relying on species.** Many bat species have very similar calls; *Myotis* species in particular are often confused.

See [Running and results](running.md) for the other files you get.

## Licences and citing

**BatDetect2 is non-commercial only** (CC BY-NC 4.0). Licences, sources and what to cite are listed on the [front page](../README.md#models-licences-and-acknowledgements). The exact model versions you used are recorded in each chunk's `_summary.json`.
