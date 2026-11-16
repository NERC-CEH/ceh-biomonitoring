# Running and results

How `cehbio run` works, on a laptop or a computing cluster, and what you get. The same applies to every pipeline.

## Running

```bash
cehbio run <pipeline> --folder <your data> --deployment <a name for this deployment>
```

- `--folder`: where the recordings or images are, e.g. an SD card or a folder. Folders inside it are included. **Your original files are never moved, changed or deleted.**
- `--deployment`: a short name for one recorder or trap at one place over one period, e.g. `wood-1` or `farm3-2026`. Results are kept separately for each deployment.
- `--device`: the recorder you used, so results get dates and times. See [Recorders](recorders.md).
- `--max-files 20`: try 20 files first.

The work is split into **chunks** of files. On a laptop, the chunks run one after another. On a cluster with Slurm, such as JASMIN, `cehbio run` sends them out as a Slurm array job, one task per chunk. Add `--dry-run` to see the job script without submitting it, or `--here` to run on the machine you're on.

**If a run is interrupted, run the same command again.** Finished chunks are skipped.

```bash
cehbio status bats --deployment wood-1    # how far has it got?
cehbio combine bats --deployment wood-1   # join the chunks into one results file
```

`cehbio run` combines the chunks itself when it runs them on your machine. On a cluster, run `cehbio combine` once all the jobs have finished. For data from a bucket, add the same `--bucket` you used to run it.

## Settings

Each pipeline has sensible defaults. Change them with `--set name=value`, or keep them in a file and use `--config my_settings.yml`. If you give a setting in more than one place, the later one wins:

1. the pipeline's defaults
2. the recorder's settings (`--device`)
3. your settings file (`--config`)
4. `--set` on the command line

`cehbio run <pipeline> --help` lists every option.

## What you get

Results go in `~/ceh-biomonitoring/outputs/<pipeline>/<place>/inference/<deployment>/`:

| File | What's in it |
|---|---|
| `<deployment>_detections.parquet` | every detection, with the columns described in each pipeline's guide |
| `<deployment>_files.csv` | every file, with its status: detections, no detections, or failed. A failed file is never mistaken for an empty one |
| `<deployment>_qa.json` | whether every chunk finished, and how many files failed |
| `chunks/*_summary.json` | for each chunk, the **exact model and package versions** used and the settings |

**Parquet** files are much smaller and faster than CSV. Open them in R with `arrow::read_parquet("file.parquet")` or in Python with `pandas.read_parquet("file.parquet")`. To get a CSV: `arrow::write_csv_arrow(arrow::read_parquet("file.parquet"), "file.csv")` in R.

**Reproducibility:** installing or updating always gets the newest model releases. The `_summary.json` records keep a note of exactly which versions and settings made each result.

## Where results go

To change it, create `~/.config/ceh-biomonitoring/settings.yml`:

```yaml
outputs_root: /path/with/plenty/of/space/ceh-biomonitoring
slurm:                              # on JASMIN or another cluster
  account: <your Slurm account>
```

On JASMIN, put `outputs_root` in your group workspace: the default, scratch, is cleared after a while. `cehbio check` shows your settings and warns about anything missing.

## Data in an object store (optional)

If your data is in an S3-compatible object store, such as JASMIN's, you can process it without downloading it yourself. Use `--bucket <bucket>` instead of `--folder`. The files are expected under `<deployment>/<data type>/` in the bucket.

Save your key in `~/.config/ceh-biomonitoring/credentials.json`:

```bash
mkdir -p ~/.config/ceh-biomonitoring
cp credentials/credentials.example.json ~/.config/ceh-biomonitoring/credentials.json
nano ~/.config/ceh-biomonitoring/credentials.json      # paste your key and secret
chmod 600 ~/.config/ceh-biomonitoring/credentials.json # only you can read it
cehbio check --bucket <bucket>
```

If you also upload data to UKCEH, you can add the upload login to the same file as `UKCEH_username` and `UKCEH_password`, and `cehbio upload` won't ask for it.

Never put this file in a repository, share it, or paste it into an email or chat.
