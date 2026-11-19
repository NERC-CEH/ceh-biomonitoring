#' Summary reports for a project, made in R
#'
#' One self-contained HTML page per deployment, in `<results>/<pipeline>/<project>/report/`, the same
#' place and the same content as the Python report (`cehbio report`), from the same tables. Makes the
#' tables first if they aren't there (or `refresh = TRUE`). Needs Quarto (https://quarto.org) and the
#' quarto, knitr and ggplot2 R packages.
#'
#' @param pipeline "birds", "bats" or "images"
#' @param project the project folder
#' @param deployments only these (default: all)
#' @param sites,weather passed to `cehbio_report_data()` when the tables are made
#' @param refresh remake the tables first (after new results)
#' @return the report files, invisibly
#' @export
cehbio_report <- function(pipeline, project, deployments = NULL, sites = NULL, weather = "open-meteo",
                          refresh = FALSE) {
  for (p in c("quarto", "knitr", "ggplot2")) {
    if (!requireNamespace(p, quietly = TRUE)) stop("Reports need the ", p, " package: install.packages(\"", p, "\")",
                                                   call. = FALSE)
  }
  folder <- file.path(results_folder(), pipeline, project, "report", "data")
  if (refresh || !is.null(sites) || !file.exists(file.path(folder, "text.json"))) {
    cehbio_report_data(pipeline, project, sites = sites, weather = weather)
  }
  d <- read_report_data(pipeline, project, folder = folder)
  out <- dirname(folder)
  deps <- deployments %||% names(d$text$deployments)
  tmpl <- system.file("templates", package = "cehbio")
  work <- file.path(tempdir(), paste0("cehbio_report_", as.integer(Sys.time())))
  dir.create(work, recursive = TRUE)
  file.copy(file.path(tmpl, c("deployment.qmd", "project.qmd", "report.css")), work, overwrite = TRUE)
  files <- character()
  for (dep in deps) {
    info <- d$deployments[d$deployments$deployment_id == dep, ]
    sub <- paste0(tools::toTitleCase(d$text$labels$what), " · ", project,
                  if (nrow(info) && !is.na(info$first_night)) paste0(" · ", info$first_night, " to ", info$last_night) else "")
    target <- paste0(dep, ".html")
    quarto::quarto_render(file.path(work, "deployment.qmd"), output_file = target, quiet = TRUE,
                          execute_params = list(data_folder = folder, pipeline = pipeline, project = project,
                                                deployment = dep, subtitle = sub))
    file.copy(file.path(work, target), file.path(out, target), overwrite = TRUE)
    files <- c(files, file.path(out, target))
    message("  ", target)
  }
  if (is.null(deployments) && length(deps) > 1) {
    target <- paste0(project, "_project.html")
    quarto::quarto_render(file.path(work, "project.qmd"), output_file = target, quiet = TRUE,
                          execute_params = list(data_folder = folder, pipeline = pipeline, project = project,
                                                subtitle = paste0(tools::toTitleCase(d$text$labels$what), " · ",
                                                                  length(deps), " deployments")))
    file.copy(file.path(work, target), file.path(out, target), overwrite = TRUE)
    files <- c(files, file.path(out, target))
    message("  ", target)
  }
  unlink(work, recursive = TRUE)
  message(length(files), " reports in ", out)
  invisible(files)
}
