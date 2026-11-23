# The report tables, made in R with no Python: the R twin of the toolkit's reporting/data.py. Both make
# the same files, with the same numbers and words, in <results>/<pipeline>/<project>/report/data/:
#   deployments, nights, individuals, species (.parquet and .csv), about.json, text.json, entoinsights/

# A setting from ~/.config/ceh-biomonitoring/settings.yml (e.g. "outputs_root", "cache_dir" under models).
.setting <- function(key, default = NULL) {
  f <- file.path(.config_dir(), "settings.yml")
  if (!file.exists(f) || !requireNamespace("yaml", quietly = TRUE)) return(default)
  s <- tryCatch(yaml::read_yaml(f), error = function(e) list())
  v <- if (key == "cache_dir") s$models$cache_dir else s[[key]]
  if (is.null(v) || !nzchar(v)) default else path.expand(sub("^~", .user_home(), v))
}

# Every run of a pipeline in a project: new layout (<project>/<dep>/working/...) and before November 2026.
.runs <- function(pipeline, project) {
  base <- file.path(results_folder(), pipeline, project)
  new <- Sys.glob(file.path(base, "*", "working", "file_lists", "manifest.json"))
  old <- Sys.glob(file.path(base, "keys", "manifests", "*", "manifest.json"))
  r <- rbind(
    data.frame(dep = basename(dirname(dirname(dirname(new)))), root = dirname(dirname(dirname(new))),
               chunks = file.path(dirname(dirname(dirname(new))), "working", "chunks"), stringsAsFactors = FALSE),
    data.frame(dep = basename(dirname(old)), root = file.path(base, "inference", basename(dirname(old))),
               chunks = file.path(base, "inference", basename(dirname(old)), "chunks"), stringsAsFactors = FALSE))
  r[order(r$dep, method = "radix"), , drop = FALSE]
}

.read_sites <- function(path) {
  if (is.null(path)) return(data.frame(deployment = character()))
  s <- utils::read.csv(path, stringsAsFactors = FALSE, check.names = FALSE, na.strings = c("", "NA"))
  names(s) <- tolower(trimws(names(s)))
  ren <- c(deployment_id = "deployment", lat = "latitude", lon = "longitude", tz = "timezone")
  for (k in names(ren)) if (k %in% names(s)) names(s)[names(s) == k] <- ren[[k]]
  if (!"deployment" %in% names(s)) stop(path, " needs a 'deployment' column (and latitude, longitude).", call. = FALSE)
  s$deployment <- as.character(s$deployment)
  s
}

.site <- function(dep, sites, det) {
  r <- if (nrow(sites) && dep %in% sites$deployment) as.list(sites[match(dep, sites$deployment), , drop = FALSE]) else list()
  for (k in c("latitude", "longitude")) {
    if ((is.null(r[[k]]) || is.na(r[[k]])) && k %in% names(det)) {
      v <- suppressWarnings(as.numeric(det[[k]]))
      v <- v[!is.na(v)]
      if (length(v)) r[[k]] <- v[1]
    }
  }
  str1 <- function(v) if (is.character(v) && length(v) && !is.na(v) && nzchar(trimws(v))) trimws(v) else NULL
  day <- function(v) { v <- str1(v); if (is.null(v)) NULL else format(as.Date(.parse_times(v))) }
  core <- list(latitude = if (!is.null(r$latitude) && !is.na(r$latitude)) as.numeric(r$latitude) else NULL,
               longitude = if (!is.null(r$longitude) && !is.na(r$longitude)) as.numeric(r$longitude) else NULL,
               timezone = str1(r$timezone), clock = str1(r$clock), start = day(r$start), end = day(r$end))
  taken <- c(names(core), "deployment", "deployment_id", "pipeline", "project", "first_night", "last_night", "nights_worked",
             "hours_worked", "files", "files_failed", "files_outside_deployment", "individuals", "taxa", "clock_used")
  for (k in setdiff(names(r), taken)) core[[k]] <- if (length(r[[k]]) && !is.na(r[[k]])) r[[k]] else NULL
  core
}

