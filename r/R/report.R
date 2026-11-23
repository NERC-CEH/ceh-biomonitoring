#' Summary reports for a project, made in R
#'
#' One report per deployment (and one for the project), in `<results>/<pipeline>/<project>/report/`, the
#' same place and the same content as the Python report (`cehbio report`), from the same tables. Makes the
#' tables first if they aren't there (or `refresh = TRUE`). Needs Quarto and a few R packages:
#' `cehbio_install("reports")` gets them, once.
#'
#' @param pipeline "birds", "bats" or "images"
#' @param project the project folder
#' @param deployments only these (default: all)
#' @param sites,weather passed to `cehbio_report_data()` when the tables are made
#' @param refresh remake the tables first (after new results)
#' @param formats any of "html", "docx" (Word) and "pdf". PDF uses Quarto's own engine (Typst); where
#'   that's blocked (some managed laptops block it), the Word version is converted by Word or LibreOffice
#' @param reference_doc a Word file whose styles the Word report uses (e.g. a UKCEH template)
#' @return the report files, invisibly
#' @export
cehbio_report <- function(pipeline, project, deployments = NULL, sites = NULL, weather = "open-meteo",
                          refresh = FALSE, formats = "html", reference_doc = NULL) {
  need <- c("quarto", "knitr", "ggplot2")
  if (!all(vapply(need, requireNamespace, TRUE, quietly = TRUE))) {
    stop("Reports need a few things set up first. Run cehbio_install(\"reports\") once.", call. = FALSE)
  }
  q <- cehbio_quarto(install = FALSE)
  if (is.null(q)) stop("Reports need Quarto. Run cehbio_install(\"reports\") once to get it.", call. = FALSE)
  old_q <- Sys.getenv("QUARTO_PATH", NA)
  Sys.setenv(QUARTO_PATH = q)
  on.exit(if (is.na(old_q)) Sys.unsetenv("QUARTO_PATH") else Sys.setenv(QUARTO_PATH = old_q), add = TRUE)
  bad <- setdiff(formats, c("html", "docx", "pdf"))
  if (length(bad)) stop("Unknown format(s): ", paste(bad, collapse = ", "), ". Use html, docx, pdf.", call. = FALSE)
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
  on.exit(unlink(work, recursive = TRUE), add = TRUE)
  file.copy(file.path(tmpl, c("deployment.qmd", "project.qmd", "report.css")), work, overwrite = TRUE)
  what <- tools::toTitleCase(d$text$labels$what)
  jobs <- lapply(deps, function(dep) {
    info <- d$deployments[d$deployments$deployment_id == dep, ]
    sub <- paste0(what, " \u00b7 ", project,
                  if (nrow(info) && !is.na(info$first_night)) paste0(" \u00b7 ", info$first_night, " to ", info$last_night) else "")
    list(qmd = "deployment.qmd", stem = dep, params = list(data_folder = folder, pipeline = pipeline,
                                                           project = project, deployment = dep, subtitle = sub))
  })
  if (is.null(deployments) && length(deps) > 1) {
    jobs[[length(jobs) + 1]] <- list(qmd = "project.qmd", stem = paste0(project, "_project"),
                                     params = list(data_folder = folder, pipeline = pipeline, project = project,
                                                   subtitle = paste0(what, " \u00b7 ", length(deps), " deployments")))
  }
  files <- character()
  for (fmt in formats) for (j in jobs) {
    f <- .render_one(work, j$qmd, j$stem, j$params, fmt, out, reference_doc)
    files <- c(files, f)
    message("  ", basename(f))
  }
  message(length(files), " reports in ", out)
  invisible(files)
}

.render_one <- function(work, qmd, stem, params, fmt, out, reference_doc = NULL) {
  to <- c(html = "html", docx = "docx", pdf = "typst")[[fmt]]
  ext <- if (fmt == "pdf") "pdf" else fmt
  target <- paste0(stem, ".", ext)
  args <- c("--to", to)
  if (fmt %in% c("docx", "pdf") && !is.null(reference_doc)) {
    args <- c(args, "-M", paste0("reference-doc:", normalizePath(reference_doc, winslash = "/")))
  }
  ok <- tryCatch({
    quarto::quarto_render(file.path(work, qmd), output_file = target, quiet = TRUE, execute_params = params,
                          quarto_args = args)
    file.exists(file.path(work, target))
  }, error = function(e) FALSE)
  if (!ok && fmt == "pdf") {                      # Typst blocked or missing: Word, then Word or LibreOffice
    docx <- .render_one(work, qmd, paste0(stem, "_for_pdf"), params, "docx", work, reference_doc)
    ok <- .docx_to_pdf(docx, file.path(work, target))
  }
  if (!ok) stop("Quarto couldn't make the ", fmt, " report for ", stem,
                if (fmt == "pdf") " (and neither Word nor LibreOffice was found to make the PDF)", call. = FALSE)
  dest <- file.path(out, target)
  if (normalizePath(dest, mustWork = FALSE) != normalizePath(file.path(work, target)))
    file.copy(file.path(work, target), dest, overwrite = TRUE)
  dest
}

.docx_to_pdf <- function(docx, pdf) {
  if (.Platform$OS.type == "windows") {
    ps <- tempfile(fileext = ".ps1")
    writeLines(c("$w = New-Object -ComObject Word.Application", "$w.Visible = $false; $w.DisplayAlerts = 0",
                 "try { $d = $w.Documents.Open($args[0], $false, $true); $d.Fields.Update() | Out-Null",
                 "      $d.SaveAs([ref]$args[1], [ref]17); $d.Close([ref]0) } finally { $w.Quit() }"), ps)
    system2("powershell", c("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", shQuote(ps),
                            shQuote(normalizePath(docx)), shQuote(normalizePath(pdf, mustWork = FALSE))),
            stdout = FALSE, stderr = FALSE)
    if (file.exists(pdf)) return(TRUE)
  }
  office <- Sys.which(c("soffice", "libreoffice"))
  office <- office[nzchar(office)]
  if (length(office)) {
    system2(office[1], c("--headless", "--convert-to", "pdf", "--outdir", shQuote(dirname(pdf)), shQuote(docx)),
            stdout = FALSE, stderr = FALSE)
    made <- file.path(dirname(pdf), sub("\\.docx$", ".pdf", basename(docx)))
    if (file.exists(made) && made != pdf) file.rename(made, pdf)
  }
  file.exists(pdf)
}
