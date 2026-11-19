# Reading results and report tables. Plain CSV, so nothing extra is needed (arrow is used for the
# bigger .parquet files only if it's installed).

#' Your results folder
#'
#' The folder every run writes to: `options(cehbio.results = ...)` if set, else the toolkit's own setting
#' (as `cehbio check` shows), else `~/ceh-biomonitoring-results`.
#' @export
results_folder <- function() {
  given <- getOption("cehbio.results", "")
  if (nzchar(given)) return(normalizePath(given, winslash = "/", mustWork = FALSE))
  py <- cehbio_python()
  if (!is.null(py)) {
    out <- suppressWarnings(system2(py, c("-c", shQuote(
      "from ceh_biomonitoring.settings import Settings; print(Settings.load().outputs_root)")),
      stdout = TRUE, stderr = FALSE))
    if (length(out) && nzchar(out[length(out)])) return(normalizePath(out[length(out)], winslash = "/", mustWork = FALSE))
  }
  home <- if (.Platform$OS.type == "windows") Sys.getenv("USERPROFILE") else path.expand("~")
  file.path(home, "ceh-biomonitoring-results")
}

.read_table <- function(folder, name) {
  pq <- file.path(folder, paste0(name, ".parquet"))
  if (file.exists(pq) && requireNamespace("arrow", quietly = TRUE)) return(as.data.frame(arrow::read_parquet(pq)))
  csv <- file.path(folder, paste0(name, ".csv"))
  if (!file.exists(csv)) return(data.frame())
  utils::read.csv(csv, stringsAsFactors = FALSE, check.names = FALSE)
}

#' The report tables for a project
#'
#' As made by `cehbio_report_data()`: a list of deployments, nights, individuals and species tables,
#' plus `about` (models, sources, assumptions) and `text` (the report's words, shared with the Python
#' report).
#' @param pipeline "birds", "bats" or "images"
#' @param project the project folder
#' @param folder the report data folder, if not the usual place
#' @export
read_report_data <- function(pipeline, project, folder = NULL) {
  folder <- folder %||% file.path(results_folder(), pipeline, project, "report", "data")
  if (!dir.exists(folder)) {
    stop("No report data in ", folder, ". Make it with cehbio_report_data(\"", pipeline, "\", \"", project, "\").",
         call. = FALSE)
  }
  out <- lapply(stats::setNames(nm = c("deployments", "nights", "individuals", "species")),
                function(n) .read_table(folder, n))
  for (n in c("about", "text")) {
    f <- file.path(folder, paste0(n, ".json"))
    out[[n]] <- if (file.exists(f)) jsonlite::fromJSON(f, simplifyVector = TRUE) else list()
  }
  if (nrow(out$nights)) out$nights$night <- as.Date(out$nights$night)
  out$folder <- folder
  out
}

#' One deployment's results, as the pipeline wrote them
#'
#' @param what "detections" (every detection), "files" (every file and its status), or for images
#'   "analysis_ready" and "tracks"
#' @export
read_results <- function(pipeline, project, deployment, what = "detections") {
  root <- file.path(results_folder(), pipeline, project, deployment)
  old <- file.path(results_folder(), pipeline, project, "inference", deployment)      # before November 2026
  if (!dir.exists(root) && dir.exists(old)) root <- old
  pq <- file.path(root, sprintf("%s_%s.parquet", deployment, what))
  csv <- file.path(root, sprintf("%s_%s.csv", deployment, what))
  if (file.exists(pq) && requireNamespace("arrow", quietly = TRUE)) return(as.data.frame(arrow::read_parquet(pq)))
  if (file.exists(csv)) return(utils::read.csv(csv, stringsAsFactors = FALSE, check.names = FALSE))
  if (file.exists(pq)) stop("Only a .parquet file is here: install.packages(\"arrow\") to read it.", call. = FALSE)
  stop("No ", what, " results for ", deployment, " in ", root, call. = FALSE)
}
