# Using the toolkit from R

Everything can be done from R: installing, running the pipelines, following them, reading the results and making reports. The models run in the toolkit's Python environment, which the R package sets up and drives, so you never write Python. The results folder, the numbers and the reports are the same as the Python route's.

## Install (once)

You need [Miniforge](https://conda-forge.org/download/) (conda) and R 4.1 or newer. For reports you also need [Quarto](https://quarto.org).

```r
install.packages("remotes")
remotes::install_github("NERC-CEH/ceh-biomonitoring", subdir = "r")
library(cehbio)
cehbio_install(c("bats", "reports"))     # the pipelines you want: birds, bats, images, validation, reports, or "all"
```

`cehbio_install()` makes a conda environment called `ceh-biomonitoring` and installs the toolkit into it. Run it again with other pipelines to add them.

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

`cehbio_report()` writes to the same folder as the Python report (`<results>/<pipeline>/<project>/report/`). It uses the same tables and the same words, so the two reports say the same thing. See [Reporting](reporting.md) for what's in the tables and the sites file.

With [EntoInsights](https://github.com/AMI-system/EntoInsights):

```r
w <- EntoInsights::wrangle_results(file.path(d$folder, "entoinsights", "dep000123_combined_results.csv"), taxa = "moth")
```

## Which Python is used

`cehbio_python()` shows it. It's the `ceh-biomonitoring` conda environment unless you choose another with `options(cehbio.python = "path/to/python")` or the `CEHBIO_PYTHON` environment variable. `options(cehbio.results = "...")` points R at a different results folder.
