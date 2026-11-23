# Videos of a light trap's night, and soundscapes of recordings: the R twin of the toolkit's videos/
# (night.py, soundscape.py), with the same options, layout and words. Uses the magick and av packages
# (cehbio_install("videos") gets them); av carries ffmpeg's libraries inside R, so no ffmpeg program is
# needed (managed laptops often block one).

.V_NAVY <- "#133b64"
.V_TRACK <- c("#f4c03d", "#67ccea", "#e76124", "#4db264", "#cfbcd5", "#477AE2", "#ffffff", "#ff8fa3")
.V_OTHER <- "#bdbdbd"
.V_CAVEAT <- "Names are suggestions from computer models, not checked by an expert"
.V_RANGES <- list(birds = c(0, 12000), bats = c(10000, 130000))
.V_SLOW <- c(birds = 1, bats = 10)
.V_CLIP <- c(birds = 10, bats = 1)

.need_video_pkgs <- function() {
  miss <- c("magick", "av")[!vapply(c("magick", "av"), requireNamespace, TRUE, quietly = TRUE)]
  if (length(miss)) stop("Videos need the ", paste(miss, collapse = " and "), " package", if (length(miss) > 1) "s",
                         ". Run cehbio_install(\"videos\") once.", call. = FALSE)
}

# the same colour for the same track as in Python (md5 of the name, as a big number, modulo the palette)
.colour_for <- function(key) {
  h <- digest::digest(as.character(key), algo = "md5", serialize = FALSE)
  r <- 0
  for (ch in strsplit(h, "")[[1]]) r <- (r * 16 + strtoi(ch, 16L)) %% length(.V_TRACK)
  .V_TRACK[r + 1]
}

# Where a photo or recording is: the path in the results, a copy under source_root, or (with the
# Python toolkit installed) the object store.
.media_finder <- function(source_root = NULL) {
  index <- NULL
  function(path) {
    path <- as.character(path)
    if (file.exists(path)) return(path)
    if (length(source_root)) {
      if (is.null(index)) {
        f <- unlist(lapply(source_root, list.files, recursive = TRUE, full.names = TRUE))
        index <<- f[!duplicated(basename(f))]
        names(index) <<- basename(index)
      }
      hit <- index[basename(gsub("\\\\", "/", path))]
      if (!is.na(hit)) return(unname(hit))
    }
    NA_character_
  }
}

.bar <- function(width, y, h, left, right = "", cex = 1.35) {
  graphics::rect(0, y, width, y + h, col = .V_NAVY, border = NA)
  graphics::text(12, y + h / 2, left, adj = c(0, 0.5), col = "white", cex = cex)
  if (nzchar(right)) graphics::text(width - 12, y + h / 2, right, adj = c(1, 0.5), col = "white", cex = cex)
}

.tab <- function(x, y, text, colour, cex = 1.25, above = TRUE) {
  w <- abs(graphics::strwidth(text, cex = cex)) + 8          # abs(): on pictures, y runs downwards
  h <- abs(graphics::strheight("Ag", cex = cex)) + 8
  y0 <- if (above && y - h >= 0) y - h else y
  graphics::rect(x, y0, x + w, y0 + h, col = grDevices::adjustcolor("black", 0.75), border = NA)
  graphics::text(x + 4, y0 + h / 2, text, adj = c(0, 0.5), col = colour, cex = cex)
}

.draw_on <- function(img, expr) {
  out <- magick::image_draw(img)
  graphics::par(family = "sans")
  force(expr)
  grDevices::dev.off()
  out
}

