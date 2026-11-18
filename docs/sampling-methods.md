# Sampling methods for expert validation

This page sets out exactly how `cehbio validate sample` chooses what experts check. It is written so it can be cited, or adapted for the methods section of a report or paper. The rules are the same for birds, bats and images. Only the first step, turning results into units, differs between groups.

The code is in `src/ceh_biomonitoring/validation/` (`units.py` for step 1, `sampling.py` for steps 2–4). The commands and options are in [Manual validation](validation.md).

## Summary

The model outputs are first grouped into **units**: independent things an expert can check (a bird's calling event, a bat pass, an insect's track through a series of photos). Units are then sampled in one of three ways:

- **site-lists:** a few units of every species reported at each site, to confirm or reject each species on the site's list
- **model:** many units of every species across all sites of one country, to measure and improve that country's species model
- **all:** every unit

Within each species, picks are spread across the model's confidence range and across the survey period, so experts see a fair picture rather than only the easiest or busiest cases. Picks from earlier rounds are excluded, so no unit is labelled twice.

The models' identifications come from our own models: the regional species model, the global model and the order model in the results. Nothing is identified again by the labelling platform.

## 1. From results to units

### Birds: events

An **event** is a run of detections of one species in one recording.

1. Detections are sorted by recording, species and start time.
2. A new event starts when the gap between the end of the previous detection of that species and the start of the next is more than **60 s** (`--max-gap`). One bird singing with long pauses therefore makes several events.
3. Each event's score is the **highest** detection score in it: BirdNET's `logit` if the results have it, otherwise `confidence`. The *peak* is the detection window with that score.
4. The event's time is the recording's time, read from the results or the file name.

### Bats: passes

A **pass** is built the same way as a bird event, with a gap of **1 s**. The score is `class_probability`, otherwise `detection_probability`. The 1 s gap is a starting point and should be checked against your own recordings.

### Images: tracks

1. **Detections kept:** detections with a valid box (positive width and height), and within `--min-crop-area` and `--max-crop-area` if those are given. Rows whose "photo" can't be a trap photo are dropped and reported: Windows Recycle Bin copies (`$R…`, `$I…`) and names without an image file type.
2. **Moth units:** any detection with a species guess from the regional model (its top-ranked species) can be chosen. Detections the tracker linked across consecutive photos form one **track**, and each track becomes one unit **per species it was identified as**.
   - The track is represented by its crop whose species score is **nearest the median** of that species' scores in the track. This is a typical view of the insect, neither its best nor its worst.
   - A detection without a track is a unit on its own.
3. **Noise units** (site-lists only): detections the moth filter rejected. These are not classed as a moth, not in Lepidoptera, have no species guess, and do have an order. There is one unit per track. They show the expert what the filter removed.
4. **Score:** the regional model's top-species confidence.
5. **Time:** the time in the results, otherwise the time in the photo's file name. When both exist, the results win, because they hold any clock corrections made when they were built. Mothbot packages also fall back to the photo's EXIF.

With `--for all`, every image detection is its own unit: tracks aren't merged.

### Site, period and identity (all groups)

- **Site:** the deployment. For audio results without a deployment id, the results folder.
- **Period:**
  - birds: the calendar **day**
  - bats and images: the **night**, running noon to noon and named by the evening it starts
  - if the results have dates but no times, the period is the date
- **Unit id:** a stable id, so the same unit gets the same id in every run and can be excluded later:
  - audio: built from the recording, the start time and the species
  - images: deployment and track, or the crop's id (the same `det_…` id the earlier labelling pipeline used)

## 2. Choosing within one species

Two rules pick *n* units from one species' units. Both are deterministic: the same inputs always give the same picks.

### Spread (images, by default)

This rule covers **confidence** and **time**:

