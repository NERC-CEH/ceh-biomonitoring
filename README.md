# CEH Biomonitoring

Tools from the UK Centre for Ecology & Hydrology (UKCEH) for monitoring wildlife with automated recorders and light traps: find birds, bats and moths in your recordings and photos, have the results checked by experts, and turn them into tables, reports and videos. On a laptop, on JASMIN or on another computing cluster, in Python or in R.

**Sending data to UKCEH for a project?** You only need [Setting up your sites](docs/setting-up-sites.md) and the [Upload guide](docs/upload-guide.md).

**Analysing your own data?** [Install](#install), then follow [Start here](#start-here).

## Contents

1. [What it does](#what-it-does)
   - [Send your data to UKCEH](#1-send-your-data-to-ukceh)
   - [Find wildlife in your recordings and photos](#2-find-wildlife-in-your-recordings-and-photos)
   - [Have the results checked by experts](#3-have-the-results-checked-by-experts)
   - [Analysis and reporting](#4-analysis-and-reporting)
   - [Visualisation](#5-visualisation)
2. [Install](#install)
3. [Start here](#start-here)
4. [Using R](#using-r)
5. [Your results folder](#your-results-folder)
6. [Models, licences and acknowledgements](#models-licences-and-acknowledgements)
7. [Help, words used, and the repository](#help)

---

## What it does

### 1. Send your data to UKCEH

For partners collecting recordings or photos for a UKCEH project. No coding needed.

| | Command | Guide |
|---|---|---|
| Ask for a deployment (one device, one site, one survey) | `cehbio deployments request` | [Setting up your sites](docs/setting-up-sites.md) |
| Upload recordings or photos, with a log so nothing is sent twice | `cehbio upload` | [Upload guide](docs/upload-guide.md) |

### 2. Find wildlife in your recordings and photos

| What | Models | Command | Guide |
|---|---|---|---|
| **Birds** in audible recordings | BirdNET or Perch (your choice) | `cehbio run birds` | [Birds](docs/birds.md) |
| **Bats** in ultrasonic recordings | BatDetect2 | `cehbio run bats` | [Bats](docs/bats.md) |
| **Moths and other insects** in light-trap photos (AMI traps, LepiSense) | finding insects, moth or not, insect order, moth species per region; each insect followed from photo to photo | `cehbio run images` | [Images](docs/images.md) |

Before you start: [Recorders and file names](docs/recorders.md) (so every result gets its date and time). For big jobs and clusters: [Running and results](docs/running.md). `cehbio status` shows how far every run has got.

### 3. Have the results checked by experts

The models make mistakes, so their results are suggestions until an expert has checked them.

| | Command | Guide |
|---|---|---|
| Choose fair samples for experts, package them (audio clips with spectrograms, or [Mothbot](https://mothbot-classify.vercel.app) for photos), and read their answers back | `cehbio validate` | [Manual validation](docs/validation.md), [Sampling methods](docs/sampling-methods.md) |

### 4. Analysis and reporting

| | Command | Guide |
|---|---|---|
| **Report tables**: deployments; nights with the weather and the moon over the hours the device worked; individuals; species. They work with [EntoInsights](https://github.com/AMI-system/EntoInsights) | `cehbio report-data` | [Reporting](docs/reporting.md#the-tables) |
| **Summary reports** per deployment and for the project, in HTML, Word and PDF | `cehbio report` | [Reporting](docs/reporting.md) |
| **Commercial projects**: say so once (`--use commercial`) and the weather and licence checks follow | | [Commercial or not](docs/reporting.md#commercial-or-not) |
| **Weather for commercial work** (ERA5-Land): a walkthrough sets up your free Copernicus key | `cehbio weather-setup` | [Weather](docs/reporting.md#weather-for-commercial-work-era5-land) |

### 5. Visualisation

| | Command | Guide |
|---|---|---|
| **A night at the light trap**: every photo in order, insects boxed and named, tracks with trails; or one insect followed close up | `cehbio video` | [Videos and soundscapes](docs/videos.md) |
| **Soundscapes**: each species' best moment with its sound and a moving spectrogram (bats slowed down so you can hear them), and the whole day at a glance | `cehbio soundscape` | [Videos and soundscapes](docs/videos.md) |

UKCEH also offers further analysis as a service: regional species lists, noise filtering, expert verification and reporting. Contact UKCEH if you would like to know more.

---

## Install

Nothing to install first: no Miniforge, conda or admin rights. The installer fetches everything itself and keeps it in one folder of its own. It gets Python 3.11 and the packages through a small program called [uv](https://docs.astral.sh/uv).

**Windows:** download this repository (green **Code** button, then **Download ZIP**), unzip it, and double-click **`install-windows.bat`**. Type what you want (e.g. `bats`, `birds bats`, `videos` or `all`) and press Enter.

**Mac, Linux or JASMIN:**

```bash
git clone https://github.com/NERC-CEH/ceh-biomonitoring.git
cd ceh-biomonitoring
./install.sh bats            # or: birds, images, videos, several (birds bats), or all; nothing = uploading and reports
```

**R:** see [Using R](#using-r).

Then open a **new** terminal (on Windows, **Windows PowerShell** from the Start menu) and type `cehbio pipelines` to see what's installed. Run the installer again with another name to add it.

- **Keep up to date:** `cehbio update` gets the newest code, models and packages. `cehbio versions` shows what you're using, and every result records the exact versions that made it.
- **JASMIN:** install on a sci server (e.g. `ssh sci-vm-04`), not a login node.
- **Where it goes:** `%LOCALAPPDATA%\ceh-biomonitoring` (Windows) or `~/.local/share/ceh-biomonitoring` (Mac, Linux), or the folder in `CEHBIO_HOME`. Prefer conda? `./install.sh --conda bats`.

## Start here

Type each command in a terminal (on Windows, **Windows PowerShell**). No coding is needed.

**1. Check everything is set up.** `cehbio check` shows where your results will go, and whether anything is missing.

**2. Try it on example data** (UK birds, UK bats, moth-trap photos). It says PASS or PROBLEM.

```bash
cehbio examples run bats        # or birds, images, all
```

**3. Run it on your own data**, starting with 20 files:

```bash
cehbio run bats --folder E:/my_recordings --project my-woods --deployment wood-1 --max-files 20
```

- `--folder`: where your recordings or photos are. They are never moved, changed or deleted.
- `--project`: a name for the folder your results go in. Use the same one for every deployment that belongs together.
- `--deployment`: a name for this recorder or trap at this place.

Remove `--max-files 20` to run on everything.

**4. Follow it:** `cehbio status` (or `cehbio status --watch` to keep checking).

**5. Open your results** in `ceh-biomonitoring-results/bats/my-woods/wood-1/` in your user folder. The `.csv` opens in Excel, and `READ ME.txt` says what each file is.

**6. Next:** have them checked by experts ([Manual validation](docs/validation.md)), make a report ([Reporting](docs/reporting.md)) or a video ([Videos and soundscapes](docs/videos.md)).

## Using R

Everything above can be done from R, with the `cehbio` R package. You never need to write Python.

```r
install.packages("remotes")
remotes::install_github("NERC-CEH/ceh-biomonitoring", subdir = "r")
cehbio::cehbio_install("bats")          # fetches what it needs itself: no Miniforge, conda or Quarto to install
```

**No Python at all for:**
- uploading;
- report tables and reports;
- videos and soundscapes.

Only running the models (`cehbio_run()`) uses Python, which `cehbio_install()` sets up for you.

| | R |
|---|---|
| Send your data to UKCEH | `cehbio_deployments()`, `cehbio_request_deployment()`, `cehbio_upload()` |
| Run the models and follow them | `cehbio_run()`, `cehbio_status()` |
| Read the results | `read_results()`, `read_report_data()` |
| Analysis and reporting | `cehbio_report_data()`, `cehbio_report()`, `plot_activity()` ..., `cehbio_weather_setup()` |
| Visualisation | `cehbio_video()`, `cehbio_soundscape()` |
| Anything else | `cehbio("validate", "collect", ...)`: any command |

R and Python make the same report tables, numbers and words. An automatic check compares them on every change. Full guide: [Using the toolkit from R](docs/r.md).

## Your results folder

Each kind of result has its own folder, so birds, bats, images and expert checks never get mixed up:

```
ceh-biomonitoring-results/          in your user folder (cehbio check shows where)
    birds/  bats/  images/          one folder per pipeline
        my-woods/                   one folder per project
            wood-1/                 one folder per deployment: results, READ ME.txt, PROGRESS.txt
                videos/             videos and soundscapes
                working/            the pipeline's own files: you don't need to open these
            report/                 report tables, reports
    labelling/                      expert checks, in steps: 1_sample, 2_for_experts, 3_answers
    examples/   upload_logs/
```

More in [Running and results](docs/running.md#your-results-folder): what each file holds, choosing another folder, and moving results from before November 2026 (`cehbio tidy`).

## Models, licences and acknowledgements

This toolkit runs models made by other teams. **Check each model's licence before commercial work**, and please **cite the models you used** if you publish. Every run records the exact model versions it used, with checksums, in `working/chunks/*_summary.json` in its results folder.

| Pipeline | Model (newest, used by default) | Made by | Source | Licence | Commercial use | Please cite |
|---|---|---|---|---|---|---|
| Birds | **BirdNET** (and its location filter) | K. Lisa Yang Center for Conservation Bioacoustics (Cornell Lab of Ornithology) and Chemnitz University of Technology | [BirdNET-Analyzer](https://github.com/birdnet-team/BirdNET-Analyzer) | code MIT, model CC BY-NC-SA 4.0 | **No** | Kahl, S., Wood, C. M., Eibl, M. & Klinck, H. (2021). BirdNET: a deep learning solution for avian diversity monitoring. *Ecological Informatics* 61, 101236 |
| Birds | **Perch** v2 | Google DeepMind / Google Research | [perch](https://github.com/google-research/perch), [Kaggle](https://www.kaggle.com/models/google/bird-vocalization-classifier) | Apache 2.0 | Yes | see the Perch repository |
| Bats | **BatDetect2** | Mac Aodha et al. (University of Edinburgh and partners) | [batdetect2](https://github.com/macaodha/batdetect2) | CC BY-NC 4.0 | **No** | Mac Aodha, O. et al. (2022). Towards a general approach for bat echolocation detection and classification. *bioRxiv* |
| Images | **flat-bug** M v2: finding insects, with outlines | Svenning, Geissmann et al. | [flat-bug](https://github.com/darsa-group/flat-bug) | MIT | Yes | see the flat-bug repository |
| Images | **Moth vs non-moth** (2024) | Rolnick lab, Mila (AMI project) | [ami-data-companion](https://github.com/RolnickLab/ami-data-companion) | code AGPL-3.0, model: see source | check | see the source repository |
| Images | **Insect order** (10 May 2024) | Bjerge et al., Aarhus University | [MCC24-trap](https://github.com/kimbjerge/MCC24-trap) | code GPL-3.0, model: see source | check | Bjerge, K. et al. (2025). Towards edge processing of images from insect camera traps. *Remote Sensing in Ecology and Conservation*. doi:10.1002/rse2.70007 |
| Images | **Moth species**, one model per region (`cehbio models`) | The Alan Turing Institute and UKCEH, for the AMBER project | this repository's model release | CC BY-NC 4.0 | **No** | the AMBER project |

> ⚠️ The image models are **still in development and far from perfect**: treat their results as suggestions, and have identifications checked by an expert.

The newest version of each model is always used; older image models stay available by name to reproduce past results (`cehbio models`).

**Acknowledgements.** The images pipeline's processing builds on [amber-inferences](https://github.com/AMI-system/amber-inferences) (MIT) from the AMI system team, and on the AMBER and INSPIRE projects. Manual validation packages crops for [Mothbot](https://mothbot-classify.vercel.app) (Digital Naturalism Laboratories) and groups similar crops with [DINOv2](https://github.com/facebookresearch/dinov2) (Meta, Apache 2.0); its species lists come from [GBIF](https://www.gbif.org) on the [GBIF Backbone Taxonomy](https://doi.org/10.15468/39omei). Weather comes from [Open-Meteo](https://open-meteo.com) and Copernicus [ERA5-Land](https://cds.climate.copernicus.eu). We thank all these teams for making their models, code and data openly available.

## Help

Run any command with `--help`, e.g. `cehbio run birds --help`. `cehbio check` shows your settings and anything missing.

For questions about uploading data to UKCEH, contact **Alyssa Duffy** at [alyduf@ceh.ac.uk](mailto:alyduf@ceh.ac.uk). Problems with the code: please open an issue.

### Words used in the guides

| Word | Meaning |
|---|---|
| **pipeline** | one kind of analysis: birds, bats or images |
| **deployment** | one recorder or trap, at one place, over one period |
| **project** | a set of deployments that belong together; their results share a folder |
| **part** (or chunk) | about 100 files, processed together. A cluster runs many parts at once |
| **cluster** | a group of shared computers, e.g. JASMIN, where long jobs run while you do something else |
| **bucket** | a folder in an online object store, where data uploaded to UKCEH is kept |

### What's in this repository

You only need the guides. The rest is there for the toolkit itself. Your results are never saved in here.

| Folder or file | What it is |
|---|---|
| `docs/` | the guides |
| `install-windows.bat`, `install.sh`, `install.ps1` | the installers |
| `src/` | the toolkit (Python) |
| `r/` | the `cehbio` R package |
| `examples/` | small open example data sets, with credits |
| `credentials/` | an *example* credentials file. Your real one goes in `~/.config/ceh-biomonitoring/`, never here |
| `tests/` | checks that the code still works |

**Licence:** the code is MIT-licensed ([LICENSE](LICENSE)); the models have their own licences, above. **Developers:** [docs/developers.md](docs/developers.md) covers adding a pipeline, plug-ins, tests, and keeping the Python and R versions in step.