# ------------------------------------------------------------------ a night at the light trap
.video_load <- function(project, deployment) {
  root <- file.path(results_folder(), "images", project, deployment)
  if (!dir.exists(root)) root <- file.path(results_folder(), "images", project, "inference", deployment)
  f_files <- file.path(root, paste0(deployment, "_files.csv"))
  if (!file.exists(f_files)) stop("No results for ", deployment, " in ", root, ".", call. = FALSE)
  files <- utils::read.csv(f_files, stringsAsFactors = FALSE, check.names = FALSE, na.strings = c("", "NA"))
  res <- c(file.path(root, paste0(deployment, c("_analysis_ready.parquet", "_detections.parquet"))))
  res <- res[file.exists(res)][1]
  cols <- c("image_path", "source_key", "image_datetime", "x_min", "y_min", "x_max", "y_max", "class_name", "order_name",
            .SPECIES, .SCORE, "track_id", "masked", "masked_as", "bucket_name")
  boxes <- if (!is.na(res)) .read_any(res, cols) else data.frame()
  when <- .na_time(nrow(files))
  for (k in c("image_datetime", "file_datetime")) if (k %in% names(files)) { v <- .parse_times(files[[k]]); when[is.na(when)] <- v[is.na(when)] }
  if (any(is.na(when))) when[is.na(when)] <- time_from_name(files$source_key[is.na(when)])
  files$when <- when
  files$night <- .night_of(when)
  files <- files[!is.na(files$when), , drop = FALSE]
  files <- files[order(files$when), , drop = FALSE]
  files$name <- basename(gsub("\\\\", "/", files$source_key))
  if (nrow(boxes)) {
    for (k in c("x_min", "y_min", "x_max", "y_max")) boxes[[k]] <- suppressWarnings(as.numeric(boxes[[k]]))
    ok <- stats::complete.cases(boxes[, c("x_min", "y_min", "x_max", "y_max")]) & boxes$x_max > boxes$x_min
    rig <- rep(FALSE, nrow(boxes))
    if ("masked_as" %in% names(boxes)) rig <- rig | nzchar(.str(boxes$masked_as))
    if ("masked" %in% names(boxes)) rig <- rig | tolower(.str(boxes$masked)) %in% c("true", "1", "1.0")
    boxes <- boxes[ok & !rig, , drop = FALSE]
    p <- if ("image_path" %in% names(boxes)) boxes$image_path else boxes$source_key
    boxes$name <- basename(gsub("\\\\", "/", p))
    boxes$track_id <- .str(.col(boxes, "track_id", ""))
  }
  list(files = files, boxes = boxes, root = root)
}

.box_text <- function(r, min_score, labels) {
  sp <- .str(.col(r, .SPECIES, ""))
  if (nzchar(sp)) {
    colour <- .colour_for(if (nzchar(r$track_id)) r$track_id else sp)
    if (labels == "none") return(list("", colour))
    sc <- suppressWarnings(as.numeric(.col(r, .SCORE, NA)))
    if (!is.na(sc) && sc < min_score) return(list("moth", colour))
    return(list(paste0(sp, if (!is.na(sc)) sprintf(" %.2f", sc) else ""), colour))
  }
  o <- .str(.col(r, "order_name", ""))
  list(if (labels == "none") "" else if (nzchar(o)) o else "insect", .V_OTHER)
}

.night_video <- function(deployment, night, files, boxes, find, out_dir, fps, width, trail, min_score, labels) {
  photos <- files[files$night == night, , drop = FALSE]
  frames_dir <- tempfile("cehbio_frames_"); dir.create(frames_dir)
  on.exit(unlink(frames_dir, recursive = TRUE), add = TRUE)
  hist <- list(); last <- list(); n <- 0; missing <- 0; size <- NULL
  for (i in seq_len(nrow(photos))) {
    p <- photos[i, ]
    path <- find(p$source_key)
    if (is.na(path)) { missing <- missing + 1; next }
    im <- tryCatch(magick::image_read(path), error = function(e) NULL)
    if (is.null(im)) { missing <- missing + 1; next }
    info <- magick::image_info(im)
    scale <- min(1, width / info$width)
    if (scale < 1) im <- magick::image_scale(im, paste0(round(info$width * scale)))
    info <- magick::image_info(im)
    if (is.null(size)) size <- c(info$width - info$width %% 2, info$height + 72)
    canvas <- magick::image_composite(magick::image_blank(size[1], size[2], .V_NAVY), im, offset = "+0+40")
    g <- if (nrow(boxes)) boxes[boxes$name == p$name, , drop = FALSE] else boxes
    canvas <- .draw_on(canvas, {
      if (nrow(g)) for (k in seq_len(nrow(g))) {
        r <- g[k, ]
        x0 <- r$x_min * scale; y0 <- r$y_min * scale + 40; x1 <- r$x_max * scale; y1 <- r$y_max * scale + 40
        lt <- .box_text(r, min_score, labels)
        if (nzchar(r$track_id) && trail > 0) {
          h <- rbind(hist[[r$track_id]], c((x0 + x1) / 2, (y0 + y1) / 2))
          hist[[r$track_id]] <- utils::tail(h, trail)
          last[[r$track_id]] <- i
        }
        graphics::rect(x0, y0, x1, y1, border = lt[[2]], lwd = 3)
        if (nzchar(lt[[1]])) .tab(x0, y0, lt[[1]], lt[[2]])
      }
      for (tid in names(hist)) if (nrow(hist[[tid]]) > 1 && i - last[[tid]] <= trail)
        graphics::lines(hist[[tid]][, 1], hist[[tid]][, 2], col = .colour_for(tid), lwd = 2)
      .bar(size[1], 0, 40, paste0(deployment, "  \u00b7  night of ", night),
           paste0(format(p$when, "%H:%M:%S", tz = "UTC"), "  \u00b7  ", nrow(g), " insect", if (nrow(g) != 1) "s" else ""), 1.45)
      .bar(size[1], size[2] - 32, 32, .V_CAVEAT, "UKCEH ceh-biomonitoring", 1.1)
    })
    n <- n + 1
    magick::image_write(magick::image_crop(canvas, paste0(size[1], "x", size[2])), file.path(frames_dir, sprintf("f%06d.jpg", n)), format = "jpeg", quality = 92)
  }
  if (!n) { message("  ", night, ": none of the ", nrow(photos), " photos could be found (give source_root)"); return(NULL) }
  out <- file.path(out_dir, sprintf("%s_%s.mp4", deployment, night))
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
  av::av_encode_video(list.files(frames_dir, full.names = TRUE), out, framerate = fps, verbose = FALSE)
  message("  ", basename(out), ": ", n, " photos", if (missing) paste0(" (", missing, " couldn't be found)") else "")
  out
}

