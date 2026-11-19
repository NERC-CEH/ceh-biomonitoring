# Running and results

How `cehbio run` works on a laptop or a computing cluster, how to follow a run, and where everything goes. It works the same way for every pipeline.

## Running

```bash
cehbio run <pipeline> --folder <your data> --project <project> --deployment <deployment>
```

- `--folder` is where the recordings or photos are, e.g. an SD card or a folder. Folders inside it are included too. **Your original files are never moved, changed or deleted.**
- `--project` names the folder your results go in, e.g. `my-woods-2026`. Use the same project for every deployment that belongs together. Without it, results go in a folder named after the bucket or country, or `local` for files on disk.
- `--deployment` is a short name for one recorder or trap at one place over one period, e.g. `wood-1` or `farm3-2026`. Each deployment gets its own folder.
- `--device` is the recorder or trap you used, so that results get their dates and times. See [Recorders](recorders.md).
- `--max-files 20` runs on the first 20 files only. Use it to try things out first.

The files are split into **parts** (also called chunks) of about 100 files each.

- **On a laptop,** the parts run one after another. A line after each part says how far the run has got and how long is left.
- **On a cluster with Slurm,** such as JASMIN, `cehbio run` sends the parts to the cluster, up to 25 at a time. When the last part finishes, a small extra job joins the results together, so you don't have to remember to.
- `--here` runs on the machine you're on, even if a cluster is available.
- `--dry-run` shows the job script without sending it.

**If a run stops, run the same command again.** Finished parts are kept and skipped.

## Checking on a run

```bash
cehbio status                                                # every run, and how far it has got
cehbio status bats --project my-woods --deployment wood-1    # one run in detail
cehbio status --watch                                        # keep checking until nothing is running
```

Example output:

```
Runs in /home/you/ceh-biomonitoring-results

  bats / my-woods / wood-1      [########################] 100%  finished
  images / farm1 / trap-north   [##########--------------]  42%  running · 10 of 24 parts · about 35 min left
```

One run in detail shows:

- how many files are done, and how many detections so far;
- how many parts are waiting their turn on the cluster;
- how long the run has been going, and roughly how long is left;
- any problems, in plain words, with where the job logs are. For example: "dep1_chunk_00007: ran out of memory".
- what to do next.

You don't need a command to check, either. Each deployment folder has a `PROGRESS.txt` that is updated as the run goes, which you can open in any text editor.

`cehbio status` also lists labelling jobs sent to the cluster (`cehbio validate ... --slurm`) from the last two weeks.

**Joining the results by hand.** `cehbio combine <pipeline> --project <project> --deployment <deployment>` joins the parts into the results files. You only need it after `--no-auto-combine`, or to join a run that is only partly finished.

## Your results folder

Everything goes in one results folder. By default this is `ceh-biomonitoring-results` in your user folder, kept apart from the folder the code is in. `cehbio check` shows where yours is. The folder looks like this:

```
ceh-biomonitoring-results/
    READ ME.txt                    what each folder is
    birds/  bats/  images/         one folder per pipeline
        my-woods/                  one folder per project (--project)
            wood-1/                one folder per deployment (--deployment)
                READ ME.txt        what each file is
                PROGRESS.txt       how far the run has got
                wood-1_detections.csv        the results: open in Excel
                wood-1_detections.parquet    the same results, smaller and faster
                wood-1_files.csv             every file, and whether it worked
                wood-1_qa.json               checks: did every part finish?
                working/           the pipeline's own files: you don't need to open these
    labelling/                     expert checks (cehbio validate), see below
        images/  birds/  bats/
            my-woods/
                1_sample/  2_for_experts/  3_answers/
    examples/                      the example data (cehbio examples)
    upload_logs/                   records of uploads to UKCEH (cehbio upload)
```

| File | What's in it |
|---|---|
| `<deployment>_detections.csv` | every detection, one row each, with the columns described in each pipeline's guide. Not written for runs with more than a million rows: use the parquet file then |
| `<deployment>_detections.parquet` | the same, much smaller and faster to read. In R: `arrow::read_parquet("file.parquet")`. In Python: `pandas.read_parquet("file.parquet")` |
| `<deployment>_files.csv` | every file, with its status: detections, no detections, or failed. A failed file is never mistaken for an empty one |
| `<deployment>_qa.json` | whether every part finished, and how many files failed |
| `working/chunks/*_summary.json` | for each part, the **exact model and package versions** used, and the settings |
| `working/jobs/logs/` | the cluster's log for each part, the place to look if something went wrong |

The images pipeline adds its own result files (`_analysis_ready.parquet`, `_tracks.parquet`); see [Images](images.md#results).

**Reproducibility:** installing or updating always gets the newest model releases. The `_summary.json` records keep a note of exactly which versions and settings made each result.

**Labelling** has its own folders. Give the three `cehbio validate` steps the same `--project`, and each step finds the files from the step before. See [Manual validation](validation.md#the-easy-way-one-project-folder).

### Choosing where results go

To use another folder, create `~/.config/ceh-biomonitoring/settings.yml`:

```yaml
outputs_root: /path/with/plenty/of/space/ceh-biomonitoring-results
slurm:                              # on JASMIN or another cluster
  account: <your Slurm account>
```

On JASMIN, put `outputs_root` in your group workspace. The default there, scratch, is cleared after a while. `cehbio check` shows your settings and warns about anything missing.

### Results from before November 2026

Results used to be kept in `~/ceh-biomonitoring/outputs`, in folders such as `bats/local/inference/wood-1/`, with the file lists in a separate `keys/` folder. The toolkit still finds those runs where they are. `cehbio status` marks them "(old layout)".

`cehbio tidy` moves them into the new layout, and also moves the old default folder out of the code folder. It lists every move first, and only moves anything after you say yes. Nothing is deleted. Your own scripts that point at the old folders will need the new paths.

## Settings

Each pipeline has sensible defaults. You can change them with `--set name=value`, or keep them in a file and use `--config my_settings.yml`. If you give a setting in more than one place, the later one wins:

1. the pipeline's defaults
2. the recorder's settings (`--device`)
3. your settings file (`--config`)
4. `--set` on the command line

`cehbio run <pipeline> --help` lists every option.

## Data in an object store (optional)

If your data is in an S3-compatible object store, such as JASMIN's, you can process it without downloading it yourself. Use `--bucket <bucket>` instead of `--folder`. The toolkit expects the files under `<deployment>/<data type>/` in the bucket.

Save your key in `~/.config/ceh-biomonitoring/credentials.json`:

```bash
mkdir -p ~/.config/ceh-biomonitoring
cp credentials/credentials.example.json ~/.config/ceh-biomonitoring/credentials.json
nano ~/.config/ceh-biomonitoring/credentials.json      # paste your key and secret
chmod 600 ~/.config/ceh-biomonitoring/credentials.json # only you can read it
cehbio check --bucket <bucket>
```

If you also upload data to UKCEH, you can add the upload login to the same file as `UKCEH_username` and `UKCEH_password`. `cehbio upload` then won't ask for it.

Never put this file in a repository, share it, or paste it into an email or chat.
