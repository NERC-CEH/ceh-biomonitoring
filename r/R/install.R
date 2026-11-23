# Installing everything from R, with nothing else to fetch by hand: no Miniforge, no conda, no admin
# rights. uv (https://docs.astral.sh/uv, a single small program) fetches its own Python 3.11 and installs
# the toolkit into an environment in the toolkit's folder; Quarto (for Word and PDF reports) is
# downloaded there too. The same environment serves the `cehbio` command, so R and Python users share it.

#' Where the toolkit keeps its own programs
#'
#' The Python environment, uv and Quarto live here, not in your results. Set the `CEHBIO_HOME`
#' environment variable to use another folder. Default: `%LOCALAPPDATA%/ceh-biomonitoring` on Windows,
#' `~/.local/share/ceh-biomonitoring` elsewhere.
#' @export
cehbio_home <- function() {
  h <- Sys.getenv("CEHBIO_HOME")
  if (!nzchar(h)) {
    h <- if (.Platform$OS.type == "windows") file.path(Sys.getenv("LOCALAPPDATA"), "ceh-biomonitoring")
         else file.path(Sys.getenv("XDG_DATA_HOME", path.expand("~/.local/share")), "ceh-biomonitoring")
  }
  normalizePath(h, winslash = "/", mustWork = FALSE)
}

.win <- function() .Platform$OS.type == "windows"

# Downloads that work on UKCEH Windows laptops, whose certificate revocation check fails for some sites.
.download <- function(url, dest) {
  old <- Sys.getenv("R_LIBCURL_SSL_REVOKE_BEST_EFFORT", NA)
  Sys.setenv(R_LIBCURL_SSL_REVOKE_BEST_EFFORT = "TRUE")
  on.exit(if (is.na(old)) Sys.unsetenv("R_LIBCURL_SSL_REVOKE_BEST_EFFORT") else Sys.setenv(R_LIBCURL_SSL_REVOKE_BEST_EFFORT = old))
  op <- options(timeout = max(1200, getOption("timeout")))
  on.exit(options(op), add = TRUE)
  ok <- tryCatch(utils::download.file(url, dest, mode = "wb", quiet = TRUE, method = "libcurl") == 0,
                 error = function(e) FALSE, warning = function(w) FALSE)
  if (!ok || !file.exists(dest)) stop("Couldn't download ", url, ". Check the internet connection and try again.", call. = FALSE)
  invisible(dest)
}

.unpack <- function(archive, into) {
  dir.create(into, recursive = TRUE, showWarnings = FALSE)
  if (grepl("\\.zip$", archive)) utils::unzip(archive, exdir = into) else utils::untar(archive, exdir = into)
}

.platform <- function() {
  arch <- if (grepl("arm|aarch64", R.version$arch)) "aarch64" else "x86_64"
  os <- if (.win()) "windows" else if (Sys.info()[["sysname"]] == "Darwin") "mac" else "linux"
  list(os = os, arch = arch)
}

# Temporarily set environment variables while running a program (system2's env= is ignored on Windows).
.with_env <- function(vars, code) {
  old <- Sys.getenv(names(vars), unset = NA, names = TRUE)
  do.call(Sys.setenv, as.list(vars))
  on.exit(for (n in names(old)) if (is.na(old[[n]])) Sys.unsetenv(n) else do.call(Sys.setenv, stats::setNames(list(old[[n]]), n)))
  force(code)
}

.uv_env <- function() {
  home <- cehbio_home()
  v <- c(UV_PYTHON_INSTALL_DIR = file.path(home, "python"), UV_NO_MODIFY_PATH = "1", UV_PYTHON_PREFERENCE = "only-managed",
         UV_LINK_MODE = "copy")
  if (.win()) v <- c(v, UV_NATIVE_TLS = "1")          # use Windows' own certificates (works behind UKCEH's network)
  if (!.win() && dir.exists("/gws")) {                  # JASMIN: /tmp is too small for PyTorch and TensorFlow
    tmp <- file.path("/var/tmp", Sys.getenv("USER"), "cehbio-install")
    dir.create(tmp, recursive = TRUE, showWarnings = FALSE)
    v <- c(v, TMPDIR = tmp)
  }
  v
}