.individual_videos <- function(deployment, night, files, boxes, find, out_dir, n = 5, fps = 2, side = 480, min_photos = 3,
                               tracks = NULL) {
  b <- merge(boxes, files[, c("name", "night", "when", "source_key")], by = "name", suffixes = c(".box", ""))
  b <- b[b$night == night & nzchar(b$track_id), , drop = FALSE]
  if (!nrow(b)) return(character())
  counts <- tapply(b$name, b$track_id, function(x) length(unique(x)))
  pick <- if (length(tracks)) intersect(tracks, names(counts)) else {
    cn <- counts[counts >= min_photos]
    utils::head(names(cn)[order(-cn, method = "radix")], n)
  }
  written <- character()
  for (tid in pick) {
    g <- b[b$track_id == tid, , drop = FALSE]
    g <- g[order(g$when), , drop = FALSE]
    sp <- .str(.col(g, .SPECIES, ""))
    sp <- sp[nzchar(sp)]
    name <- if (length(sp)) names(sort(table(sp), decreasing = TRUE))[1] else "insect"
    head <- sprintf("%s  \u00b7  %s to %s  \u00b7  %d photos", name, format(min(g$when), "%H:%M", tz = "UTC"),
                    format(max(g$when), "%H:%M", tz = "UTC"), length(unique(g$name)))
    frames_dir <- tempfile("cehbio_frames_"); dir.create(frames_dir)
    k <- 0
    for (j in seq_len(nrow(g))) {
      r <- g[j, ]
      path <- find(r$source_key)
      if (is.na(path)) next
      im <- magick::image_read(path)
      w <- r$x_max - r$x_min; h <- r$y_max - r$y_min
      half <- max(w, h) * 0.9 + 20
      cx <- (r$x_min + r$x_max) / 2; cy <- (r$y_min + r$y_max) / 2
      info <- magick::image_info(im)
      pad <- ceiling(half)
      im <- magick::image_border(im, "black", paste0(pad, "x", pad))      # so crops near the edge stay square
      crop <- magick::image_crop(im, sprintf("%dx%d+%d+%d", round(2 * half), round(2 * half), round(cx - half + pad), round(cy - half + pad)))
      crop <- magick::image_scale(crop, paste0(side, "x", side, "!"))
      kk <- side / (2 * half)
      canvas <- magick::image_composite(magick::image_blank(side, side + 72, .V_NAVY), crop, offset = "+0+40")
      col <- .colour_for(tid)
      lt <- .box_text(r, 0, "species")
      canvas <- .draw_on(canvas, {
        bx0 <- (r$x_min - (cx - half)) * kk; by0 <- (r$y_min - (cy - half)) * kk + 40
        graphics::rect(bx0, by0, bx0 + w * kk, by0 + h * kk, border = col, lwd = 3)
        .tab(6, 46, paste(format(r$when, "%H:%M:%S", tz = "UTC"), lt[[1]]), col, above = FALSE)
        .bar(side, 0, 40, head, cex = 1.15)
        .bar(side, side + 40, 32, "Suggested names, not checked", tid, cex = 1.05)
      })
      k <- k + 1
      magick::image_write(canvas, file.path(frames_dir, sprintf("f%06d.jpg", k)), format = "jpeg", quality = 92)
    }
    if (k) {
      out <- file.path(out_dir, sprintf("%s_%s_%s.mp4", deployment, night, tid))
      av::av_encode_video(list.files(frames_dir, full.names = TRUE), out, framerate = fps, verbose = FALSE)
      message("  ", basename(out), ": ", k, " photos of ", name)
      written <- c(written, out)
    }
    unlink(frames_dir, recursive = TRUE)
  }
  written
}

