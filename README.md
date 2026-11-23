# CEH Biomonitoring

Tools from the UK Centre for Ecology & Hydrology (UKCEH) for biodiversity monitoring with automated recorders and light traps.

- **Send your data to UKCEH**, if you collect recordings or images for a UKCEH project.
- **Find birds, bats and insects in your own data**, on a laptop, on JASMIN or on another computing cluster.

| What | Tool | Command | Guide |
|---|---|---|---|
| Set up your sites (deployments) for uploading | the UKCEH upload service | `cehbio deployments` | [Setting up your sites](docs/setting-up-sites.md) |
| Upload recordings or images to UKCEH | the UKCEH upload service | `cehbio upload` | [Upload guide](docs/upload-guide.md) |
| Birds in audible recordings | **BirdNET** or **Perch** (your choice) | `cehbio run birds` | [Birds](docs/birds.md) |
| Bats in ultrasonic recordings | **BatDetect2** | `cehbio run bats` | [Bats](docs/bats.md) |
| Moths and other insects in light-trap images | insect detection, moth/non-moth, order and regional species models for AMI traps and LepiSense | `cehbio run images` | [Images](docs/images.md) |
| Expert checks of the results (birds, bats, images) | fair samples for experts, packaged as audio clips or for the [Mothbot](https://mothbot-classify.vercel.app) labelling site, and their answers read back | `cehbio validate` | [Manual validation](docs/validation.md), [Sampling methods](docs/sampling-methods.md) |
| Analysis-ready tables: nights with weather and the moon, individuals, species | weather from Open-Meteo or ERA5-Land; works with EntoInsights | `cehbio report-data` | [Reporting](docs/reporting.md#the-tables) |
| Summary reports per deployment and project, in HTML, Word and PDF | | `cehbio report` | [Reporting](docs/reporting.md) |
| Everything from R | the `cehbio` R package | `cehbio_run()`, `cehbio_report()` ... | [From R](docs/r.md) |

You only install what you need. Everything shares one environment, called `ceh-biomonitoring`.

UKCEH also offers further analysis as a service, e.g. regional species lists, noise filtering, expert verification and reporting. Contact UKCEH if you would like to know more.

---

## Install

Nothing to install first: no Miniforge, conda or admin rights. The installer fetches everything itself (Python 3.11 and the packages, through a small program called [uv](https://docs.astral.sh/uv)) and keeps it in one folder of its own.

**On Windows:** download this repository (green **Code** button, then **Download ZIP**), unzip it, and double-click **`install-windows.bat`**. Type the pipelines you want (e.g. `bats`, or `birds bats`, or `all`) and press Enter.

**On Mac, Linux or JASMIN:**

```bash
git clone https://github.com/NERC-CEH/ceh-biomonitoring.git
cd ceh-biomonitoring
./install.sh                 # just uploading and reports
./install.sh bats            # + bats       (or: birds, images, birds bats, or: all)
```

**From R:** `cehbio::cehbio_install("bats")` does the same: see [Using the toolkit from R](docs/r.md).

Then open a **new** terminal (on Windows, **Windows PowerShell** from the Start menu) and type `cehbio pipelines` to see what's installed. To add another pipeline later, run the installer again with its name.

> Everything goes in `%LOCALAPPDATA%\ceh-biomonitoring` (Windows) or `~/.local/share/ceh-biomonitoring` (Mac, Linux), or the folder in the `CEHBIO_HOME` environment variable. Your results go somewhere else (see below). Prefer conda? `./install.sh --conda bats` makes a conda environment called `ceh-biomonitoring`, as before.

**Always on the newest models:** run `cehbio update` now and then. It gets the newest code, model lists, packages and models for every pipeline you have installed (BirdNET, Perch, BatDetect2 and the image models). `cehbio versions` shows what you're using, and every result records the exact versions that made it.

> **On JASMIN:** install on a sci server (e.g. `ssh sci-vm-04`), not a login node. The installer works around JASMIN's small `/tmp` limit for you.

## Start here

**Prefer R?** Everything below can be done from R instead: see [Using the toolkit from R](docs/r.md).


You type each command into a terminal (on Windows, **Windows PowerShell**). No coding is needed.

**1. Check everything is set up.**

```bash
cehbio check
```

This shows where your results will go, and whether anything is missing.

**2. Try it on example data** (UK birds, UK bats, moth-trap photos). It says PASS or PROBLEM.

```bash
cehbio examples run bats        # or birds, images, all
```

**3. Run it on your own data.** Start with 20 files:

```bash
cehbio run bats --folder E:/my_recordings --project my-woods --deployment wood-1 --max-files 20
```

- `--folder`: where your recordings or photos are. They are never moved, changed or deleted.
- `--project`: a name for the folder your results go in. Use the same one for every deployment that belongs together.
- `--deployment`: a name for this recorder or trap at this place.

Remove `--max-files 20` to run on everything.

**4. See how far it has got.**

```bash
cehbio status                   # every run: a progress bar, and roughly how long is left
cehbio status --watch           # keep checking until it's finished
```

**5. Open your results.** They're in your user folder, in `ceh-biomonitoring-results/bats/my-woods/wood-1/`. The `.csv` file opens in Excel, and `READ ME.txt` there says what each file is.

**6. Have the results checked by experts.** See [Manual validation](docs/validation.md).

## Your results folder

Each kind of result has its own folder, so birds, bats, images and labelling never get mixed up:

```
ceh-biomonitoring-results/          in your user folder (cehbio check shows where)
    birds/  bats/  images/          one folder per pipeline
        my-woods/                   one folder per project
            wood-1/                 one folder per deployment: results, READ ME.txt, PROGRESS.txt
                working/            the pipeline's own files: you don't need to open these
    labelling/                      expert checks, in steps: 1_sample, 2_for_experts, 3_answers
    examples/   upload_logs/
```

More in [Running and results](docs/running.md#your-results-folder): what each file holds, choosing another folder, and moving results from before November 2026 (`cehbio tidy`).

## Guides

Read them in this order:

1. [Recorders and file names](docs/recorders.md): so every result gets its date and time
2. the guide for your pipeline: [Birds](docs/birds.md), [Bats](docs/bats.md) or [Images](docs/images.md)
3. [Running and results](docs/running.md): big jobs, computing clusters, following a run, where everything goes
4. [Manual validation](docs/validation.md) and [Sampling methods](docs/sampling-methods.md): expert checks
5. [Reporting](docs/reporting.md): summary reports and report-ready tables, with weather and the moon
6. [Using the toolkit from R](docs/r.md): everything from R, from installing to reports
7. For sending data to UKCEH: [Setting up your sites](docs/setting-up-sites.md) and the [Upload guide](docs/upload-guide.md)

**Words used in the guides:**

| Word | Meaning |
|---|---|
| **pipeline** | one kind of analysis: birds, bats or images |
| **deployment** | one recorder or trap, at one place, over one period |
| **project** | a set of deployments that belong together; their results share a folder |
| **part** (or chunk) | about 100 files, processed together. A cluster runs many parts at once |
| **cluster** | a group of shared computers, e.g. JASMIN, where long jobs run while you do something else |
| **bucket** | a folder in an online object store, where data uploaded to UKCEH is kept |

## What's in this repository

You only need the guides. The rest is there for the toolkit itself.

| Folder or file | What it is |
|---|---|
| `docs/` | the guides |
| `examples/` | small open example data sets, with credits |
| `credentials/` | an *example* credentials file. Your real one goes in `~/.config/ceh-biomonitoring/`, never here |
| `install.sh`, `environment.yml`, `pyproject.toml` | the installer and what it installs |
| `src/` | the code (Python) |
| `r/` | the `cehbio` R package: the toolkit from R ([guide](docs/r.md)) |
| `tests/` | checks that the code still works, for developers |

Your results are never saved in here: they go in your results folder.

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

**Keeping up to date:** the newest version of each model is always used. Run `cehbio update` now and then; `cehbio versions` and `cehbio models` show what you're using. Older image models stay available by name to reproduce past results.

**Acknowledgements.** The images pipeline's processing builds on [amber-inferences](https://github.com/AMI-system/amber-inferences) (MIT) from the AMI system team, and on the AMBER and INSPIRE projects. Manual validation packages crops for [Mothbot](https://mothbot-classify.vercel.app) (Digital Naturalism Laboratories) and groups similar crops with [DINOv2](https://github.com/facebookresearch/dinov2) (Meta, Apache 2.0); its species lists come from [GBIF](https://www.gbif.org) on the [GBIF Backbone Taxonomy](https://doi.org/10.15468/39omei). We thank all the teams above for making their models and code openly available.

## Getting help

Run any command with `--help`, e.g. `cehbio run birds --help`. `cehbio check` shows your settings and anything missing.

For questions about uploading data to UKCEH, contact **Alyssa Duffy** at [alyduf@ceh.ac.uk](mailto:alyduf@ceh.ac.uk). Problems with the code: please open an issue.

## Licence

The code is MIT-licensed (see [LICENSE](LICENSE)). The models have their own licences, above.

## For developers

See [docs/developers.md](docs/developers.md): adding a pipeline, plug-ins and tests.