#' uv, the program that fetches Python and installs packages
#'
#' Uses uv if you have it, otherwise downloads it (once) into `cehbio_home()`.
#' @return the path to uv
#' @export
cehbio_uv <- function() {
  exe <- file.path(cehbio_home(), "uv", if (.win()) "uv.exe" else "uv")
  if (file.exists(exe)) return(exe)
  if (nzchar(Sys.which("uv"))) return(unname(Sys.which("uv")))
  p <- .platform()
  file <- switch(p$os, windows = sprintf("uv-%s-pc-windows-msvc.zip", p$arch),
                 mac = sprintf("uv-%s-apple-darwin.tar.gz", p$arch),
                 linux = sprintf("uv-%s-unknown-linux-gnu.tar.gz", p$arch))
  message("Getting uv (once) ...")
  tmp <- tempfile(fileext = if (p$os == "windows") ".zip" else ".tar.gz")
  .download(paste0("https://github.com/astral-sh/uv/releases/latest/download/", file), tmp)
  un <- tempfile()
  .unpack(tmp, un)
  found <- list.files(un, pattern = if (.win()) "^uv\\.exe$" else "^uv$", recursive = TRUE, full.names = TRUE)
  if (!length(found)) stop("The uv download didn't contain uv.", call. = FALSE)
  dir.create(dirname(exe), recursive = TRUE, showWarnings = FALSE)
  file.copy(found[1], exe, overwrite = TRUE)
  if (!.win()) Sys.chmod(exe, "755")
  if (system2(exe, "--version", stdout = FALSE, stderr = FALSE) != 0)
    stop("uv was downloaded to ", exe, " but this computer won't run it. If your organisation blocks ",
         "programs in your user folder, ask IT to allow it.", call. = FALSE)
  exe
}

#' Quarto, for Word and PDF reports
#'
#' Uses Quarto if it's installed, otherwise downloads it (once) into `cehbio_home()`.
#' @param install download it if it isn't found
#' @return the path to quarto, or NULL
#' @export
cehbio_quarto <- function(install = TRUE) {
  own <- file.path(cehbio_home(), "quarto", "bin", if (.win()) "quarto.exe" else "quarto")
  cand <- c(Sys.getenv("QUARTO_PATH"), own, unname(Sys.which("quarto")),
            if (.win()) file.path(Sys.getenv("LOCALAPPDATA"), "Programs/Quarto/bin/quarto.exe"),
            if (.win()) "C:/Program Files/Quarto/bin/quarto.exe")
  cand <- cand[nzchar(cand) & file.exists(cand)]
  if (length(cand)) return(normalizePath(cand[1], winslash = "/"))
  if (!install) return(NULL)
  p <- .platform()
  rel <- tryCatch(jsonlite::fromJSON(.download("https://api.github.com/repos/quarto-dev/quarto-cli/releases/latest",
                                               tempfile(fileext = ".json"))), error = function(e) NULL)
  v <- if (!is.null(rel)) sub("^v", "", rel$tag_name) else "1.8.27"
  file <- switch(p$os, windows = sprintf("quarto-%s-win.zip", v), mac = sprintf("quarto-%s-macos.tar.gz", v),
                 linux = sprintf("quarto-%s-linux-%s.tar.gz", v, if (p$arch == "aarch64") "arm64" else "amd64"))
  message("Getting Quarto ", v, " (once, about 150 MB) ...")
  tmp <- tempfile(fileext = if (p$os == "windows") ".zip" else ".tar.gz")
  .download(sprintf("https://github.com/quarto-dev/quarto-cli/releases/download/v%s/%s", v, file), tmp)
  dest <- file.path(cehbio_home(), "quarto")
  unlink(dest, recursive = TRUE)
  un <- tempfile()
  .unpack(tmp, un)
  top <- list.files(un, full.names = TRUE)
  src <- if (length(top) == 1 && dir.exists(file.path(top, "bin"))) top else un     # Linux/Mac tarballs have one top folder
  dir.create(dest, recursive = TRUE, showWarnings = FALSE)
  file.copy(list.files(src, full.names = TRUE, all.files = TRUE, no.. = TRUE), dest, recursive = TRUE)
  if (!file.exists(own)) stop("Quarto didn't unpack as expected into ", dest, call. = FALSE)
  if (system2(own, "--version", stdout = FALSE, stderr = FALSE) != 0)
    stop("Quarto was downloaded to ", dest, " but this computer won't run it. Ask IT to allow it, or install ",
         "Quarto from https://quarto.org.", call. = FALSE)
  normalizePath(own, winslash = "/")
}