#' A light trap's night as a video
#'
#' Every photo of the night in order, each insect boxed, moths named with the model's score, other insects
#' by their order, and a trail behind each tracked insect; optionally the insects seen on most photos,
#' each followed close up. Saved in the deployment's `videos/` folder. The same as `cehbio video`.
#' Every frame says the names are suggestions, not checked identifications.
#'
#' @param project,deployment the run
#' @param night night(s), named by the evening they start, e.g. "2026-05-11" (default: the busiest)
#' @param all_nights one video per night
#' @param individuals also follow the N insects seen on most photos, close up
#' @param tracks follow these tracks close up (e.g. "Track_000123")
#' @param fps photos per second
#' @param width video width in pixels
#' @param trail photos of trail behind each tracked insect (0: none)
#' @param min_score name moths only at or above this score
#' @param labels "species" or "none"
#' @param source_root folder(s) with copies of the photos, if they aren't where the pipeline read them
#' @param out folder for the videos
#' @return the video files, invisibly
#' @export
cehbio_video <- function(project, deployment, night = NULL, all_nights = FALSE, individuals = 0, tracks = NULL, fps = 4,
                         width = 1280, trail = 8, min_score = 0, labels = "species", source_root = NULL, out = NULL) {
  .need_video_pkgs()
  d <- .video_load(project, deployment)
  files <- d$files; boxes <- d$boxes
  key <- if (nrow(boxes)) ifelse(nzchar(boxes$track_id), boxes$track_id, paste0("box", seq_len(nrow(boxes)))) else character()
  nb <- if (nrow(boxes)) merge(data.frame(name = boxes$name, k = key), files[, c("name", "night")], by = "name") else data.frame()
  busy <- if (nrow(nb)) tapply(nb$k, nb$night, function(x) length(unique(x))) else table(files$night)
  busy <- names(busy)[order(-busy, method = "radix")]
  chosen <- if (length(night)) {
    bad <- setdiff(night, files$night)
    if (length(bad)) stop("No photos on night(s) ", paste(bad, collapse = ", "), ".", call. = FALSE)
    night
  } else if (all_nights) sort(unique(files$night)) else {
    message("The busiest night is ", busy[1], " (choose others with night =, or all_nights = TRUE).")
    busy[1]
  }
  out_dir <- out %||% file.path(d$root, "videos")
  find <- .media_finder(source_root)
  written <- character()
  for (n in chosen) {
    v <- .night_video(deployment, n, files, boxes, find, out_dir, fps, width, trail, min_score, labels)
    if (!is.null(v)) written <- c(written, v)
    if (individuals > 0 || length(tracks)) written <- c(written, .individual_videos(deployment, n, files, boxes, find, out_dir,
                                                                                    individuals, tracks = tracks))
  }
  if (length(written)) message("Videos in ", out_dir)
  invisible(written)
}

# ------------------------------------------------------------------ soundscapes
.read_clip <- function(path, start, end) {
  a <- av::read_audio_bin(path, channels = 1, start_time = start, end_time = end)
  list(a = as.numeric(a) / 2^31, sr = attr(a, "sample_rate"))
}

.spec_raster <- function(a, sr, group, width, height) {
  nfft <- if (group == "birds") 1024 else 512
  if (length(a) < nfft) a <- c(a, rep(0, nfft - length(a)))
  hop <- max(1, (length(a) - nfft) %/% max(1, width - 1))
  starts <- seq(1, length(a) - nfft + 1, by = hop)
  win <- 0.5 - 0.5 * cos(2 * pi * (0:(nfft - 1)) / (nfft - 1))
  m <- vapply(starts, function(s) a[s:(s + nfft - 1)] * win, numeric(nfft))
  p <- Mod(stats::mvfft(m))[1:(nfft / 2 + 1), , drop = FALSE]^2
  db <- 10 * log10(p + 1e-12)
  freqs <- (0:(nfft / 2)) * sr / nfft
  rng <- c(.V_RANGES[[group]][1], min(.V_RANGES[[group]][2], sr / 2))
  db <- db[freqs >= rng[1] & freqs <= rng[2], , drop = FALSE]
  db <- db[nrow(db):1, , drop = FALSE]
  q <- stats::quantile(db, c(0.2, 0.997))
  idx <- pmin(256, pmax(1, round((db - q[1]) / max(1e-6, q[2] - q[1]) * 255) + 1))
  cols <- grDevices::hcl.colors(256, "Inferno")
  ras <- matrix(cols[idx], nrow = nrow(db))
  img <- magick::image_scale(magick::image_read(grDevices::as.raster(ras)), paste0(width, "x", height, "!"))
  list(img = img, range = rng)
}

