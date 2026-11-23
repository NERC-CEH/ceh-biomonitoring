# Running the toolkit from R. Every function here calls the same `cehbio` commands as the Python route,
# so results, folders and reports are identical whichever language you use.

#' The Python that runs the toolkit
#'
#' Looks, in order, at `options(cehbio.python = ...)`, the `CEHBIO_PYTHON` environment variable, the
#' toolkit's own environment (made by `cehbio_install()`), and a `ceh-biomonitoring` conda environment.
#' @return the path to python, or NULL if the toolkit isn't installed yet
#' @export
cehbio_python <- function() {
  given <- c(getOption("cehbio.python", ""), Sys.getenv("CEHBIO_PYTHON"))
  given <- given[nzchar(given)]
  if (length(given) && file.exists(given[1])) return(normalizePath(given[1], winslash = "/"))
  own <- file.path(cehbio_home(), "env", if (.Platform$OS.type == "windows") "Scripts/python.exe" else "bin/python")
  if (file.exists(own)) return(normalizePath(own, winslash = "/"))
  home <- path.expand("~")
  if (.Platform$OS.type == "windows") home <- Sys.getenv("USERPROFILE", home)
  bases <- c(file.path(home, c("miniforge3", "miniconda3", "anaconda3", "mambaforge")),
             file.path(Sys.getenv("LOCALAPPDATA"), c("miniforge3", "miniconda3")),
             "C:/ProgramData/miniforge3", "/opt/conda")
  exe <- if (.Platform$OS.type == "windows") "python.exe" else file.path("bin", "python")
  cand <- file.path(bases, "envs", "ceh-biomonitoring", exe)
  hit <- cand[file.exists(cand)]
  if (length(hit)) normalizePath(hit[1], winslash = "/") else NULL
}

.conda <- function() {
  home <- if (.Platform$OS.type == "windows") Sys.getenv("USERPROFILE") else path.expand("~")
  exe <- if (.Platform$OS.type == "windows") c("condabin/conda.bat", "Scripts/conda.exe") else "bin/conda"
  cand <- c(Sys.which("conda"), Sys.which("mamba"),
            as.vector(outer(file.path(home, c("miniforge3", "miniconda3", "mambaforge")), exe, file.path)),
            file.path(Sys.getenv("LOCALAPPDATA"), "miniforge3", exe))
  cand <- cand[nzchar(cand) & file.exists(cand)]
  if (length(cand)) cand[1] else NULL
}

#' Run any cehbio command
#'
#' `cehbio("status")` is the same as typing `cehbio status` in a terminal. Output is shown as it runs.
#' @param ... the command and its options, e.g. `cehbio("run", "bats", "--folder", "E:/card")`
#' @param echo show the output as it runs (default TRUE)
#' @return invisibly, the exit status (0 = it worked)
#' @export
cehbio <- function(..., echo = TRUE) {
  py <- cehbio_python()
  if (is.null(py)) stop("The toolkit isn't installed yet. Run cehbio_install() first, e.g. cehbio_install(\"bats\").", call. = FALSE)
  args <- c("-m", "ceh_biomonitoring", unlist(list(...)))
  args <- vapply(args, shQuote, "", type = if (.Platform$OS.type == "windows") "cmd" else "sh")
  res <- getOption("cehbio.results", "")
  if (nzchar(res)) {                                   # the same results folder for the Python side
    old <- Sys.getenv("CEHBIO_RESULTS", NA)
    Sys.setenv(CEHBIO_RESULTS = normalizePath(res, winslash = "/", mustWork = FALSE))
    on.exit(if (is.na(old)) Sys.unsetenv("CEHBIO_RESULTS") else Sys.setenv(CEHBIO_RESULTS = old), add = TRUE)
  }
  if (!echo) return(invisible(suppressWarnings(system2(py, args, stdout = TRUE, stderr = TRUE))))
  code <- system2(py, args)
  if (!identical(as.integer(code), 0L)) warning("cehbio stopped with an error (see above).", call. = FALSE)
  invisible(code)
}

`%||%` <- function(a, b) if (is.null(a)) b else a

.opt <- function(name, value) {
  if (is.null(value) || identical(value, FALSE)) return(character())
  if (isTRUE(value)) return(paste0("--", name))
  c(paste0("--", name), as.character(value))
}

#' Check settings, results folder and what's installed
#' @export
cehbio_check <- function() cehbio("check")

#' Run a pipeline on a deployment
#'
#' @param pipeline "birds", "bats" or "images"
#' @param folder the recordings or photos (never moved or changed)
#' @param project the folder the results go in, e.g. "my-woods"
#' @param deployment a name for this recorder or trap at this place
#' @param device e.g. "audiomoth", "song-meter", "lepisense", "ami-trap"
#' @param bucket an object-store bucket instead of a folder
#' @param set named list of settings, e.g. `list(region = "uk")`
#' @param max_files try this many files first
#' @param ... more options as name = value, e.g. `here = TRUE`, `files_per_chunk = 200`
#' @export
cehbio_run <- function(pipeline, folder = NULL, project = NULL, deployment, device = NULL, bucket = NULL,
                       set = NULL, max_files = NULL, ...) {
  sets <- if (length(set)) as.vector(rbind("--set", paste0(names(set), "=", unlist(set)))) else character()
  more <- list(...)
  extra <- unlist(Map(function(n, v) .opt(gsub("_", "-", n), v), names(more), more))
  cehbio("run", pipeline, .opt("folder", folder), .opt("bucket", bucket), .opt("project", project),
         .opt("deployment", deployment), .opt("device", device), .opt("max-files", max_files), sets, extra)
}

#' How far runs have got
#' @param pipeline,project,deployment narrow it down (all optional)
#' @param watch keep checking every this many seconds until nothing is running
#' @export
cehbio_status <- function(pipeline = NULL, project = NULL, deployment = NULL, watch = NULL) {
  cehbio("status", pipeline, .opt("project", project), .opt("deployment", deployment), .opt("watch", watch))
}

#' Join a run's parts into its results (only needed after no_auto_combine)
#' @inheritParams cehbio_run
#' @export
cehbio_combine <- function(pipeline, project, deployment) {
  cehbio("combine", pipeline, .opt("project", project), .opt("deployment", deployment))
}

#' What time a light trap's clock kept
#' @param folder,bucket,deployment,results where the photos or results are
#' @param lat,lon the site
#' @param timezone e.g. "Europe/London"
#' @param device e.g. "lepisense" (helps read the file names)
#' @export
cehbio_clock_check <- function(lat, lon, timezone = NULL, folder = NULL, results = NULL, bucket = NULL,
                               deployment = NULL, device = NULL) {
  cehbio("clock-check", .opt("lat", lat), .opt("lon", lon), .opt("timezone", timezone), .opt("folder", folder),
         .opt("results", results), .opt("bucket", bucket), .opt("deployment", deployment), .opt("device", device))
}