1. Sort the units by score, low to high.
2. Split them into ***n* bands with equal numbers of units**. These are quantile bands, not equal-width score bands, so each band holds about 1/*n* of the units.
3. Work through the bands from lowest to highest score, and take **one unit from each**. Choose the unit:
   1. **furthest in time** (in days) from the units already picked;
   2. if several are equally far, the one from the **least-used period** (night or day) so far;
   3. if several still tie, the one **nearest the middle of the band**.

   The first band has nothing to be far from, so its pick is the one nearest the band's middle.

The result is one pick per confidence band, with the picks pushed apart in time (different nights, weeks and months where the survey allows). Units without a known time can't be pushed apart in time, so for them the other two tie-breaks decide. A species with *n* or fewer units has all of them taken.

### Best (birds and bats site-lists, by default)

This rule picks the clearest examples, for a quick "is this species there?" check:

1. the highest-scoring unit (`why`: *best*);
2. then the highest-scoring unit on a **day or night not used yet** (*best on another day*);
3. once every period is used, the highest-scoring unit in a **recording or photo not used yet** (*best in another recording*);
4. then the next highest (*next best*).

`--how best` and `--how spread` override the site-lists default for any group.

## 3. The three purposes

### Site-lists: is each species really at each site?

For **each site separately**, and **each species reported there**:

1. **Which species:** every species with at least one unit at the site. With `--species-table`, only the species that table lists for the site. For example, `cehbio bird-results` keeps species with at least 2 events on at least 2 days.
2. **How many:** pick *n* units with the rule above. By default birds and bats use 2 with *best*, and images use 3 with *spread* (`--per-species`, `--how`).
3. **Unusual months:** if any of the species' units at the site fall in a month the species list marks *unlikely* and weren't picked, the highest-scoring one is added (`why`: *outside its usual months*). This happens even when the species table leaves the species out.

   An out-of-season record is a real record if it's right, so it is checked, not removed. `--no-unusual-months` turns this off.
4. **Noise (images):** up to 100 noise units per site (`--noise`).
   - They are shared between insect orders in proportion to how many each order has, using the largest-remainder method.
   - Within an order they are drawn **at random, without replacement**, with a fixed seed (`--seed`, default 42). This is the only random step.

**Experts see:** audio clips come with the model's label, asking "is this right?". Mothbot packages are blind by default.

### Model: how good is the model, and what would improve it?

For **one country at a time**. Each country has its own species model, so countries are never mixed. Countries that share a model, such as Kenya and Uganda, are sampled together. Results from several countries give one selection file per country.

For **every species** the model reported in that country (its mistakes are what it learns from), noise units aside:

1. **How many:** up to *n* units per species: birds and bats 50, images 100 (`--per-species`).
2. **Across sites:**
   - every site with the species gets **one** pick first, busiest sites first;
   - if *n* is smaller than the number of sites, only the busiest *n* sites get one;
   - the rest of the picks are shared between sites **in proportion to their remaining units** (largest remainder).
3. **Within each site:** the *spread* rule chooses that site's share.

No unusual-month extras are added, because every species is already sampled.

**Experts see:** audio is blind, with the model's labels kept in a separate key file that isn't sent. Mothbot packages are blind by default.

### All

Every unit, for example every crop of a deployment.

## 4. Rounds, exclusions and spares

- **No unit labelled twice:** `--exclude` takes earlier selection files, and their unit ids are removed before sampling. Rounds can be added over time (for example site-lists first, then model rounds) without repeats.
- **Spares:** `--reserve N` picks up to *N* more units per species (and site), with the same rule, from the units not already chosen. They are marked `reserve` and aren't packaged unless needed.
- **When spares are used:** a platform may drop a pick, for example a Mothbot screen removing a crop that looks like a gecko. Spares then replace dropped picks **in rank order**, within the same site and species (or the same country model and species for model samples), until the target is met again.

## 5. What a selection records

The selection is a CSV with one row per unit, plus `<name>_record.json`.

**Columns of the CSV:**

| Column | Meaning |
|---|---|
| `selection_id` | B00001…, BAT00001…, I00001… |
| `purpose` | site-lists, model or all |
| `site`, `period` | where and when |
| `species`, `score`, `score_type` | what the model said |
| `rank` | order within the species |
| `why` | the reason for the pick: *species check*, *best*, *best on another day*, *model examples*, *outside its usual months*, *noise (not a moth: Diptera)*, *reserve* … |
| `reserve` | whether it's a spare |
| `country`, `model_group` | model samples |

The rows also carry everything needed to find the unit again (recording and seconds, or photo and box), and all the models' outputs.

**The record file** gives the inputs, every option, the seed, the number of units available, those excluded, and a count of picks by reason. With the same results and record, the selection can be made again exactly.

## 6. Using the answers: what each sample can and can't estimate

- **Site-lists** confirm or reject species at sites. They are designed for *presence*, not for an unbiased error rate. The *best* rule deliberately shows each species' clearest examples, so its agreement rate is an upper bound on precision.
- **Model samples (spread)** are a stratified sample: each species is split into *n* equal-count confidence bands, and one unit is taken per band. Each pick therefore stands for about *N*/*n* of that species' *N* units:
  - **Precision for a species** is the share of its checked units the expert confirms. Each pick carries equal weight within the species.
  - **Precision across species** weights each species by its *N*.
  - **Precision above a score threshold** comes from the picks in the bands above it.

  The pick within a band is systematic (the furthest in time), not random. This spreads picks across the survey, but it means within-band estimates assume that time of capture doesn't bias identification within the band.
- **Noise samples** are random within each order, so the share the expert finds to be moths estimates what the moth filter misses, per order and per site.

`cehbio validate collect` puts each expert answer next to the model's species and score (`agrees`: both name the same species), ready for these calculations.

## 7. Defaults

| | Birds | Bats | Images |
|---|---|---|---|
| Unit | event | pass | track |
| Joining gap | 60 s | 1 s | (tracker) |
| Period | day | night | night |
| Site-lists per species per site | 2, *best* | 2, *best* | 3, *spread* |
| Model per species per country | 50 | 50 | 100 |
| Noise per site (site-lists) | — | — | 100 |
| Score | logit, else confidence | class probability, else detection probability | regional top-species confidence |