.V_W <- 1280; .V_SPEC_H <- 520; .V_TOP <- 40; .V_BOTTOM <- 64; .V_LEFT <- 56

.clip_frame <- function(spec, clip_start, clip_len, title, right, marks, group) {
  H <- .V_TOP + .V_SPEC_H + .V_BOTTOM
  img <- magick::image_composite(magick::image_blank(.V_W, H, .V_NAVY), spec$img, offset = paste0("+", .V_LEFT, "+", .V_TOP))
  lo <- spec$range[1]; hi <- spec$range[2]; sw <- .V_W - .V_LEFT
  .draw_on(img, {
    for (khz in seq(lo, hi, length.out = 5)) {
      y <- .V_TOP + .V_SPEC_H - (khz - lo) / (hi - lo) * .V_SPEC_H
      graphics::text(4, min(max(y, .V_TOP + 7), .V_TOP + .V_SPEC_H - 7), sprintf("%.0f kHz", khz / 1000), adj = c(0, 0.5), col = "white", cex = 1.05)
    }
    steps <- c(0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300)
    step <- steps[which(clip_len / steps <= 8)[1]]
    dec <- if (step < 0.1) 2 else if (step < 1) 1 else 0
    for (t in seq(ceiling(clip_start / step) * step, clip_start + clip_len + 1e-9, by = step)) {
      x <- .V_LEFT + (t - clip_start) / clip_len * sw
      graphics::segments(x, .V_TOP + .V_SPEC_H, x, .V_TOP + .V_SPEC_H + 5, col = "white")
      graphics::text(x + 2, .V_TOP + .V_SPEC_H + 12, sprintf(paste0("%.", dec, "f s"), t), adj = c(0, 0.5), col = "white", cex = 1.05)
    }
    for (m in marks) {
      x0 <- .V_LEFT + max(0, (m$start - clip_start) / clip_len) * sw
      x1 <- .V_LEFT + min(1, (m$end - clip_start) / clip_len) * sw
      if (x1 <= .V_LEFT || x0 >= .V_W) next
      col <- .colour_for(m$species)
      if (!is.null(m$low) && !is.null(m$high)) {
        y0 <- .V_TOP + .V_SPEC_H - (min(m$high, hi) - lo) / (hi - lo) * .V_SPEC_H
        y1 <- .V_TOP + .V_SPEC_H - (max(m$low, lo) - lo) / (hi - lo) * .V_SPEC_H
      } else { y0 <- .V_TOP + 2; y1 <- .V_TOP + .V_SPEC_H - 2 }
      graphics::rect(x0, y0, x1, y1, border = col, lwd = 2)
      .tab(x0 + 2, max(.V_TOP + 2, y0 + 2), m$text, col, cex = 1.15, above = FALSE)
    }
    .bar(.V_W, 0, .V_TOP, title, right, 1.4)
    .bar(.V_W, H - 30, 30, paste0(.V_CAVEAT, if (group == "bats") "  \u00b7  slowed down 10 times" else ""), "UKCEH ceh-biomonitoring", 1.05)
  })
}

.clip_marks <- function(det, key, start, end) {
  score <- intersect(c("confidence", "logit", "class_probability"), names(det))[1]
  g <- det[as.character(det$source_key) == key & det$end_time > start & det$start_time < end, , drop = FALSE]
  lapply(seq_len(nrow(g)), function(i) {
    r <- g[i, ]
    cn <- if ("common_name" %in% names(r)) r$common_name else NA
    list(start = r$start_time, end = r$end_time, species = r$species_name,
         text = paste0(if (!is.na(cn) && nzchar(cn)) paste0(cn, " ") else "", r$species_name,
                       if (!is.na(score) && !is.na(r[[score]])) sprintf(" %.2f", r[[score]]) else ""),
         low = if ("low_freq" %in% names(r) && !is.na(r$low_freq)) r$low_freq else NULL,
         high = if ("high_freq" %in% names(r) && !is.na(r$high_freq)) r$high_freq else NULL)
  })
}

