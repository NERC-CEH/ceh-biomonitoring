# CEH Biomonitoring

Tools from the UK Centre for Ecology & Hydrology (UKCEH) for biodiversity monitoring with acoustic recorders:

- **Send your data to UKCEH**, if you collect recordings or images for a UKCEH project.
- **Find birds and bats in your own recordings**, on a laptop, on JASMIN or on another computing cluster.

| What | Tool | Command |
|---|---|---|
| Upload recordings or images to UKCEH | the AMI upload service | `cehbio upload` |
| Birds in audible recordings | **BirdNET** or **Perch** (your choice) | `cehbio run birds` |
| Bats in ultrasonic recordings | **BatDetect2** | `cehbio run bats` |

You only install what you need. Everything shares one environment, called `ceh-biomonitoring`.

UKCEH also offers further analysis as a service, e.g. regional species lists, noise filtering, moth and insect image processing, and reporting. Contact UKCEH if you would like to know more.

---

## Install

You need [Miniforge](https://github.com/conda-forge/miniforge) (conda) once. Then:

```bash
git clone https://github.com/NERC-CEH/ceh-biomonitoring.git
cd ceh-biomonitoring
./install.sh                 # just uploading
./install.sh bats            # + bats       (or: birds, or: birds bats, or: all)
conda activate ceh-biomonitoring
cehbio pipelines             # what is installed
```

To add another pipeline later, run `./install.sh <name>` again. Rerunning it also updates everything to the newest model releases.

> **On JASMIN:** install on a sci server (e.g. `ssh sci-vm-04`), not a login node. The installer works around JASMIN's small `/tmp` limit for you.

## Sending your data to UKCEH

You need an **upload service username and password**. They are given to partners working with UKCEH where it has been agreed that UKCEH will process your data. To get them, contact **Alyssa Duffy** at [alyduf@ceh.ac.uk](mailto:alyduf@ceh.ac.uk).

```bash
conda activate ceh-biomonitoring
cehbio upload
```

`cehbio upload` asks you, step by step, for:

- your name
- the country and deployment, picked from a list
- what you're uploading: images, audible recordings or ultrasound recordings
- which folder to upload from, e.g. your SD card

**Try a test of 10 files first.** You can say yes to this when it asks.

If the upload stops part-way, for example because your laptop goes to sleep, **run `cehbio upload` again**. Files that already went up are skipped.

Every file is logged, so you can always check what was sent. The log lives in `upload_logs/` inside your outputs folder.

If you upload often, you can give all the answers as options and let it run unattended. See `cehbio upload --help`.

## Finding birds and bats in your recordings

Point it at a folder of recordings. Your original files are never moved, changed or deleted.

```bash
cehbio run bats  --folder E:/my_recordings --deployment wood-1
cehbio run birds --folder E:/my_recordings --deployment wood-1 --set model=perch
cehbio run birds --folder E:/my_recordings --deployment wood-1 --set lat=51.6 --set lon=-1.1 --set week=20
```

**Test on a few files first:** add `--max-files 20`.

If a run is interrupted, run the same command again: finished parts are skipped.

On a computing cluster with Slurm, such as JASMIN, `cehbio run` sends the work out as a Slurm array job. Use `--dry-run` to see the job script without submitting it.

### Recorders and file names

Say which recorder you used, and every result gets the date and time read from its file name:

```bash
cehbio run bats --folder E:/rec --deployment wood-1 --device audiomoth
cehbio devices                                   # the recorders it knows
```

If your file names are different, describe them in plain language:

```bash
--timestamp-pattern "SERIAL_YYYYMMDD_hhmmss"     # e.g. 2MM24834_20240705_043000.wav
```

`YYYY MM DD hh mm ss` are the date and time parts, `SERIAL` is the recorder's ID and `*` means anything. Capital `MM` is the month and small `mm` is minutes.

### Choosing birds settings

| Setting | BirdNET | Perch |
|---|---|---|
| choose the model | `model=birdnet` (default) | `model=perch` |
| location filter | `lat=…`, `lon=…`, `week=1-48`: BirdNET's own filter of likely species | – |
| cut-off | `min_conf=0.25` (BirdNET's default) | **none by default**: each 5-second window's top species and score are reported. Set `logit_threshold=…` once you have checked scores against recordings you have listened to |
| only certain species | – | `species_list=my_species.csv` (a `species` column) |

**Always check a sample of results by listening before trusting a cut-off for your sites.**

You can keep settings in a file and use `--config my_settings.yml`, e.g.:

```yaml
model: perch
logit_threshold: 12
```

`cehbio run birds --help` lists every option.

## What you get

Results go in `~/ceh-biomonitoring/outputs/<pipeline>/<place>/inference/<deployment>/`:

- `<deployment>_detections.parquet`: every detection. Open it in R with `arrow::read_parquet()` or in Python with `pandas.read_parquet()`.
- `<deployment>_files.csv`: every file, with its status: detections, no detections, or failed. A failed file is never mistaken for silence.
- `<deployment>_qa.json`: whether everything finished.
- `chunks/*_summary.json`: the **exact model and package versions** used. You always get the newest model releases, and these records keep your results reproducible.

To change where results go, create `~/.config/ceh-biomonitoring/settings.yml`:

```yaml
outputs_root: /path/with/plenty/of/space/ceh-biomonitoring
slurm:                              # on JASMIN or another cluster
  account: <your Slurm account>
```

`cehbio check` shows your settings and anything missing.

## Model licences: check before commercial work

| Model | Licence | Commercial use |
|---|---|---|
| **BirdNET** (model and location filter) | CC BY-NC-SA 4.0 | **No, non-commercial only** |
| Perch v2 | Apache 2.0 | Yes |
| BatDetect2 | see its repository | check |

## Object-store data (optional)

If your recordings are in an S3-compatible object store (e.g. JASMIN's), you can process them without downloading them yourself. Use `--bucket <bucket>` instead of `--folder`, with your key in `~/.config/ceh-biomonitoring/credentials.json`:

```bash
mkdir -p ~/.config/ceh-biomonitoring
cp credentials/credentials.example.json ~/.config/ceh-biomonitoring/credentials.json
nano ~/.config/ceh-biomonitoring/credentials.json      # paste your key and secret
chmod 600 ~/.config/ceh-biomonitoring/credentials.json # only you can read it
cehbio check
```

Never put this file in a repository, share it, or paste it into an email or chat.

## For developers

- **Adding a pipeline:** write one class in `src/ceh_biomonitoring/pipelines/`. The class says what files it wants and how to process a folder of them. Then register it in `pipelines/__init__.py` and add an install extra in `pyproject.toml`. See `pipelines/base.py`.
- **Plug-ins:** other packages can add pipelines, recorders, machine settings and commands through entry points (`ceh_biomonitoring.pipelines`, `.devices`, `.profiles`, `.commands`, `.data`).
- **Tests:** `pip install -e ".[dev]" && pytest`. They need no key and no models.