# Device clock times -> UTC. A local time that happens twice (when the clocks go back) is left unknown,
# and one that never happens (when they go forward) is moved to the change, as in Python.
.to_utc <- function(t, clock, tz) {
  if (is.na(clock) || clock == "UTC") return(t)
  if (clock == "local" && !is.null(tz)) {
    fmt <- "%Y-%m-%d %H:%M:%S"
    txt <- format(t, fmt, tz = "UTC")
    local1 <- function(s) {          # UTC seconds for a local wall time, or NA if it doesn't exist
      x <- suppressWarnings(as.POSIXct(s, tz = tz, format = fmt))
      ok <- !is.na(x) & format(x, fmt, tz = tz) == s
      ifelse(ok, as.numeric(x), NA_real_)
    }
    out <- local1(txt)
    gap <- is.na(out) & !is.na(t)                     # never happens (clocks forward): moved to the change
    for (i in which(gap)) {
      w <- ceiling(as.numeric(t[i]) / 60) * 60
      for (m in 0:180) { v <- local1(format(.ct(w + 60 * m), fmt, tz = "UTC")); if (!is.na(v)) { out[i] <- v; break } }
    }
    amb <- !is.na(out) & !gap & (format(.ct(out - 3600), fmt, tz = tz) == txt | format(.ct(out + 3600), fmt, tz = tz) == txt)
    out[amb] <- NA                                     # happens twice (clocks back): unknown
    return(.ct(out))
  }
  m <- regmatches(clock, regexec("^(?:UTC)?([+-])(\\d{1,2})(?::?(\\d{2}))?$", clock, perl = TRUE))[[1]]
  if (length(m)) {
    sign <- if (m[2] == "-") -1 else 1
    return(t - sign * (as.integer(m[3]) * 3600 + (if (nzchar(m[4])) as.integer(m[4]) else 0) * 60))
  }
  t
}

.decide_clock <- function(site, times, dep, notes) {
  if (!is.null(site$clock)) {
    c <- site$clock
    return(list(clock = if (toupper(c) == "UTC") "UTC" else if (tolower(c) == "local") "local" else c, notes = notes))
  }
  if (!is.null(site$latitude) && !is.null(site$timezone)) {
    res <- tryCatch(.clock_check(times, site$latitude, site$longitude, site$timezone), error = function(e) list())
    if (!is.null(res$clock) && res$clock %in% c("UTC", "local")) {
      return(list(clock = res$clock, notes = c(notes, sprintf("%s: clock taken as %s from the clock check (%s)", dep, res$clock, res$verdict))))
    }
    if (!is.null(res$verdict)) notes <- c(notes, sprintf("%s: the clock check couldn't decide (%s); local time assumed", dep, res$verdict))
    return(list(clock = "local", notes = notes))
  }
  list(clock = "UTC", notes = c(notes, paste0(dep, ": no time zone or clock given, so the device clock is taken as UTC ",
                                               "for the weather and moon (give them with --sites)")))
}

.provenance <- function(chunks_dir) {
  for (f in sort(Sys.glob(file.path(chunks_dir, "*_summary.json")))) {
    p <- tryCatch(jsonlite::fromJSON(f, simplifyVector = FALSE)$provenance, error = function(e) NULL)
    if (length(p)) return(p)
  }
  list()
}