.write_wav <- function(a, sr, path) {
  s <- as.integer(round(pmax(-1, pmin(1, a)) * 32767))
  con <- file(path, "wb"); on.exit(close(con))
  n <- length(s) * 2
  writeBin(charToRaw("RIFF"), con); writeBin(as.integer(36 + n), con, size = 4, endian = "little")
  writeBin(charToRaw("WAVEfmt "), con); writeBin(16L, con, size = 4, endian = "little")
  writeBin(c(1L, 1L), con, size = 2, endian = "little"); writeBin(as.integer(sr), con, size = 4, endian = "little")
  writeBin(as.integer(sr * 2), con, size = 4, endian = "little"); writeBin(c(2L, 16L), con, size = 2, endian = "little")
  writeBin(charToRaw("data"), con); writeBin(as.integer(n), con, size = 4, endian = "little")
  writeBin(s, con, size = 2, endian = "little")
}

.render_clips <- function(clips, out, group, fps = 20) {
  slow <- .V_SLOW[[group]]
  sr <- clips[[1]]$sr
  frames_dir <- tempfile("cehbio_frames_"); dir.create(frames_dir)
  on.exit(unlink(frames_dir, recursive = TRUE), add = TRUE)
  audio <- numeric(); k <- 0; frames <- character()
  line <- magick::image_blank(2, .V_SPEC_H, "white")
  for (cl in clips) {
    a <- cl$a
    if (cl$sr != sr) a <- stats::approx(seq_along(a), a, n = round(length(a) * sr / cl$sr))$y
    nf <- min(length(a) %/% 2, round(sr * 0.02))
    if (nf > 0) { ramp <- seq(0, 1, length.out = nf); a[1:nf] <- a[1:nf] * ramp; a[(length(a) - nf + 1):length(a)] <- a[(length(a) - nf + 1):length(a)] * rev(ramp) }
    gap <- rep(0, round(0.4 * sr / slow))
    audio <- c(audio, a, gap)
    n <- max(1, round(length(a) / sr * slow * fps))
    # the playhead at up to 60 places per clip, each image used for several frames: saving every frame
    # as an image would be far slower in R, and 60 steps still move smoothly
    steps <- min(n, 60)
    pos <- character(steps)
    for (s in seq_len(steps)) {
      x <- .V_LEFT + floor((s - 0.5) / steps * (.V_W - .V_LEFT)) - 1
      k <- k + 1
      pos[s] <- file.path(frames_dir, sprintf("f%06d.jpg", k))
      magick::image_write(magick::image_composite(cl$frame, line, offset = paste0("+", x, "+", .V_TOP)), pos[s],
                          format = "jpeg", quality = 92)
    }
    k <- k + 1
    still <- file.path(frames_dir, sprintf("f%06d.jpg", k))
    magick::image_write(cl$frame, still, format = "jpeg", quality = 92)
    frames <- c(frames, pos[pmin(steps, ceiling(seq_len(n) / n * steps))],
                rep(still, round(length(gap) / sr * slow * fps)))
  }
  audio <- audio / max(1e-9, max(abs(audio))) * 0.9
  rate <- round(sr / slow)
  if (!rate %in% c(8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000)) {
    audio <- stats::approx(seq_along(audio), audio, n = round(length(audio) * 48000 / rate))$y
    rate <- 48000
  }
  wav <- file.path(frames_dir, "sound.wav")
  .write_wav(audio, rate, wav)
  dir.create(dirname(out), recursive = TRUE, showWarnings = FALSE)
  av::av_encode_video(frames, out, framerate = fps, audio = wav, verbose = FALSE)
  out
}