# The `cehbio` command for the terminal, pointing at the toolkit's environment: put in ~/.local/bin,
# which is added to your PATH (on Windows, your own PATH only: no admin rights needed).
.shim <- function(py) {
  bin <- file.path(if (.win()) Sys.getenv("USERPROFILE") else path.expand("~"), ".local", "bin")
  dir.create(bin, recursive = TRUE, showWarnings = FALSE)
  if (.win()) {
    writeLines(c("@echo off", sprintf("\"%s\" -m ceh_biomonitoring %%*", normalizePath(py, winslash = "\\"))),
               file.path(bin, "cehbio.cmd"))
    ps <- paste0("$b='", normalizePath(bin, winslash = "\\"), "';",
                 "$p=[Environment]::GetEnvironmentVariable('Path','User');",
                 "if(-not $p){$p=''};",
                 "if(($p -split ';') -notcontains $b){[Environment]::SetEnvironmentVariable('Path',($p.TrimEnd(';')+';'+$b).TrimStart(';'),'User');'added'}")
    added <- suppressWarnings(system2("powershell", c("-NoProfile", "-Command", shQuote(ps)), stdout = TRUE, stderr = TRUE))
    if (any(grepl("added", added))) message("The `cehbio` command is ready in new terminal windows.")
  } else {
    f <- file.path(bin, "cehbio")
    writeLines(c("#!/bin/sh", sprintf("exec \"%s\" -m ceh_biomonitoring \"$@\"", py)), f)
    Sys.chmod(f, "755")
    if (!grepl(bin, Sys.getenv("PATH"), fixed = TRUE))
      message("To type `cehbio` in a terminal, add ", bin, " to your PATH (e.g. in ~/.bashrc).")
  }
}

#' Install the toolkit, once
#'
#' Everything is fetched for you: no Miniforge, conda or admin rights needed. The pipelines (the models)
#' get their own Python 3.11 environment in `cehbio_home()` (via uv), shared with the `cehbio` terminal
#' command. Reports are made in R, and get Quarto and the R packages they use. Run it again with other pipelines to add them.
#'
#' @param pipelines any of "birds", "bats", "images", "validation", "reports", "videos", or "all".
#'   "videos" (`cehbio_video()`, `cehbio_soundscape()`) needs no Python either.
#'   `cehbio_install("reports")` sets up reports only, with no Python at all: reports are made in R
#' @param source where to install the toolkit's Python side from (default: the newest on GitHub)
#' @param command also make the `cehbio` terminal command (default TRUE)
#' @export
cehbio_install <- function(pipelines = "reports",
                           source = "https://github.com/NERC-CEH/ceh-biomonitoring/archive/refs/heads/main.zip",
                           command = TRUE) {
  pipelines <- unique(pipelines)
  bad <- setdiff(pipelines, c("birds", "bats", "images", "validation", "reports", "videos", "all"))
  if (length(bad)) stop("Unknown: ", paste(bad, collapse = ", "), ". Choose from birds, bats, images, validation, reports, videos, all.", call. = FALSE)
  if (any(c("videos", "all") %in% pipelines)) {                 # videos from R are made in R: magick and av
    need <- c("magick", "av")[!vapply(c("magick", "av"), requireNamespace, TRUE, quietly = TRUE)]
    if (length(need)) { message("Installing R packages: ", paste(need, collapse = ", ")); utils::install.packages(need) }
  }
  python <- setdiff(pipelines, c("reports", "videos"))
  if (length(python)) python <- union(python, "reports")    # the Python side's reports come too: they're small
  if (length(python)) {                        # the toolkit's own Python environment (reports in R don't need it)
    uv <- cehbio_uv()
    env <- file.path(cehbio_home(), "env")
    py <- file.path(env, if (.win()) "Scripts/python.exe" else "bin/python")
    .with_env(.uv_env(), {
      if (!file.exists(py)) {
        message("Making the toolkit's Python environment (once) ...")
        if (system2(uv, c("venv", "--seed", "--python", "3.11", shQuote(env))) != 0 || !file.exists(py))
          stop("The Python environment wasn't made: see the messages above.", call. = FALSE)
      }
      message("Installing: ", paste(python, collapse = ", "), " (the first time takes a while: the models' packages are large)")
      spec <- sprintf("ceh-biomonitoring[%s] @ %s", paste(python, collapse = ","), source)
      if (system2(uv, c("pip", "install", "--python", shQuote(py), "--upgrade", shQuote(spec))) != 0)
        stop("The install didn't finish: see the messages above, then run cehbio_install() again.", call. = FALSE)
    })
    if (command) .shim(py)
  }
  {                                            # what reports from R need
    need <- c("quarto", "knitr", "ggplot2", "yaml")
    need <- need[!vapply(need, requireNamespace, TRUE, quietly = TRUE)]
    if (length(need)) { message("Installing R packages: ", paste(need, collapse = ", ")); utils::install.packages(need) }
    q <- cehbio_quarto()
    message("Quarto: ", q)
  }
  message("Done.")
  if (length(python)) cehbio_check()
  invisible(TRUE)
}