.species_table <- function(ind) {
  if (!nrow(ind)) return(data.frame())
  key <- paste(ind$deployment_id, ind$kind, ind$taxon, sep = "\r")
  first <- !duplicated(key)
  out <- ind[first, c("deployment_id", "kind", "taxon")]
  s <- split(seq_len(nrow(ind)), factor(key, levels = unique(key)))
  m <- function(v) { v <- v[!is.na(v)]; if (length(v)) mean(v) else NA_real_ }
  mx <- function(v) { v <- v[!is.na(v)]; if (length(v)) max(v) else NA_real_ }
  out$individuals <- vapply(s, length, 0L)
  out$nights <- vapply(s, function(i) length(unique(ind$night[i][!is.na(ind$night[i])])), 0L)
  out$first_night <- vapply(s, function(i) min(ind$night[i], na.rm = TRUE), "")
  out$last_night <- vapply(s, function(i) max(ind$night[i], na.rm = TRUE), "")
  out$score_mean <- vapply(s, function(i) m(ind$score[i]), 0)
  out$score_max <- vapply(s, function(i) mx(ind$score[i]), 0)
  out$unlikely_this_month <- vapply(s, function(i) sum(ind$unlikely_this_month[i], na.rm = TRUE), 0L)
  if ("common_name" %in% names(ind)) {
    cn <- ind[!is.na(ind$common_name), c("taxon", "common_name")]
    cn <- cn[!duplicated(cn$taxon), ]
    out$common_name <- cn$common_name[match(out$taxon, cn$taxon)]
  }
  # sorted as groupby (deployment, kind, taxon), then by deployment and most individuals first
  out <- out[order(out$deployment_id, out$kind, out$taxon, method = "radix"), , drop = FALSE]
  out <- out[order(out$deployment_id, -out$individuals, method = "radix"), , drop = FALSE]
  rownames(out) <- NULL
  out
}

.entoinsights <- function(root, dep, pipeline, site, out) {
  dir.create(out, recursive = TRUE, showWarnings = FALSE)
  if (pipeline == "images") {
    f <- file.path(root, paste0(dep, "_analysis_ready.parquet"))
    if (!file.exists(f)) f <- file.path(root, paste0(dep, "_detections.parquet"))
    if (!file.exists(f)) return(NULL)
    d <- .read_any(f)
    for (i in 1:5) for (k in c("name", "confidence")) {
      from <- sprintf("regional_species_rank_%d_%s", i, k)
      if (from %in% names(d)) names(d)[names(d) == from] <- sprintf("top_%d_%s", i, if (k == "name") "species" else "confidence")
    }
    for (k in c("top_1_species", "top_1_confidence")) if (!k %in% names(d)) d[[k]] <- NA
    blank <- function(v) is.na(v) | !nzchar(trimws(as.character(v)))
    if (!"deployment_id" %in% names(d)) d$deployment_id <- NA
    d$deployment_id[blank(d$deployment_id)] <- dep
    if (!"deployment_name" %in% names(d)) d$deployment_name <- ""
    d$deployment_name[blank(d$deployment_name)] <- dep
    for (k in c("latitude", "longitude")) if (!k %in% names(d) || all(is.na(d[[k]]))) d[[k]] <- site[[k]] %||% NA
    if (!"image_path" %in% names(d)) d$image_path <- d$source_key
    t <- .parse_times(.col(d, "image_datetime"))
    d$image_datetime <- format(t, "%Y-%m-%d %H:%M:%S", tz = "UTC")
    if (!"recording_session" %in% names(d) || all(is.na(d$recording_session))) d$recording_session <- .night_of(t)
    d$outline <- NULL
    p <- file.path(out, paste0(dep, "_combined_results.csv"))
    .write_csv(d, p)
    return(p)
  }
  if (pipeline == "birds") {
    f <- file.path(root, paste0(dep, "_detections.parquet"))
    if (!file.exists(f)) return(NULL)
    d <- .read_any(f)
    if (!"confidence" %in% names(d)) return(NULL)
    b <- data.frame(path = d$source_key, filename = d$filename, site = dep, lat = site$latitude %||% NA,
                    lon = site$longitude %||% NA, scientific_name = d$species_name, common_name = .col(d, "common_name"),
                    confidence = d$confidence, start_time = d$start_time, end_time = d$end_time)
    p <- file.path(out, paste0(dep, "_birdnet_results.csv"))
    .write_csv(b, p)
    return(p)
  }
  NULL
}