.overview_png <- function(det, ev, day, group, find, out, deployment) {
  recs <- ev[ev$period == day, , drop = FALSE]
  recs <- recs[!duplicated(recs$source_key), c("source_key", "when")]
  recs <- recs[order(recs$when), , drop = FALSE]
  cols <- list(); xs <- numeric()
  for (i in seq_len(nrow(recs))) {
    path <- find(recs$source_key[i])
    if (is.na(path)) next
    info <- av::av_media_info(path)
    for (t0 in seq(0, max(0, info$duration - 0.5), by = 30)) {
      cl <- tryCatch(.read_clip(path, t0, min(info$duration, t0 + 2)), error = function(e) NULL)
      if (is.null(cl) || length(cl$a) < 1024) next
      nfft <- if (group == "birds") 1024 else 512
      starts <- seq(1, length(cl$a) - nfft + 1, by = 512)
      m <- vapply(starts, function(s) cl$a[s:(s + nfft - 1)], numeric(nfft))
      p <- rowMeans(10 * log10(Mod(stats::mvfft(m))[1:(nfft / 2 + 1), , drop = FALSE]^2 + 1e-12))
      fr <- (0:(nfft / 2)) * cl$sr / nfft
      rng <- c(.V_RANGES[[group]][1], min(.V_RANGES[[group]][2], cl$sr / 2))
      p <- p[fr >= rng[1] & fr <= rng[2]]
      cols[[length(cols) + 1]] <- stats::approx(seq_along(p), p, n = 160)$y
      xs <- c(xs, as.numeric(recs$when[i]) + t0)
    }
  }
  if (!length(cols)) return(NULL)
  m <- do.call(cbind, cols)
  dir.create(dirname(out), recursive = TRUE, showWarnings = FALSE)
  grDevices::png(out, width = 1540, height = 550, res = 110)
  on.exit(grDevices::dev.off())
  graphics::par(mar = c(3, 4, 2.5, 14), family = "sans")
  q <- stats::quantile(m, c(0.05, 0.995))
  ytop <- rng[2] / 1000
  o <- order(xs)
  graphics::image(.ct(xs[o]), seq(rng[1], rng[2], length.out = 160) / 1000, t(m[, o, drop = FALSE]), col = grDevices::hcl.colors(256, "Inferno"),
                  zlim = q, xlab = "", ylab = "pitch (kHz)", useRaster = TRUE, xaxt = "n")
  graphics::axis.POSIXct(1, .ct(xs), format = "%H:%M")
  e <- ev[ev$period == day, , drop = FALSE]
  top <- utils::head(names(sort(table(e$species), decreasing = TRUE)), 8)
  for (i in seq_along(top)) {
    g <- e[e$species == top[i], , drop = FALSE]
    graphics::points(.ct(as.numeric(g$when) + g$peak_s), rep(ytop * (0.97 - 0.035 * (i - 1)), nrow(g)), pch = 21,
                     bg = .colour_for(top[i]), col = "black", cex = 0.9)
  }
  graphics::title(sprintf("%s, %s: the sound through the %s, with what the model suggested (not checked)", deployment, day,
                          if (group == "birds") "day" else "night"), adj = 0, cex.main = 0.95, font.main = 1)
  if (length(top)) graphics::legend(graphics::par("usr")[2], graphics::par("usr")[4], xpd = TRUE, bty = "n", cex = 0.75, pch = 21,
                                    pt.bg = vapply(top, .colour_for, ""), legend = sprintf("%s (%d)", top, as.integer(table(e$species)[top])),
                                    title = "commonest suggestions")
  out
}

