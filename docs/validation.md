# Manual validation

The models make mistakes, so results should be checked by experts. `cehbio validate` does this in three steps, the same way for birds, bats and images:

| Step | What it does | Command |
|---|---|---|
| **1. Sample** | chooses *what* the experts check | `cehbio validate sample` |
| **2. Prepare** | packages it for the *platform* they use: audio clips and a spreadsheet, or a [Mothbot](https://mothbot-classify.vercel.app) package | `cehbio validate prepare` |
| **3. Collect** | reads their answers back, next to what the model said | `cehbio validate collect` |

Sampling and packaging are separate, so the rules for choosing what to check stay the same whichever platform is used. A selection is a plain CSV, one row per item.

Everything runs on your own computer, JASMIN, Polar or any other cluster. Files are read from disk when they're there, otherwise from the object store with your own credentials ([Running](running.md)). Add `--slurm` to `sample` or `prepare` to run it as a batch job.

```bash
pip install -e ".[validation]"        # or ./install.sh validation: Mothbot packages and audio clips
```

## The easy way: one project folder

Give each step the same `--project`. Everything then goes in your results folder, one sub-folder per step, and each step finds the newest file from the step before, so there are no paths to type:

```bash
cehbio validate sample images --for all ~/ceh-biomonitoring-results/images/farm1/dep000123 --project farm1
cehbio validate prepare --project farm1                # packages for the experts
#   ... send them, and put what comes back in 3_answers/returned/ ...
cehbio validate collect --project farm1                # their answers, next to what the model said
```

```
ceh-biomonitoring-results/labelling/images/farm1/
    READ ME.txt
    1_sample/          what the experts check  (all_2026-11-19.csv, and its _record.json)
    2_for_experts/     the packages to send them, one folder per selection
    3_answers/         the answers (all_2026-11-19_answers.csv)
        returned/      put the packages or sheets the experts send back here
```

`cehbio status` lists labelling jobs sent to the cluster with `--slurm`. You can still name every file yourself with `--out` and the selection's path, as in the examples below.

## What gets checked: units

Each group's results are first grouped into **units**, so two picks are never the same animal doing the same thing:

| Group | Unit | |
|---|---|---|
| Birds | an **event** | detections of one species in one recording, joined while the pause is up to 60 s (`--max-gap`) |
| Bats | a **pass** | calls of one species in one recording, joined while the pause is up to 1 s. A starting point: check it suits your recordings |
| Images | a **track** | one insect followed through consecutive photos; crops without a track count on their own. Each track is shown by the crop nearest its median species score |

## Three purposes

The same results can be sampled for different jobs. Give earlier selections with `--exclude`, and **nothing is labelled twice**.

| | `--for site-lists` | `--for model` | `--for all` |
|---|---|---|---|
| **Question** | is each species really at each site? | how good is the model, and what would improve it? | label everything |
| **Scope** | **each site** on its own | **all sites in one country**: each country has its own species model, so countries are never mixed | the results given |
| **Which species** | those reported at the site, or only those a `--species-table` lists, plus anything at an unusual time of year | **every** species the model reported: its mistakes are what it learns from | all |
| **How many** | per species per site: birds and bats 2, images 3 | per species per country: birds and bats 50, images 100 | all |
| **Expert sees the model's label?** | audio: yes, "is this right?" | no (blind): "what is this?". The labels are kept in a separate key | |

**Which country:** give `--country`, e.g. `--country "Costa Rica"`. It then applies to every result, and if the results say they're from somewhere else, the sample stops rather than mixing. Without it, the country comes from the results (their bucket or country folder). Countries sharing a species model are sampled together; results from several countries give one selection file per country.

**Unusual months:** species detected in a month their [species list](birds.md) marks *unlikely* are always added to site-lists (an early Swallow is a real record if it's right, so it's checked, not removed). `--no-unusual-months` leaves them out.

**Noise (images):** site-lists also include up to 100 insects per deployment that the moth filter removed (`--noise`), in proportion to their orders and drawn at random (`--seed`), so the expert sees what it removed.

## How picks are spread

So that experts see a fair picture, not just the easiest or busiest cases (the full method, step by step, with what each sample can estimate: [Sampling methods](sampling-methods.md)):

| | |
|---|---|
| **Space** | model: one per site first (busiest sites first), the rest in proportion to what each site has |
| **Confidence** | units are split into bands with equal numbers of units, low to high score, and one is taken from each |
| **Time** | from each band, the unit **furthest in time from those already picked**, so picks reach across the survey (different days, nights, weeks and months, where the data allow) |
| **"best"** | site-lists for birds and bats (`--how best`): the best-scoring unit, then the best on another day, then in another recording. The clearest examples, for a quick "is it there?" check. Images use `--how spread` |

## Birds and bats: audio clips

```bash
# per site: 2 clips per species (only those bird-results lists, with --species-table), plus unusual months
cehbio validate sample birds --for site-lists results/wood-1 --species-table bird_results/wood-1_site_species.csv --out sel/wood-1
cehbio validate prepare sel/wood-1.csv --out to_expert/wood-1

# across all sites in a country: up to 50 events per species, blind, none already chosen
cehbio validate sample birds --for model results/* --country "United Kingdom" --exclude sel/wood-*.csv --out sel/birds_model_r1
cehbio validate prepare sel/birds_model_r1.csv --out to_expert/birds_model_r1

# bats: the same, with passes
cehbio validate sample bats --for site-lists results/barn-1 --out sel/barn-1
cehbio validate prepare sel/barn-1.csv --out to_expert/barn-1
```

Birds get a 30 s clip centred on the strongest detection (`--clip-seconds`). Bats get the whole pass with 1 s either side (`--pad-seconds`), at the recording's own sample rate, ready for bat software. The spreadsheet says where in the clip the model detected the species. Model samples are **blind**: the expert writes what they hear, and the model's labels go in `model_labels_KEY_do_not_send.csv`.

## Images: Mothbot packages

```bash
cehbio validate sample images --for site-lists results/dep000145 results/dep000123 --out sel/sg_sites
cehbio validate sample images --for model results/* --country Singapore --exclude sel/sg_sites.csv --reserve 20 --out sel/sg_model_r1
cehbio validate prepare sel/sg_model_r1.csv --out to_experts/singapore --slurm
```

Each deployment gets one package per labelling round (`--one-package` for one in all):

```
to_experts/singapore/dep000145/2026-11-18_model.zip      what the expert gets
to_experts/singapore/dep000145/2026-11-18_model_provenance.csv   every crop back to its photo, box and model outputs (not sent)
```

| | |
|---|---|
| **Crops** | cut from the original photos with the detector's boxes (nothing is re-detected). Only the photos needed are fetched, one at a time, and not kept |
| **Nights** | noon to noon, named by the evening they start. The folder date is the labelling round, not when photos were taken |
| **Site** | the name Mothbot shows: the project folder of the results (`images/<project>/<deployment>/`), else the country's name. `--site-name Farm 1` sets it yourself |
| **Species list** | every package has one (`species/SpeciesList_<country>_Lepidoptera-GBIF-backbone-<date>.csv`), which Mothbot offers the expert names from. It's on the **GBIF Backbone Taxonomy** (the keys the models' `gbif_id` columns use) and laid out like a GBIF species-list download: the species GBIF has records of in the package's country (Lepidoptera; `--species-taxon Insecta` for more), with their record counts, plus every species the regional model named in the package (and, with `--no-blind`, the global model's guesses too), so a right answer is always on the list. `--species-list <csv>` uses your own list instead (a GBIF download, or any CSV with a species column; it's matched to the backbone), `--no-species-list` leaves it out. What GBIF sends is cached in your model cache, so compute nodes without internet use it; `--slurm` fetches it before the job is sent, and `cehbio update` refreshes it. Species GBIF doesn't know stay on the list by name, and `<package>_species_list.json` (not sent) says where every part came from |
| **Blind** | the models' identifications are left out, so experts label without them (the default). `--no-blind` (or `--show-machine-ids`) adds them in Mothbot's machine-ID format (`03_classifications/_bot.ndjson`): one row per model per crop (the regional species model, the global model with its GBIF key, and the order model: always **our** models' identifications, read from the results and named by model, e.g. `moth-species-singapore-v2`; Mothbot's own classifier, BioCLIP in Mothbot Process, is never run, and Mothbot Classify only displays what's in the package), each with the full taxon and its GBIF backbone key, the species list it belongs to, and when the model ran. The regional model's answer (the order model's, for non-moths) is the one shown first; the expert can switch between models, and their own answers always win |
| **Dates in Mothbot** | every time is written as strict ISO 8601 (`2026-06-12T23:00:55`) and every night as `YYYY-MM-DD`, and the package check fails otherwise. Mothbot reads any other layout with the browser's date parser, which takes `06/12/2026` as 12 June (US order) and shifts times by the laptop's time zone. `--clock-timezone UTC` (LepiSense units keep UTC) adds the zone to each time without shifting it |
| **Times** | from the results (any layout: text, timestamps, time zones, numbers), else the photo's file name, else its EXIF. The results win when both are known, because they hold clock corrections (dep000145 had a camera set to 2023; dep000142 was 10 h out). Sampling says how many times were corrected or missing |
| **Photos** | JPEG, PNG, TIFF, WebP and BMP (HEIC with `pip install pillow-heif`); 16-bit and transparent photos are converted. Files that can't be trap photos (Windows Recycle Bin copies, `$R...jpg`, and broken rows) are left out at sampling, with a note. Photos whose file ends early (an SD-card error) are read as far as they go, as the images pipeline does (`photo_repaired` in its results) |
| **Clusters** | similar crops are grouped ([DINOv2](https://github.com/facebookresearch/dinov2) embeddings and HDBSCAN), so an expert can label a cluster at once. `--cluster-method leaf` (default) gives many small, tight clusters; `eom` fewer, larger ones; `--no-cluster` skips it. DINOv2 is downloaded once into your model cache, so run one `prepare` on a machine with internet before using compute nodes without it |
| **Screens** | crops that look like a reference set (geckos, leaves, snails...) are left out and **replaced from the reserve**, so targets are still met: sample with `--reserve N`, then `prepare --screen gecko.npz` (or list screens in the `validation.screens` setting). Make a screen from a folder of example crops: `cehbio validate reference crops/geckos --name gecko --out gecko.npz` (threshold: the distance that takes in 95% of the examples, unless you give `--threshold`) |
| **Checked** | every package is checked before zipping: every crop present, records consistent, boxes inside their photos, every machine ID named, the species list readable. `cehbio validate check <folders>` checks any package |
| **Resumable** | run the same command again after a stop: finished packages are skipped |

Older image results (the INSPIRE / AMBER outputs, with names like `top_species_prediction`) work too, and crop ids match the earlier labelling pipeline's, so crops chosen in earlier Mothbot rounds can be excluded. `--min-crop-area` and `--max-crop-area` leave out crops by size; `--for all` packages every crop.

### Keeping up with Mothbot

Packages follow [Mothbot Classify](https://github.com/Digital-Naturalism-Laboratories/mothbot-classify) (the labelling site) and [Mothbot Process](https://github.com/Digital-Naturalism-Laboratories/Mothbot_Process)'s machine-ID fields as they were when the format was last checked (`MOTHBOT` in `platforms/mothbot.py`; `cehbio versions` shows it). `cehbio update` asks GitHub for the newest of both and says when either has changed, so the format can be checked against the new version (their `docs/mothbox-next-package.md` and `src/features/mothbox-next/records.ts`), and the dates in `MOTHBOT` moved on.

## Reading the answers back

```bash
cehbio validate collect sel/sg_sites.csv returned/*.zip --out answers/sg_sites.csv      # Mothbot packages sent back
cehbio validate collect sel/wood-1.csv to_expert/wood-1/validation_sheet.csv --out answers/wood-1.csv
```

One row per answer: the model's species and score, the expert's label (latest answer per expert) with its GBIF key and the species list they used, and `agrees` (both name the same species), ready for accuracy and thresholds.

## Adding a platform

A platform is one module in `src/ceh_biomonitoring/validation/platforms/` with `GROUPS` (what it takes) and `prepare(selection, out, ...)`, plus a line in `PLATFORMS`. The sampling doesn't change.

```
src/ceh_biomonitoring/validation/
    units.py      results -> units (events, passes, tracks)
    sampling.py   the rules: site-lists, model, all
    media.py      finding recordings and photos: disk, or the object store
    platforms/    audio_clips.py  mothbot.py
    embeddings.py DINOv2: clusters and screens
    gbif.py       species lists on the GBIF backbone (cached)
src/ceh_biomonitoring/times.py   dates and times in any layout, from results, file names and EXIF
    collect.py    reading answers back
```
