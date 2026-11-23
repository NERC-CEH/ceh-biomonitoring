# Videos and soundscapes

Short videos to share what a trap or recorder found: for talks, websites, social media, or a partner who'd like to see their site. Made from your results, on your own computer.

```bash
./install.sh videos            # once (Windows: install-windows.bat, then type videos; R: cehbio_install("videos"))
```

## A night at the light trap

```bash
cehbio video --project farm1 --deployment trap-1                                 # the busiest night
cehbio video --project farm1 --deployment trap-1 --night 2026-05-11 --individuals 5
```
```r
cehbio_video("farm1", "trap-1")
cehbio_video("farm1", "trap-1", night = "2026-05-11", individuals = 5)
```

- **The night:** every photo in order, a few a second. Each insect has a box. Moths are named with the model's score, other insects by their order, and each tracked insect leaves a trail showing where it has been.
- **`--individuals 5`:** the five insects seen on most photos, each followed close up from photo to photo. `--track Track_000123` follows particular ones.

Nights are named by the evening they start. Without `--night`, it makes the busiest night (most insects); `--all-nights` makes one per night.

| Option | |
|---|---|
| `--fps 4` | photos per second |
| `--width 1280` | video width in pixels |
| `--trail 8` | how many photos of trail behind each insect (0 for none) |
| `--min-score 0.5` | name moths only at or above this score (others just say "moth") |
| `--labels none` | boxes without names |

## A day of birds, a night of bats

```bash
cehbio soundscape birds --project my-woods --deployment wood-1                   # the day with most species
cehbio soundscape bats --project my-woods --deployment wood-1 --night 2026-05-11
cehbio soundscape birds --project my-woods --deployment wood-1 --recording 20260511_050000.WAV
```
```r
cehbio_soundscape("birds", "my-woods", "wood-1")
```

- **Highlights:** the best moment for each species the model found (up to 12, `--highlights`), in time order. Each is a short clip with its sound and a spectrogram (time across, pitch up, louder is brighter), with a line moving across as it plays and each detection boxed and named with its score.
- **Bats are slowed down ten times**, so you can hear them: a 45 kHz call becomes 4.5 kHz. One second of recording becomes ten seconds of video.
- **The day at a glance (birds):** a picture of the whole day's sound, low to high pitch, with a dot for each detection, by species. `--overview` adds one for bats, `--no-overview` leaves it out.
- **`--recording`:** one whole recording (up to 5 minutes, `--max-seconds`) with everything found in it.

## Where they go, and where the photos and recordings come from

In the deployment's results folder, under `videos/`. Use `--out` to choose another folder.

The photos and recordings are found the same way as for [expert checks](validation.md):
1. in the folder the pipeline read, if it's on this computer;
2. in `--source-root`: one or more folders with copies, e.g. a hard drive;
3. in the object store: `--bucket`, or the bucket in the results.

Any that can't be found are skipped, and it says how many.

## Before you share one

Every frame says the names are **suggestions from computer models, not checked by an expert**. Keep that line in. If the names matter, have an expert check them first ([Manual validation](validation.md)). The models' licences (see the [README](../README.md#models-licences-and-acknowledgements)) apply to their results in videos too. BirdNET, BatDetect2 and the moth species models are for non-commercial use only. Photos and recordings of private land may need the landowner's permission to share.
