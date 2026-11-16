# Images: moths and other insects in light-trap photos

Finds insects in photos from automated light traps, such as **AMI traps** and **LepiSense / AMI-mini** units. It says whether each one is a moth, which insect order it belongs to and, for moths, suggests the species. It then follows the same insect from photo to photo through the night, so one moth sitting on the screen for an hour is counted once, not thirty times.

> ⚠️ **These models are still in development and far from perfect.** Treat every result as a suggestion. Detection misses some insects and picks up some things that aren't insects, and species suggestions are often wrong, especially for small, worn or unusual moths, and for species the model has seen few photos of. **Have identifications checked by an expert before relying on them.**

## What it does to each photo

1. **Finds insects** with the [flat-bug](https://github.com/darsa-group/flat-bug) detector. Boxes scoring below `box_threshold` are left out.
2. **Leaves out known clutter**, using your [mask](#masks-ring-lights-and-other-things-always-in-view) (e.g. a ring light) and your [own filters](#your-own-filters-eg-geckos).
3. **Keeps the best boxes**, at most `max_crops_per_image` (default 100) per photo, by detector score. Photos with more, e.g. during a beetle emergence, record how many were left out.
4. **Moth or not:** `moth-vs-nonmoth-v1`.
5. **Order:** `insect-order-v1`, 16 groups, e.g. *Lepidoptera Macros*, *Coleoptera*, *Diptera Tipulidae*, *Vegetation*.
6. **Species:** your region's species model, for moths and Lepidoptera only. It gives the top 5 guesses with scores.
7. **Tracking:** each insect's best match in the previous photo, joined into tracks when the results are combined.

Photos are processed **one night at a time, in time order**. Photos taken before noon count as the previous night.

## Install

```bash
./install.sh images
```

It needs PyTorch. A GPU makes it much faster (on JASMIN it runs on the GPU nodes automatically), but it also works on a laptop for small tests. The models (up to about 700 MB for one region) download the first time they're used and are checked against their published checksums.

## Run

```bash
cehbio models                               # the models, and which regions have species models
cehbio run images --folder E:/trap_photos --deployment farm1-2026 --device lepisense --set region=uk --max-files 50
```

- `--set region=...`: which species model to use, e.g. `uk`, `thailand`, `costa-rica`, `japan`. Run `cehbio models` for the full list. Without a region you still get detection, moth/non-moth and order.
- `--device`: `ami-trap` or `lepisense`, so photos get their date and time. See [Recorders and file names](recorders.md).
- Start with `--max-files 50` to check everything works, and to make a mask (below).

### Settings

| Setting | Default | Meaning |
|---|---|---|
| `region` | (none) | species model for this region (`cehbio models`) |
| `species_model` | | or name a species model exactly |
| `box_threshold` | `0.2` | detector score below this: not an insect |
| `max_crops_per_image` | `100` | keep at most this many boxes per photo, the highest-scoring |
| `top_n` | `5` | species guesses per insect |
| `mask` | | mask image of areas to ignore (see below) |
| `mask_overlap` | `0.5` | ignore a box when at least this much of it is in the masked area |
| `filters` | | your filter file(s) (see below) |
| `save_crops` | `false` | also save every crop as a `.jpg` |
| `track_cost_threshold` | `1.0` | how similar two crops must be to join a track (lower = stricter) |
| `device` | `auto` | `cuda` (GPU), `cpu` or `auto` |
| `deployment_name`, `lat`, `lon` | | written into every row, if you give them |

## Masks: ring lights and other things always in view

LepiSense and AMI-mini units have a ring light in the photo, and the detector often mistakes it for insects in every single photo. A **mask** tells the pipeline to ignore those areas. It's a black-and-white image the same shape as your photos: **black = ignore, white = keep**.

The ring light sits in a slightly different place in each deployment, so **make one mask per deployment**. The easiest way:

```bash
# 1. a short test run without a mask
cehbio run images --folder E:/trap_photos --deployment farm1-test --device lepisense --max-files 300

# 2. let it find the places detected in photo after photo
cehbio mask suggest --detections ~/ceh-biomonitoring/outputs/images/local/inference/farm1-test/farm1-test_detections.parquet \
                    --image E:/trap_photos/one_photo.jpg --out masks/farm1.png
```

This writes `masks/farm1.png`, plus `masks/farm1_preview.jpg` showing the ignored area in red over your photo. **Always look at the preview.** If it covers too much or too little, change `--min-fraction`: the default 0.2 means "detected in at least 20% of photos".

Or draw it yourself by clicking round each area. This needs a screen, so it won't work on JASMIN:

```bash
cehbio mask draw --image E:/trap_photos/one_photo.jpg --out masks/farm1.png
```

Then use it:

```bash
cehbio run images --folder E:/trap_photos --deployment farm1-2026 --device lepisense --set region=uk --set mask=masks/farm1.png
```

Every photo records how many boxes the mask removed (`n_boxes_masked`).

## Your own filters, e.g. geckos

Some things the models were never trained on turn up again and again: geckos hunting on the screen, snails, leaves. Write rules for them in a YAML file and use it with `--set filters=my_filters.yml`:

```yaml
filters:
  - name: gecko
    stage: detection        # when to check: detection | order | species
    action: flag            # flag (keep, but name the rule in the 'filters' column) | remove
    when:                   # all conditions must be true
      relative_area_min: 0.02     # at least 2% of the photo
      aspect_min: 2.5             # long and thin

  - name: snail
    stage: order
    action: flag
    when:
      relative_area_min: 0.005
      aspect_max: 1.3             # round
      order_name: [Coleoptera, Vegetation]

  - name: leaf
    stage: order
    action: remove
    when:
      order_name: [Vegetation]
      order_confidence_max: 1.0
```

| Condition | Meaning | Stages |
|---|---|---|
| `relative_area_min` / `relative_area_max` | box area as a fraction of the photo | all |
| `aspect_min` / `aspect_max` | long side ÷ short side of the box | all |
| `zone: [x0, y0, x1, y1]` | box centre inside this part of the photo (0 to 1, from the top left) | all |
| `box_score_max` | detector score at or below this | all |
| `filename_matches` | file name matches a [regular expression](https://docs.python.org/3/howto/regex.html), e.g. `"^ami-mini-"` | all |
| `class_name` | `moth` or `nonmoth` | order, species |
| `order_name` | one of these orders | order, species |
| `order_confidence_max` | order score at or below this | order, species |
| `species` | top species is one of these | species |
| `species_confidence_max` | top species score at or below this | species |

**Start with `action: flag`.** Check what a rule catches before switching to `remove`. Removed boxes can't be got back without re-running, though every photo records how many were removed (`n_boxes_removed_by_filters`). Rules checked at `stage: detection` save time, because removed boxes are never classified.

## Results

In `outputs/images/<place>/inference/<deployment>/`:

| File | What's in it |
|---|---|
| `<deployment>_analysis_ready.parquet` | **start here**: one row per insect crop, plus one row per photo with nothing found, with its `track_id` |
| `<deployment>_tracks.parquet` | one row per track: start and end time, number of photos, and the first crop's classification |
| `<deployment>_detections.parquet` | the same crops before tracking |
| `<deployment>_files.csv` | every photo and its status, including photos that couldn't be read |
| `chunks/*_summary.json` | the exact models (with checksums), settings and package versions used |

The main columns:

| Column | Meaning |
|---|---|
| `image_path`, `image_datetime`, `recording_session` | the photo, when it was taken, and which night |
| `crop_status` | `crop_1`, `crop_2`, ... (the detector's numbering) or *No detections for this image.* |
| `x_min`, `y_min`, `x_max`, `y_max`, `box_score` | where the insect is, and how sure the detector is |
| `class_name`, `class_confidence` | moth or nonmoth |
| `order_name`, `order_confidence` | insect order |
| `regional_species_rank_1_name` ... `_5_name`, `..._confidence` | species guesses, best first |
| `track_id`, `tracking_decision` | which track the crop belongs to, and why |
| `previous_image`, `best_match_crop`, `total_cost` | its best match in the previous photo |
| `filters` | names of the filters it matched (flagged) |
| `n_boxes_detected`, `n_boxes_masked`, `n_boxes_removed_by_filters`, `n_boxes_over_cap` | what happened to the photo's boxes |
| `image_bluriness`, `crop_bluriness` | sharpness: low values are blurry |

**Counting insects:** count **tracks**, not crops. Many tracks are a single photo (`is_single_image_track`). Tracking is simple, so one insect that moves a lot may appear as several tracks, and two similar moths side by side may occasionally be joined.

## Models and credits

| Step | Model | By | Licence |
|---|---|---|---|
| Finding insects | flat-bug M | Svenning, Geissmann et al. ([flat-bug](https://github.com/darsa-group/flat-bug)) | MIT |
| Moth or not | moth-vs-nonmoth-v1 | Mila / Rolnick lab, AMI project ([ami-data-companion](https://github.com/RolnickLab/ami-data-companion)) | see source |
| Order | insect-order-v1 | Aarhus University, Bjerge et al. 2025 ([MCC24-trap](https://github.com/kimbjerge/MCC24-trap)), via AMBER | to be confirmed |
| Species | moth-species-*region*-v*N* | The Alan Turing Institute, for the AMBER project | open access, licence to be confirmed |

The pipeline's processing follows [amber-inferences](https://github.com/AMI-system/amber-inferences) (MIT), so results match earlier UKCEH outputs. If you publish results, please cite the models you used. Their details and checksums are recorded in each chunk's `_summary.json`.
