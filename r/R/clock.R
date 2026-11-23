# What time a light trap's clock kept, from when it started and stopped each night: the R twin of the
# toolkit's clockcheck.py (same rules, same words). Used by the report tables when a site has a time zone
# but no clock was given. Times are never changed: this only decides which clock to read them by.

.START_EARLIEST_H <- -1.0
.START_LATEST_H <- 1.5
.STOPPED_EARLY_H <- 1.5
.JUMP_MIN <- 40
.FOLLOWS_DUSK_IQR_MIN <- 45

.q <- function(x, p) unname(stats::quantile(x, p, type = 7, na.rm = TRUE))
.spread <- function(x) (.q(x, 0.75) - .q(x, 0.25)) * 60

.mins <- function(h) {
  m <- round(h * 60)
  if (m == 0) "at" else paste0(abs(m), " min ", if (m > 0) "after" else "before")
}
.fmt_utc <- function(h) {
  sign <- if (h >= 0) "+" else "-"
  h <- abs(h)
  paste0("UTC", sign, as.integer(h), if (h %% 1) sprintf(":%02d", round((h %% 1) * 60)) else "")
}
.fixed <- function(spread_min) paste0("the first photos don't follow dusk (they wander by about ", round(spread_min),
                                      " min), so the trap probably runs on a fixed schedule: its clock can't be told from this")

# hours a time zone is ahead of UTC at 22:00 local on a day
.utc_offset_h <- function(day, tz) {
  x <- as.POSIXct(paste(format(as.Date(day)), "22:00:00"), tz = tz)
  (as.numeric(as.POSIXct(format(x, "%Y-%m-%d %H:%M:%S"), tz = "UTC")) - as.numeric(x)) / 3600
}

.spells <- function(t) {
  t <- sort(t[!is.na(t)])
  if (!length(t)) return(data.frame(first = .ct(numeric()), last = .ct(numeric()), files = integer()))
  spell <- cumsum(c(FALSE, diff(as.numeric(t)) > 3 * 3600))
  data.frame(first = .ct(tapply(as.numeric(t), spell, min)), last = .ct(tapply(as.numeric(t), spell, max)),
             files = as.integer(tabulate(spell + 1)))
}

.roll_median <- function(x, k = 5, min_n = 3) {
  n <- length(x)
  h <- k %/% 2
  vapply(seq_len(n), function(i) {
    w <- x[max(1, i - h):min(n, i + h)]
    w <- w[!is.na(w)]
    if (length(w) >= min_n) stats::median(w) else NA_real_
  }, 0)
}

