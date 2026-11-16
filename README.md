# CEH Biomonitoring

Tools from the UK Centre for Ecology & Hydrology (UKCEH) for biodiversity monitoring with automated recorders and light traps.

- **Send your data to UKCEH**, if you collect recordings or images for a UKCEH project.
- **Find birds, bats and insects in your own data**, on a laptop, on JASMIN or on another computing cluster.

| What | Tool | Command | Guide |
|---|---|---|---|
| Upload recordings or images to UKCEH | the UKCEH upload service | `cehbio upload` | [Upload guide](docs/upload-guide.md) |
| Birds in audible recordings | **BirdNET** or **Perch** (your choice) | `cehbio run birds` | [Birds](docs/birds.md) |
| Bats in ultrasonic recordings | **BatDetect2** | `cehbio run bats` | [Bats](docs/bats.md) |
| Moths and other insects in light-trap images | insect detection, moth/non-moth, order and regional species models for AMI traps and LepiSense | `cehbio run images` | [Images](docs/images.md) |

You only install what you need. Everything shares one environment, called `ceh-biomonitoring`.

UKCEH also offers further analysis as a service, e.g. regional species lists, noise filtering, expert verification and reporting. Contact UKCEH if you would like to know more.

---

## Install

You need [Miniforge](https://conda-forge.org/download/) (conda) once. Then, on Mac, Linux or JASMIN:

```bash
git clone https://github.com/NERC-CEH/ceh-biomonitoring.git
cd ceh-biomonitoring
./install.sh                 # just uploading
./install.sh bats            # + bats       (or: birds, images, birds bats, or: all)
conda activate ceh-biomonitoring
cehbio pipelines             # what is installed
```

To add another pipeline later, run `./install.sh <name>` again.

**Always on the newest models:** run `cehbio update` now and then. It gets the newest code, model lists, packages and models for every pipeline you have installed (BirdNET, Perch, BatDetect2 and the image models). `cehbio versions` shows what you're using, and every result records the exact versions that made it.

**On Windows**, in the **Miniforge Prompt**:

```
conda create -n ceh-biomonitoring python=3.11 -y
conda activate ceh-biomonitoring
pip install "ceh-biomonitoring[bats] @ https://github.com/NERC-CEH/ceh-biomonitoring/archive/refs/heads/main.zip"
```

Put the pipelines you want in the brackets, e.g. `[birds]`, `[images]`, `[birds,bats]` or `[all]`. Leave out the brackets for uploading only.

> **On JASMIN:** install on a sci server (e.g. `ssh sci-vm-04`), not a login node. The installer works around JASMIN's small `/tmp` limit for you.

## Quick start

```bash
cehbio run bats --folder E:/my_recordings --deployment wood-1 --max-files 20
```

This finds bat calls in the first 20 recordings in `E:/my_recordings`. Your original files are never moved, changed or deleted. Remove `--max-files 20` to run on everything.

Then see:

- the guide for your pipeline: [birds](docs/birds.md), [bats](docs/bats.md) or [images](docs/images.md)
- [Recorders and file names](docs/recorders.md): so every result gets its date and time
- [Running and results](docs/running.md): big jobs, computing clusters, what you get and where it goes

## Models, licences and acknowledgements

This toolkit runs models made by other teams. **Check each model's licence before commercial work**, and please **cite the models you used** if you publish. Every run records the exact model versions it used, with checksums, in `chunks/*_summary.json`.

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

**Acknowledgements.** The images pipeline's processing builds on [amber-inferences](https://github.com/AMI-system/amber-inferences) (MIT) from the AMI system team, and on the AMBER and INSPIRE projects. We thank all the teams above for making their models and code openly available.

## Getting help

Run any command with `--help`, e.g. `cehbio run birds --help`. `cehbio check` shows your settings and anything missing.

For questions about uploading data to UKCEH, contact **Alyssa Duffy** at [alyduf@ceh.ac.uk](mailto:alyduf@ceh.ac.uk). Problems with the code: please open an issue.

## Licence

The code is MIT-licensed (see [LICENSE](LICENSE)). The models have their own licences, above.

## For developers

See [docs/developers.md](docs/developers.md): adding a pipeline, plug-ins and tests.