.write_csv <- function(d, path) {
  for (k in names(d)) {
    if (inherits(d[[k]], "POSIXct")) d[[k]] <- format(d[[k]], "%Y-%m-%d %H:%M:%S", tz = "UTC")
    if (is.logical(d[[k]])) d[[k]] <- ifelse(is.na(d[[k]]), NA, ifelse(d[[k]], "True", "False"))    # as pandas writes them
  }
  utils::write.csv(d, path, row.names = FALSE, na = "", fileEncoding = "UTF-8")
}

#' Make the report tables for a project
#'
#' Writes deployments, nights (with weather and the moon), individuals and species tables to
#' `<results>/<pipeline>/<project>/report/data/`, with about.json, text.json and an EntoInsights copy.
#' Made in R, with no Python needed; the Python toolkit's `cehbio report-data` makes the same tables.
#' See `read_report_data()`.
#'
#' @inheritParams cehbio_run
#' @param deployments only these (default: all in the project)
#' @param sites a CSV with deployment, latitude, longitude, and optionally timezone, clock, start, end
#'   (and any other columns, e.g. site_name or country, which are kept)
#' @param weather "open-meteo" (non-commercial only), "era5-land" (commercial use allowed; needs a CDS
#'   key) or "none"
#' @param engine "r" (default) or "python" (the toolkit's `cehbio report-data`, if it's installed)
#' @return a summary list, invisibly
#' @export
cehbio_report_data <- function(pipeline, project, deployments = NULL, sites = NULL, weather = "open-meteo", engine = "r") {
  if (engine == "python") {
    return(invisible(cehbio("report-data", pipeline, .opt("project", project), .opt("sites", sites), .opt("weather", weather),
                            if (length(deployments)) c("--deployment", deployments))))
  }
  pipeline <- match.arg(pipeline, c("birds", "bats", "images"))
  runs <- .runs(pipeline, project)
  if (length(deployments)) runs <- runs[runs$dep %in% deployments, , drop = FALSE]
  if (!nrow(runs)) stop("No ", pipeline, " runs in project '", project, "' under ", results_folder(), ".", call. = FALSE)
  out <- file.path(results_folder(), pipeline, project, "report", "data")
  dir.create(out, recursive = TRUE, showWarnings = FALSE)
  site_table <- .read_sites(sites)
  notes <- character()
  dep_rows <- list(); night_parts <- list(); ind_parts <- list(); prov <- list()
  for (r in seq_len(nrow(runs))) {
    dep <- runs$dep[r]
    root <- runs$root[r]
    f_files <- file.path(root, paste0(dep, "_files.csv"))
    f_det <- file.path(root, paste0(dep, "_detections.parquet"))
    if (!file.exists(f_files)) { notes <- c(notes, sprintf("%s: not combined yet (no %s), left out", dep, basename(f_files))); next }
    files <- utils::read.csv(f_files, stringsAsFactors = FALSE, check.names = FALSE, na.strings = c("", "NA"))
    det <- if (file.exists(f_det)) .read_any(f_det, c("latitude", "longitude")) else data.frame()
    when <- .na_time(nrow(files))
    for (k in c("image_datetime", "file_datetime")) if (k %in% names(files)) { v <- .parse_times(files[[k]]); when[is.na(when)] <- v[is.na(when)] }
    if (any(is.na(when))) { v <- time_from_name(files$source_key[is.na(when)]); when[is.na(when)] <- v }
    files$when <- when
    files$night <- .night_of(when)
    site <- .site(dep, site_table, det)
    dc <- .decide_clock(site, files$when, dep, notes)
    clock <- dc$clock; notes <- dc$notes
    files$when_utc <- .to_utc(files$when, clock, site$timezone)
    res_file <- if (pipeline == "images") {
      c(file.path(root, paste0(dep, "_analysis_ready.parquet")), f_det)[file.exists(c(file.path(root, paste0(dep, "_analysis_ready.parquet")), f_det))][1]
    } else f_det
    ind <- if (!is.na(res_file) && file.exists(res_file)) .individuals(res_file, pipeline, dep) else data.frame()
    inside <- function(n) (if (!is.null(site$start)) n >= site$start else TRUE) & (if (!is.null(site$end)) n < site$end else TRUE)
    if (nrow(ind) && (!is.null(site$start) || !is.null(site$end))) { ind <- ind[inside(ind$night), , drop = FALSE]; rownames(ind) <- NULL }
    ind_parts[[length(ind_parts) + 1]] <- ind
    if (!length(prov)) prov <- .provenance(runs$chunks[r])
    ok <- !is.na(files$night) & !is.na(files$when)
    f <- files[ok, , drop = FALSE]
    g <- split(seq_len(nrow(f)), f$night)
    nights <- data.frame(night = names(g), deployment_id = dep,
                         first_file = .ct(vapply(g, function(i) min(as.numeric(f$when[i])), 0)),
                         last_file = .ct(vapply(g, function(i) max(as.numeric(f$when[i])), 0)),
                         first_utc = .ct(vapply(g, function(i) { v <- as.numeric(f$when_utc[i]); if (all(is.na(v))) NA_real_ else min(v, na.rm = TRUE) }, 0)),
                         last_utc = .ct(vapply(g, function(i) { v <- as.numeric(f$when_utc[i]); if (all(is.na(v))) NA_real_ else max(v, na.rm = TRUE) }, 0)),
                         files = vapply(g, length, 0L),
                         files_failed = vapply(g, function(i) sum(f$status[i] %in% "failed"), 0L),
                         files_with_detections = vapply(g, function(i) sum(f$status[i] %in% c("detections", "processed")), 0L),
                         stringsAsFactors = FALSE)
    rownames(nights) <- NULL
    nights$hours_worked <- round((as.numeric(nights$last_file) - as.numeric(nights$first_file)) / 3600, 2)
    nights$in_deployment <- if (!is.null(site$start) || !is.null(site$end)) inside(nights$night) else TRUE
    cnt <- if (nrow(ind)) table(ind$night) else integer()
    nights$individuals <- if (nrow(ind)) as.integer(ifelse(is.na(cnt[nights$night]), 0, cnt[nights$night])) else 0L
    nights$individuals_per_hour <- round(ifelse(nights$hours_worked > 0, nights$individuals / nights$hours_worked, NA), 3)
    if (!is.null(site$latitude)) {
      lat <- site$latitude; lon <- site$longitude
      moon <- t(vapply(seq_len(nrow(nights)), function(i) .moon_over(nights$first_utc[i], nights$last_utc[i], lat, lon),
                       c(moon_illumination = 0, moon_up_share = 0)))
      if (nrow(nights)) { nights$moon_illumination <- moon[, 1]; nights$moon_up_share <- moon[, 2] }
      if (!is.null(weather) && weather != "none" && nrow(nights)) {
        wx <- tryCatch({
          hours <- .hourly_weather(weather, lat, lon, as.Date(min(nights$first_utc, na.rm = TRUE)),
                                   as.Date(max(nights$last_utc, na.rm = TRUE) + 86400))
          lapply(seq_len(nrow(nights)), function(i) .weather_over(hours, nights$first_utc[i], nights$last_utc[i]))
        }, error = function(e) { notes <<- c(notes, sprintf("%s: no weather (%s)", dep, conditionMessage(e))); NULL })
        if (!is.null(wx)) for (k in .WX_COLS) nights[[k]] <- vapply(wx, function(v) if (is.null(v)) NA_real_ else unname(v[[k]]), 0)
      }
    } else {
      notes <- c(notes, paste0(dep, ": no latitude and longitude, so no weather or moon (give them with --sites)"))
    }
    night_parts[[length(night_parts) + 1]] <- nights
    worked <- nights[nights$files > 0 & nights$in_deployment, , drop = FALSE]
    if (any(!nights$in_deployment)) notes <- c(notes, sprintf("%s: %d nights outside the deployment dates (%s to %s) are left out of the totals",
                                                              dep, sum(!nights$in_deployment), site$start %||% "...", site$end %||% "..."))
    row <- list(deployment_id = dep, pipeline = pipeline, project = project,
                first_night = if (nrow(worked)) min(worked$night) else NA, last_night = if (nrow(worked)) max(worked$night) else NA,
                nights_worked = nrow(worked), hours_worked = sum(worked$hours_worked), files = sum(worked$files),
                files_failed = sum(worked$files_failed), files_outside_deployment = sum(nights$files[!nights$in_deployment]),
                individuals = nrow(ind), taxa = if (nrow(ind)) length(unique(ind$taxon)) else 0L)
    for (k in names(site)) row[[k]] <- site[[k]] %||% NA
    for (k in c("latitude", "longitude", "timezone", "clock", "start", "end")) if (is.null(row[[k]])) row[[k]] <- NA
    row$clock_used <- clock
    dep_rows[[length(dep_rows) + 1]] <- row
    if (pipeline %in% c("images", "birds")) {
      got <- .entoinsights(root, dep, pipeline, site, file.path(out, "entoinsights"))
      if (is.null(got) && pipeline == "birds") notes <- c(notes, paste0(dep, ": no EntoInsights copy (it reads BirdNET results only)"))
    }
  }
  tables <- list(deployments = .rbind_fill(lapply(dep_rows, function(r) as.data.frame(r, stringsAsFactors = FALSE))),
                 nights = .rbind_fill(night_parts), individuals = .rbind_fill(ind_parts))
  tables$species <- .species_table(tables$individuals)
  for (n in names(tables)) {
    nanoparquet::write_parquet(tables[[n]], file.path(out, paste0(n, ".parquet")))
    .write_csv(tables[[n]], file.path(out, paste0(n, ".csv")))
  }
  w <- if (!is.null(weather) && weather != "none") c(list(source = weather), .WEATHER_SOURCES[[weather]]) else NULL
  about <- list(made_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%S+00:00", tz = "UTC"),
                toolkit_version = as.character(utils::packageVersion("cehbio")), made_by = "R",
                pipeline = pipeline, project = project, deployments = I(vapply(dep_rows, `[[`, "", "deployment_id")),
                night = "noon to noon on the device's clock",
                individual = c(images = "an insect followed through consecutive photos (a track)",
                               birds = "a species calling in one recording, pauses of up to 60 s",
                               bats = "a species in one recording, pauses of up to 1 s (a pass)")[[pipeline]],
                weather = w, moon = "Schlyter's low-precision method (about 1 degree)", models = prov, notes = I(notes))
  jsonlite::write_json(about, file.path(out, "about.json"), auto_unbox = TRUE, pretty = TRUE, null = "null", digits = NA)
  jsonlite::write_json(.build_text(tables, about), file.path(out, "text.json"), auto_unbox = TRUE, pretty = TRUE,
                       null = "null", digits = NA)
  message(nrow(tables$deployments), " deployments, ", nrow(tables$nights), " nights, ",
          formatC(nrow(tables$individuals), big.mark = ",", format = "d"), " individuals, ", nrow(tables$species),
          " species rows -> ", out)
  for (n in notes) message("  NOTE ", n)
  invisible(list(out = out, deployments = nrow(tables$deployments), nights = nrow(tables$nights),
                 individuals = nrow(tables$individuals), species = nrow(tables$species), notes = notes))
}