# The clock verdict (a list with clock and verdict), as clockcheck.check.
.clock_check <- function(times, lat, lon, tz = NULL, min_files = 5) {
  n <- .spells(times)
  n <- n[n$files >= min_files, , drop = FALSE]
  if (!nrow(n)) return(list(verdict = "not enough nights with photos to tell"))
  rows <- lapply(seq_len(nrow(n)), function(i) {
    first <- n$first[i]
    last <- n$last[i]
    night <- as.Date(format(first, "%Y-%m-%d", tz = "UTC"))
    dusks <- do.call(c, lapply(-1:1, function(k) .sun_time(night + k, lat, lon, FALSE)))
    dawns <- do.call(c, lapply(0:2, function(k) .sun_time(night + k, lat, lon, TRUE)))
    dusks <- dusks[!is.na(dusks)]
    dawns <- dawns[!is.na(dawns)]
    dusk <- if (length(dusks)) dusks[which.min(abs(as.numeric(first) - as.numeric(dusks)))] else NA
    dawn <- if (length(dawns)) dawns[which.min(abs(as.numeric(last) - as.numeric(dawns)))] else NA
    if (!is.na(dusk)) night <- as.Date(format(dusk, "%Y-%m-%d", tz = "UTC"))
    data.frame(night = format(night),
               gap = if (is.na(dusk)) NA_real_ else round((as.numeric(first) - as.numeric(dusk)) / 3600, 2),
               end = if (is.na(dawn)) NA_real_ else round((as.numeric(last) - as.numeric(dawn)) / 3600, 2),
               local = if (is.null(tz)) NA_real_ else .utc_offset_h(night, tz))
  })
  t <- do.call(rbind, rows)
  if (all(is.na(t$gap))) return(list(verdict = "no dusk at this latitude on these dates: can't tell"))
  night_ok <- !(abs(t$gap - stats::median(t$gap, na.rm = TRUE)) > 3) | is.na(t$gap)
  gi <- which(night_ok & !is.na(t$gap))
  gap <- t$gap[gi]
  out <- list(n_nights = length(gap))
  local <- if (!is.null(tz)) t$local[gi] else NULL
  changes <- !is.null(tz) && length(unique(local)) > 1
  if (changes) {
    s_utc <- .spread(gap)
    s_local <- .spread(gap - local)
    if (min(s_utc, s_local) > .FOLLOWS_DUSK_IQR_MIN) {
      out$verdict <- .fixed(min(s_utc, s_local))
    } else if (s_local < s_utc) {
      d <- stats::median(gap - local)
      if (d >= .START_EARLIEST_H && d <= .START_LATEST_H) {
        out$clock <- "local"
        out$verdict <- paste0("the clock keeps local time (", tz, "), changing with the clocks: the first photos keep ",
                              "step with dusk in local time across the change, starting ", .mins(d), " civil dusk")
      } else {
        out$clock <- sprintf("local %+d h", as.integer(round(d)))
        out$verdict <- paste0("the clock changes with the clocks (", tz, ") but is about ", abs(round(d)), " h ",
                              if (d > 0) "ahead" else "behind", ", if the unit starts near dusk: it was probably set wrongly")
      }
    } else {
      g <- stats::median(gap)
      if (g >= .START_EARLIEST_H && g <= .START_LATEST_H) {
        out$clock <- "UTC"
        out$verdict <- paste0("the clock keeps UTC: the first photos keep step with dusk in UTC across the change of ",
                              "the clocks, starting ", .mins(g), " civil dusk")
      } else {
        out$clock <- .fmt_utc(round(g))
        out$verdict <- paste0("the clock is about ", .fmt_utc(round(g)), " (it doesn't change with the clocks), if the ",
                              "unit starts near dusk: that's neither UTC nor local time (", tz, "). It was probably set ",
                              "up somewhere else, or set wrongly")
      }
    }
  } else if (.spread(gap) > .FOLLOWS_DUSK_IQR_MIN) {
    out$verdict <- .fixed(.spread(gap))
  } else {
    g <- stats::median(gap)
    cands <- c(UTC = 0)
    if (!is.null(tz) && local[1] != 0) cands[paste0("local time (", tz, ", ", .fmt_utc(local[1]), ")")] <- local[1]
    d <- g - cands
    fits <- d[d >= .START_EARLIEST_H & d <= .START_LATEST_H]
    if (length(fits) == 1) {
      out$clock <- if (names(fits) == "UTC") "UTC" else "local"
      out$verdict <- paste0("the clock keeps ", names(fits), ": the unit starts ", .mins(fits[[1]]), " civil dusk")
    } else if (length(fits) > 1) {
      out$verdict <- paste0("the first photos follow dusk closely, but these nights can't tell which clock: ",
                            paste0("if it keeps ", names(fits), ", the unit starts ", vapply(fits, .mins, ""), " civil dusk",
                                   collapse = "; or "),
                            ". The nights don't cross a change of the clocks, which would settle it. Check one photo ",
                            "against a known time instead (when the unit was switched on, or a photo of a phone's clock)")
    } else {
      out$clock <- .fmt_utc(round(g))
      out$verdict <- paste0("the clock is about ", .fmt_utc(round(g)), ", if the unit starts near dusk: that's neither ",
                            "UTC nor local time", if (!is.null(tz)) paste0(" (", tz, ")") else "",
                            ". It was probably set up somewhere else, or set wrongly")
    }
    if (is.null(tz) && identical(out$clock, "UTC")) out$verdict <- paste0(out$verdict, ". Give --timezone to check it against local time too")
  }
  out
}
