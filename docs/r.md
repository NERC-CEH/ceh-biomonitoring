# Using the toolkit from R

Everything can be done from R: installing, running the pipelines, following them, reading the results and making reports. The models run in the toolkit's Python environment, which the R package sets up and drives, so you never write Python. **Reports need no Python at all**: the R package makes the report tables and the reports itself. The results folder, the numbers and the reports are the same as the Python route's.

## Install (once)

You need R 4.1 or newer, and nothing else: no Miniforge, conda, Quarto or admin rights. `cehbio_install()` fetches them for you.

```r
install.packages("remotes")
remotes::install_github("NERC-CEH/ceh-biomonitoring", subdir = "r")
library(cehbio)
cehbio_install("bats")      # the pipelines you want: "birds", "bats", "images", "validation", or "all"
```

What it does, once:

- for the pipelines (the models): gets [uv](https://docs.astral.sh/uv), a small program that fetches Python 3.11, and installs the pipelines you chose into the toolkit's own Python environment;
- gets the R packages reports use (quarto, knitr, ggplot2) and Quarto itself, for Word and PDF;
- makes the `cehbio` command, so the same install works from a terminal too.

It all goes in one folder, `cehbio_home()` (`%LOCALAPPDATA%/ceh-biomonitoring` on Windows, `~/.local/share/ceh-biomonitoring` elsewhere), never in your results. Run `cehbio_install()` again with other pipelines to add them. `cehbio_install("reports")` sets up reports only, with **no Python**: e.g. for making reports on results someone else ran, or where your organisation doesn't allow Python.

> If your organisation blocks programs in your user folder, `cehbio_install()` says so; ask IT to allow `uv.exe` and Python in that folder.

## Upload data to UKCEH

Uploading needs only the R package: no Python and no `cehbio_install()`.

```r
cehbio_deployments()                    # your deployments, and whether each is active
cehbio_request_deployment()             # ask for a new one: it asks step by step
cehbio_upload()                         # upload: it asks step by step (sign in, deployment, data type, folder)
```

The questions, the checks and the upload log are the same as the [Upload guide](upload-guide.md)'s, so an upload started in R can be finished with the `cehbio upload` command, and the other way round: files already sent are skipped. Give the answers as arguments to skip the questions, e.g. `cehbio_upload(folder = "E:/", country = "United Kingdom", deployment = "Wytham Woods 1", data_type = "snapshot_images", name = "Your Name")`. Your password is asked for and stays hidden (or set the `CEHBIO_UPLOAD_USER` and `CEHBIO_UPLOAD_PASSWORD` environment variables).

## Run, follow, read

```r
cehbio_check()                                        # results folder, settings, what's installed

cehbio_run("bats", folder = "E:/cards/wood-1", project = "my-woods", deployment = "wood-1", max_files = 20)
cehbio_run("images", folder = "E:/trap", project = "farm1", deployment = "trap-north",
           device = "lepisense", set = list(region = "uk"))

cehbio_status()                                       # every run, and how far it has got
cehbio_status("bats", project = "my-woods", deployment = "wood-1", watch = 60)

det <- read_results("bats", project = "my-woods", deployment = "wood-1")       # every detection
files <- read_results("bats", "my-woods", "wood-1", what = "files")             # every file and its status
```

Any other command works through `cehbio()`. For example, `cehbio("validate", "prepare", "--project", "farm1")` is the same as typing `cehbio validate prepare --project farm1`.

## Reports

```r
cehbio_report_data("images", "farm1", sites = "sites.csv")    # the tables, with weather and the moon
d <- read_report_data("images", "farm1")                       # deployments, nights, individuals, species
plot_activity(d, "dep000123")                                    # the report's charts, as ggplot2
cehbio_report("images", "farm1")                               # one HTML report per deployment, and the project
```

`cehbio_report_data()` makes the tables in R, by the same rules as Python's `cehbio report-data` (an automatic check makes sure the two give identical tables). `cehbio_report()` writes to the same folder as the Python report (`<results>/<pipeline>/<project>/report/`), with the same words, so the two reports say the same thing. See [Reporting](reporting.md) for what's in the tables and the sites file.

With [EntoInsights](https://github.com/AMI-system/EntoInsights):

```r
w <- EntoInsights::wrangle_results(file.path(d$folder, "entoinsights", "dep000123_combined_results.csv"), taxa = "moth")
```

## Videos and soundscapes

Made in R, with no Python (`cehbio_install("videos")` once, for the magick and av packages):

```r
cehbio_video("farm1", "trap-1", individuals = 5)          # the busiest night, and 5 insects close up
cehbio_soundscape("birds", "my-woods", "wood-1")          # each species' best moment, with sound
cehbio_soundscape("bats", "my-woods", "wood-1", day = "2026-05-11")
```

The same videos as `cehbio video` and `cehbio soundscape`: see [Videos and soundscapes](videos.md). If the photos or recordings aren't where the pipeline read them, give `source_root = "E:/copies"`. (Fetching them from the object store needs the Python toolkit.)

## Which Python is used

`cehbio_python()` shows it. It's the environment `cehbio_install()` made (or, if you installed the old way, the `ceh-biomonitoring` conda environment) unless you choose another with `options(cehbio.python = "path/to/python")` or the `CEHBIO_PYTHON` environment variable. `options(cehbio.results = "...")` points R at a different results folder.
