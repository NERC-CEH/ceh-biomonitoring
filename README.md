# CEH Biomonitoring

Tools from the UK Centre for Ecology & Hydrology (UKCEH) for biodiversity monitoring with automated recorders and light traps.

- **Send your data to UKCEH**, if you collect recordings or images for a UKCEH project.
- **Find birds, bats and insects in your own data**, on a laptop, on JASMIN or on another computing cluster.

| What | Tool | Command | Guide |
|---|---|---|---|
| Upload recordings or images to UKCEH | the AMI upload service | `cehbio upload` | [Upload guide](docs/upload-guide.md) |
| Birds in audible recordings | **BirdNET** or **Perch** (your choice) | `cehbio run birds` | [Birds](docs/birds.md) |
| Bats in ultrasonic recordings | **BatDetect2** | `cehbio run bats` | [Bats](docs/bats.md) |
| Moths and other insects in light-trap images | detection and classification models for AMI traps and LepiSense | `cehbio run images` | *coming soon* |

You only install what you need. Everything shares one environment, called `ceh-biomonitoring`.

UKCEH also offers further analysis as a service, e.g. regional species lists, noise filtering, expert verification and reporting. Contact UKCEH if you would like to know more.

---

## Install

You need [Miniforge](https://conda-forge.org/download/) (conda) once. Then, on Mac, Linux or JASMIN:

```bash
git clone https://github.com/NERC-CEH/ceh-biomonitoring.git
cd ceh-biomonitoring
./install.sh                 # just uploading
./install.sh bats            # + bats       (or: birds, or: birds bats, or: all)
conda activate ceh-biomonitoring
cehbio pipelines             # what is installed
```

To add another pipeline later, run `./install.sh <name>` again. Rerunning it also updates everything to the newest model releases.

**On Windows**, in the **Miniforge Prompt**:

```
conda create -n ceh-biomonitoring python=3.11 -y
conda activate ceh-biomonitoring
pip install "ceh-biomonitoring[bats] @ https://github.com/NERC-CEH/ceh-biomonitoring/archive/refs/heads/main.zip"
```

Put the pipelines you want in the brackets, e.g. `[birds]`, `[birds,bats]` or `[all]`. Leave out the brackets for uploading only.

> **On JASMIN:** install on a sci server (e.g. `ssh sci-vm-04`), not a login node. The installer works around JASMIN's small `/tmp` limit for you.

## Quick start

```bash
cehbio run bats --folder E:/my_recordings --deployment wood-1 --max-files 20
```

This finds bat calls in the first 20 recordings in `E:/my_recordings`. Your original files are never moved, changed or deleted. Remove `--max-files 20` to run on everything.

Then see:

- the guide for your pipeline: [birds](docs/birds.md) or [bats](docs/bats.md)
- [Recorders and file names](docs/recorders.md): so every result gets its date and time
- [Running and results](docs/running.md): big jobs, computing clusters, what you get and where it goes

## Model licences: check before commercial work

| Model | Licence | Commercial use |
|---|---|---|
| **BirdNET** (model and location filter) | CC BY-NC-SA 4.0 | **No, non-commercial only** |
| Perch v2 | Apache 2.0 | Yes |
| BatDetect2 | see its repository | check |

## Getting help

Run any command with `--help`, e.g. `cehbio run birds --help`. `cehbio check` shows your settings and anything missing.

For questions about uploading data to UKCEH, contact **Alyssa Duffy** at [alyduf@ceh.ac.uk](mailto:alyduf@ceh.ac.uk). Problems with the code: please open an issue.

## For developers

See [docs/developers.md](docs/developers.md): adding a pipeline, plug-ins and tests.