#' A day of bird song, or a night of bats, to watch and listen to
#'
#' The best moment for each species the model found (up to `highlights`), in time order, each a short clip
#' with its sound and a moving spectrogram, the detections marked and named with their scores; and, for
#' birds, a picture of the whole day. Bats are slowed down ten times so they can be heard. Or one whole
#' `recording`. Saved in the deployment's `videos/` folder. The same as `cehbio soundscape`.
#'
#' @param pipeline "birds" or "bats"
#' @param project,deployment the run
#' @param day the day (birds) or night (bats), e.g. "2026-05-11" (default: the one with most species)
#' @param recording one whole recording instead (its file name)
#' @param highlights how many species' best moments
#' @param length seconds of video per highlight (default 10)
#' @param min_score only detections at or above this score
#' @param overview also the whole-day picture (default: birds yes, bats no)
#' @param max_seconds `recording`: at most this much
#' @param source_root folder(s) with copies of the recordings, if they aren't where the pipeline read them
#' @param out folder for the videos
#' @return the files made, invisibly
#' @export
cehbio_soundscape <- function(pipeline, project, deployment, day = NULL, recording = NULL, highlights = 12, length = NULL,
                              min_score = NULL, overview = NULL, max_seconds = 300, source_root = NULL, out = NULL) {
  .need_video_pkgs()
  pipeline <- match.arg(pipeline, c("birds", "bats"))
  root <- file.path(results_folder(), pipeline, project, deployment)
  if (!dir.exists(root)) root <- file.path(results_folder(), pipeline, project, "inference", deployment)
  f <- file.path(root, paste0(deployment, "_detections.parquet"))
  if (!file.exists(f)) stop("No results for ", deployment, " in ", root, ".", call. = FALSE)
  det <- .read_any(f)
  ev <- .audio_units(det, pipeline)
  if (is.null(ev) || !nrow(ev)) stop("Nothing was detected in ", deployment, "'s recordings, so there's nothing to show.", call. = FALSE)
  ev$period <- if (pipeline == "birds") format(ev$when, "%Y-%m-%d", tz = "UTC") else .night_of(ev$when)
  ev <- ev[!is.na(ev$period), , drop = FALSE]
  out_dir <- out %||% file.path(root, "videos")
  find <- .media_finder(source_root)
  clip_s <- if (!is.null(length)) length / .V_SLOW[[pipeline]] else .V_CLIP[[pipeline]]
  if (!is.null(recording)) {
    keys <- as.character(det$source_key)
    key <- keys[tolower(basename(gsub("\\\\", "/", keys))) == tolower(basename(recording))][1]
    if (is.na(key)) stop("No recording called ", recording, " in ", deployment, "'s results.", call. = FALSE)
    path <- find(key)
    if (is.na(path)) stop(recording, " isn't on this computer: give source_root.", call. = FALSE)
    cl <- .read_clip(path, 0, max_seconds)
    len <- base::length(cl$a) / cl$sr
    spec <- .spec_raster(cl$a, cl$sr, pipeline, .V_W - .V_LEFT, .V_SPEC_H)
    fr <- .clip_frame(spec, 0, len, paste0(deployment, "  \u00b7  ", basename(key)), sprintf("%.0f s", len),
                      .clip_marks(det, key, 0, len), pipeline)
    o <- .render_clips(list(list(a = cl$a, sr = cl$sr, frame = fr)),
                       file.path(out_dir, sprintf("%s_%s_soundscape.mp4", deployment, tools::file_path_sans_ext(basename(key)))), pipeline)
    message("  ", basename(o))
    return(invisible(o))
  }
  days <- tapply(ev$species, ev$period, function(x) base::length(unique(x)))
  days <- names(days)[order(-days, method = "radix")]
  if (is.null(day)) {
    day <- days[1]
    message("The ", if (pipeline == "birds") "day" else "night", " with most species is ", day, " (choose another with day =).")
  } else if (!day %in% days) stop("Nothing detected on ", day, ". With detections: ", paste(sort(days), collapse = ", "), call. = FALSE)
  e <- ev[ev$period == day, , drop = FALSE]
  if (!is.null(min_score)) e <- e[!is.na(e$score) & e$score >= min_score, , drop = FALSE]
  e <- e[order(-ifelse(is.na(e$score), -Inf, e$score), method = "radix"), , drop = FALSE]
  e <- utils::head(e[!duplicated(e$species), , drop = FALSE], highlights)
  e <- e[order(e$when, e$peak_s), , drop = FALSE]
  clips <- list()
  for (i in seq_len(nrow(e))) {
    r <- e[i, ]
    path <- find(r$source_key)
    if (is.na(path)) { message("  skipped ", r$species, ": not on this computer"); next }
    mid <- r$peak_s + (r$window_s %||% 0) / 2
    start <- max(0, mid - clip_s / 2)
    cl <- .read_clip(path, start, start + clip_s)
    len <- base::length(cl$a) / cl$sr
    spec <- .spec_raster(cl$a, cl$sr, pipeline, .V_W - .V_LEFT, .V_SPEC_H)
    cn <- if ("common_name" %in% names(r)) r$common_name else NA
    title <- paste0(deployment, "  \u00b7  ", format(r$when + start, "%Y-%m-%d %H:%M:%S", tz = "UTC"), "  \u00b7  ",
                    if (!is.na(cn) && nzchar(cn)) paste0(cn, " (", r$species, ")") else r$species)
    clips[[base::length(clips) + 1]] <- list(a = cl$a, sr = cl$sr, frame = .clip_frame(
      spec, start, len, title, sprintf("score %.2f", r$score), .clip_marks(det, as.character(r$source_key), start, start + len), pipeline))
  }
  if (!base::length(clips)) stop("None of the recordings could be found: give source_root.", call. = FALSE)
  o <- .render_clips(clips, file.path(out_dir, sprintf("%s_%s_soundscape.mp4", deployment, day)), pipeline)
  message("  ", basename(o), ": ", base::length(clips), " highlights")
  written <- o
  if (if (is.null(overview)) pipeline == "birds" else overview) {
    p <- .overview_png(det, ev, day, pipeline, find, file.path(out_dir, sprintf("%s_%s_overview.png", deployment, day)), deployment)
    if (!is.null(p)) { message("  ", basename(p)); written <- c(written, p) }
  }
  message("In ", out_dir)
  invisible(written)
}
