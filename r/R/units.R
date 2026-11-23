# Individuals from a run's results: the R twin of the toolkit's validation/units.py, for the report
# tables. The same rules, so R and Python count the same individuals:
#   images  a TRACK: one insect followed through photos (crops without a track count on their own),
#           named by the crop nearest the track's median species score; other insects by their order
#   birds   an EVENT: one species in one recording, joined while the pause is up to 60 s
#   bats    a PASS: one species in one recording, joined while the pause is up to 1 s

.SPECIES <- "regional_species_rank_1_name"
.SCORE <- "regional_species_rank_1_confidence"
.IMAGE_ALIASES <- c(filepath = "image_path", site_name = "deployment_name",
                    top_species_prediction = "regional_species_rank_1_name",
                    species_confidence = "regional_species_rank_1_confidence")
.PHOTO_TYPES <- c(".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".webp", ".bmp")

.col <- function(d, k, default = NA) if (k %in% names(d)) d[[k]] else rep(default, nrow(d))
.str <- function(x) { x <- trimws(as.character(x)); x[is.na(x)] <- ""; x }

.read_any <- function(f, cols = NULL) {
  if (grepl("\\.parquet$", f)) {
    if (!is.null(cols)) {
      have <- nanoparquet::read_parquet_schema(f)$name
      cols <- intersect(cols, have)
      return(as.data.frame(nanoparquet::read_parquet(f, col_select = cols)))
    }
    return(as.data.frame(nanoparquet::read_parquet(f)))
  }
  utils::read.csv(f, stringsAsFactors = FALSE, check.names = FALSE, na.strings = c("", "NA", "NaN", "nan"))
}

.not_photos <- function(paths) {
  names <- basename(gsub("\\\\", "/", as.character(paths)))
  ext <- tolower(regmatches(names, regexpr("\\.[A-Za-z0-9]+$", names)))
  e <- rep("", length(names))
  e[grepl("\\.[A-Za-z0-9]+$", names)] <- ext
  grepl("^\\$[RI][A-Z0-9]{6}", names) | !e %in% .PHOTO_TYPES
}

.image_units <- function(df, dep) {
  for (k in names(.IMAGE_ALIASES)) if (k %in% names(df) && !.IMAGE_ALIASES[[k]] %in% names(df)) names(df)[names(df) == k] <- .IMAGE_ALIASES[[k]]
  for (k in c("x_min", "y_min", "x_max", "y_max", "crop_area", .SCORE)) if (k %in% names(df)) df[[k]] <- suppressWarnings(as.numeric(df[[k]]))
  if (!all(c("x_min", "y_min", "x_max", "y_max") %in% names(df))) return(NULL)
  ok <- !is.na(df$x_min) & !is.na(df$y_min) & !is.na(df$x_max) & !is.na(df$y_max) & df$x_max > df$x_min & df$y_max > df$y_min
  df <- df[ok, , drop = FALSE]
  rig <- rep(FALSE, nrow(df))
  if ("masked_as" %in% names(df)) rig <- rig | nzchar(.str(df$masked_as))
  if ("masked" %in% names(df)) rig <- rig | tolower(.str(df$masked)) %in% c("true", "1", "1.0")
  if (any(rig)) { message("  NOTE: ", sum(rig), " boxes on the ring light or its screws are left out"); df <- df[!rig, , drop = FALSE] }
  if (!nrow(df)) return(NULL)
  path_col <- if ("image_path" %in% names(df)) "image_path" else "source_key"
  junk <- .not_photos(df[[path_col]])
  if (any(junk)) {
    message("  NOTE ", dep, ": ", sum(junk), " detections on ", length(unique(df[[path_col]][junk])), " files that aren't ",
            "trap photos (Recycle Bin copies or broken rows) are left out")
    df <- df[!junk, , drop = FALSE]
    if (!nrow(df)) return(NULL)
  }
  sp <- .str(.col(df, .SPECIES, ""))
  order <- .str(.col(df, "order_name", ""))
  moth <- tolower(.str(.col(df, "class_name", ""))) == "moth"
  lep <- grepl("lepidoptera", order, ignore.case = TRUE)
  noise <- !moth & !lep & sp == "" & order != ""
  keep <- sp != "" | noise
  df <- df[keep, , drop = FALSE]; sp <- sp[keep]; order <- order[keep]; noise <- noise[keep]
  if (!nrow(df)) return(NULL)
  if (!"image_path" %in% names(df)) df$image_path <- df$source_key
  df$deployment_id <- .str(.col(df, "deployment_id", ""))
  key <- paste(trimws(df$deployment_id), trimws(as.character(df$image_path)), .py_num(df$x_min), .py_num(df$y_min),
               .py_num(df$x_max), .py_num(df$y_max), sep = "|")
  track <- .str(.col(df, "track_id", ""))
  need_id <- track == ""
  df$unit_id <- paste0(df$deployment_id, "::", track)
  df$unit_id[need_id] <- paste0("det_", .sha20(key[need_id]))
  cand <- df[sp != "", , drop = FALSE]
  cand$species <- sp[sp != ""]
  cand$noise_class <- NA_character_
  if (nrow(cand)) {
    grp <- paste(cand$species, cand$unit_id, sep = "\r")
    s <- cand[[.SCORE]] %||% rep(NA_real_, nrow(cand))
    med <- stats::ave(s, grp, FUN = function(v) stats::median(v, na.rm = TRUE))
    dist <- abs(s - med)
    dist[is.na(dist)] <- Inf
    o <- order(cand$species, cand$unit_id, dist, method = "radix")
    cand <- cand[o, , drop = FALSE]
    cand <- cand[!duplicated(paste(cand$species, cand$unit_id, sep = "\r")), , drop = FALSE]
  }
  nz <- df[noise, , drop = FALSE]
  nz$noise_class <- order[noise]
  nz$species <- paste0("not a moth: ", order[noise])
  nz <- nz[!duplicated(nz$unit_id), , drop = FALSE]
  u <- .rbind_fill(list(cand, nz))
  u$score <- if (.SCORE %in% names(u)) u[[.SCORE]] else NA_real_
  u$score_type <- .SCORE
  un <- .col(u, "rank_1_unlikely_this_month", FALSE)
  u$unlikely <- !is.na(un) & tolower(as.character(un)) %in% c("true", "1")
  b <- .best_times(if ("image_datetime" %in% names(u)) u$image_datetime else NULL, u$image_path)
  u$when <- b$when
  if (b$disagree) message("  NOTE ", dep, ": ", b$disagree, " photos' times in the results differ from their file names ",
                          "(clock corrections when the results were made, usually): the results' times are used")
  u
}

.audio_units <- function(d, group) {
  gap_s <- if (group == "birds") 60 else 1
  score <- intersect(if (group == "birds") c("logit", "confidence") else c("class_probability", "detection_probability"), names(d))[1]
  if (is.na(score)) stop("These ", group, " results have no score column.", call. = FALSE)
  d$species_name <- trimws(as.character(d$species_name))
  d <- d[!is.na(d$species_name) & d$species_name != "", , drop = FALSE]
  if (!nrow(d)) return(NULL)
  d[[score]] <- suppressWarnings(as.numeric(d[[score]]))
  from_col <- if ("file_datetime" %in% names(d)) .parse_times(d$file_datetime) else .na_time(nrow(d))
  from_name <- time_from_name(d$source_key, date_only_ok = TRUE)
  d$when <- from_col
  d$when[is.na(d$when)] <- from_name[is.na(d$when)]
  d <- d[order(as.character(d$source_key), d$species_name, d$start_time, method = "radix"), , drop = FALSE]
  same <- c(FALSE, d$source_key[-1] == d$source_key[-nrow(d)] & d$species_name[-1] == d$species_name[-nrow(d)])
  prev_end <- c(NA, d$end_time[-nrow(d)])
  prev_end[!same] <- NA
  d$unit <- cumsum(is.na(prev_end) | (d$start_time - prev_end) > gap_s)
  first <- !duplicated(d$unit)
  u <- d[first, intersect(c("species_name", "source_key", "deployment_id", "common_name"), names(d)), drop = FALSE]
  first_known <- function(v) { k <- !is.na(v); i <- match(unique(d$unit), d$unit[k]); v[k][i] }    # as pandas' first()
  u$when <- .ct(first_known(as.numeric(d$when)))
  for (k in intersect(c("deployment_id", "common_name"), names(d))) u[[k]] <- first_known(d[[k]])
  u$start_s <- tapply(d$start_time, d$unit, min)
  u$end_s <- tapply(d$end_time, d$unit, max)
  u$score <- tapply(d[[score]], d$unit, function(v) if (all(is.na(v))) NA_real_ else max(v, na.rm = TRUE))
  u$unlikely <- if ("unlikely_this_month" %in% names(d))
    as.logical(tapply(tolower(as.character(d$unlikely_this_month)) %in% c("true", "1"), d$unit, any)) else FALSE
  names(u)[names(u) == "species_name"] <- "species"
  u$score_type <- score
  u$noise_class <- NA_character_
  u$unit_id <- .sha20(paste(u$source_key, .py_num(u$start_s), u$species, sep = "|"))
  u
}

.rbind_fill <- function(parts) {
  parts <- Filter(function(p) !is.null(p) && nrow(p), parts)
  if (!length(parts)) return(data.frame())
  cols <- unique(unlist(lapply(parts, names)))
  do.call(rbind, lapply(parts, function(p) { for (k in setdiff(cols, names(p))) p[[k]] <- NA; p[cols] }))
}

# One row per individual, as reporting/data.py individuals()
.individuals <- function(result_file, group, dep) {
  cols <- if (group == "images") c("image_path", "source_key", "image_datetime", "deployment_id", "x_min", "y_min", "x_max",
                                   "y_max", "crop_area", "class_name", "order_name", "order_confidence", .SPECIES, .SCORE,
                                   "track_id", "rank_1_unlikely_this_month", "masked", "masked_as", names(.IMAGE_ALIASES)) else NULL
  d <- .read_any(result_file, cols)
  if (!nrow(d)) return(data.frame())
  u <- if (group == "images") .image_units(d, dep) else .audio_units(d, group)
  if (is.null(u) || !nrow(u)) return(data.frame())
  u <- u[order(-ifelse(is.na(u$score), -Inf, u$score), method = "radix"), , drop = FALSE]
  u <- u[!duplicated(u$unit_id), , drop = FALSE]
  kind <- if (group == "images") ifelse(!is.na(u$noise_class), "other insect", "moth") else substr(group, 1, nchar(group) - 1)
  out <- data.frame(deployment_id = .str(.col(u, "deployment_id", "")), unit_id = u$unit_id, when = u$when,
                    taxon = sub("not a moth: ", "", u$species, fixed = TRUE), kind = kind, score = as.numeric(u$score),
                    score_type = u$score_type, unlikely_this_month = as.logical(u$unlikely), stringsAsFactors = FALSE)
  for (k in c("common_name", "order_name", "n_detections", "start_s", "end_s", "image_path", "source_key"))
    if (k %in% names(u)) out[[k]] <- u[[k]]
  if (group == "images" && "order_confidence" %in% names(u)) {
    oc <- suppressWarnings(as.numeric(u$order_confidence))
    other <- out$kind == "other insect" & is.na(out$score)
    out$score[other] <- oc[other]
    out$score_type[other] <- "order_confidence"
  }
  out$night <- .night_of(out$when)
  rownames(out) <- NULL
  out
}
