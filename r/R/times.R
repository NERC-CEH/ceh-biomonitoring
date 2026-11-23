# Dates and times, whatever form they come in: the R twin of the toolkit's times.py, so R and Python read
# every result the same way. Times are the LOCAL CLOCK as written (a time zone, when there is one, is
# dropped, not converted). In R they are POSIXct marked "UTC" only so that nothing shifts them.

.YEARS <- c(1990, 2100)
.NAME_RX <- c("(?<!\\d)(\\d{4})[-_](\\d{2})[-_](\\d{2})[T _-](\\d{2})[-_:.](\\d{2})[-_:.](\\d{2})(?!\\d)",
              "(?<!\\d)(\\d{4})(\\d{2})(\\d{2})[T_-]?(\\d{2})(\\d{2})(\\d{2})(?!\\d)")
.DATE_RX <- c("(?<!\\d)(\\d{4})-(\\d{2})-(\\d{2})(?!\\d)", "(?<!\\d)(\\d{4})(\\d{2})(\\d{2})(?!\\d)",
              "(?<!\\d)(\\d{4})_(\\d{2})_(\\d{2})(?!\\d)")

.ct <- function(x) as.POSIXct(x, tz = "UTC")
.na_time <- function(n = 1) .ct(rep(NA_real_, n))

.ok_parts <- function(p) {          # year, month, day, (hour, min, sec): a real date in range
  p <- as.integer(p)
  if (p[1] < .YEARS[1] || p[1] > .YEARS[2] || p[2] < 1 || p[2] > 12 || p[3] < 1) return(FALSE)
  d <- suppressWarnings(as.Date(sprintf("%04d-%02d-%02d", p[1], p[2], p[3])))
  if (is.na(d) || as.integer(format(d, "%d")) != p[3]) return(FALSE)
  if (length(p) > 3 && (p[4] > 23 || p[5] > 59 || p[6] > 59)) return(FALSE)
  TRUE
}

.match_parts <- function(name, rx) {
  m <- regmatches(name, gregexpr(rx, name, perl = TRUE))[[1]]
  lapply(m, function(s) regmatches(s, regexec(rx, s, perl = TRUE))[[1]][-1])
}

# the date and time in one file name, as "YYYY-MM-DD HH:MM:SS", or NA
.name_time1 <- function(name) {
  name <- basename(gsub("\\\\", "/", name))
  for (rx in .NAME_RX) for (p in .match_parts(name, rx)) {
    if (.ok_parts(p)) return(do.call(sprintf, c(list("%s-%s-%s %s:%s:%s"), as.list(p))))
  }
  NA_character_
}

.name_date1 <- function(name) {
  t <- .name_time1(name)
  if (!is.na(t)) return(substr(t, 1, 10))
  name <- basename(gsub("\\\\", "/", name))
  for (rx in .DATE_RX) for (p in .match_parts(name, rx)) if (.ok_parts(p)) return(paste(p, collapse = "-"))
  NA_character_
}

#' Times in file names
#'
#' The date and time in file names, as the pipelines read them (e.g. `20240725204340-snapshot.jpg`,
#' `SMA01234_20240705_043000.wav`, `ami-mini-20250428T210338.jpg`): the device's own clock.
#' @param names file names or paths
#' @param date_only_ok when a name has a date but no time, give midnight on that date
#' @return POSIXct (marked UTC, meaning "as on the clock"), NA where there is none
#' @export
time_from_name <- function(names, date_only_ok = FALSE) {
  u <- unique(as.character(names))
  v <- vapply(u, .name_time1, "")
  if (date_only_ok) {
    miss <- is.na(v)
    v[miss] <- vapply(u[miss], function(n) { d <- .name_date1(n); if (is.na(d)) NA_character_ else paste(d, "00:00:00") }, "")
  }
  .ct(v[match(as.character(names), u)])
}

# Any column of times -> clock times (NA where it can't be read). As times.parse.
.parse_times <- function(x) {
  if (inherits(x, "POSIXct")) return(.ct(format(x, "%Y-%m-%d %H:%M:%OS6", tz = attr(x, "tzone") %||% "")))
  if (inherits(x, "Date")) return(.ct(paste(format(x), "00:00:00")))
  if (is.factor(x)) x <- as.character(x)
  if (is.numeric(x)) {
    n <- ifelse(abs(x) > 1e11, x / 1000, x)
    out <- .ct(n)
    out[is.na(x) | x == 0] <- NA
  } else {
    s <- trimws(as.character(x))
    s[is.na(s) | tolower(s) %in% c("", "nan", "nat", "none", "null")] <- NA
    s <- sub("^(\\d{4}):(\\d{2}):(\\d{2})", "\\1-\\2-\\3", s)                       # EXIF
    s <- sub("^(\\d{4})(\\d{2})(\\d{2})(\\d{2})(\\d{2})(\\d{2})$", "\\1-\\2-\\3 \\4:\\5:\\6", s)
    s <- trimws(sub("(Z|[+-]\\d{2}:?\\d{2})$", "", s))                              # time zone dropped
    s <- sub("T", " ", s, fixed = TRUE)
    out <- .na_time(length(s))
    for (f in c("%Y-%m-%d %H:%M:%OS", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%OS", "%d/%m/%Y %H:%M:%OS")) {
      todo <- is.na(out) & !is.na(s)
      if (!any(todo)) break
      out[todo] <- as.POSIXct(s[todo], format = f, tz = "UTC")
    }
  }
  y <- as.integer(format(out, "%Y"))
  out[!is.na(y) & (y < .YEARS[1] | y > .YEARS[2])] <- NA
  out
}

# Times from a results column, falling back to the file name. As times.best: the results win.
.best_times <- function(column, names) {
  from_file <- time_from_name(names)
  col <- if (is.null(column)) .na_time(length(names)) else .parse_times(column)
  both <- !is.na(col) & !is.na(from_file)
  off <- both & abs(as.numeric(col) - as.numeric(from_file)) > 60
  when <- col
  when[is.na(when)] <- from_file[is.na(when)]
  src <- rep("unknown", length(names))
  src[!is.na(from_file)] <- "file name"
  src[!is.na(col)] <- "results"
  list(when = when, source = src, disagree = length(unique(names[off])))
}

# The night (noon to noon on the device's clock), named by its evening, as text.
.night_of <- function(t) format(t - 12 * 3600, "%Y-%m-%d", tz = "UTC")

# Python's str() of a number, so ids made from numbers are the same in R and Python.
.py_num <- function(x) {
  vapply(as.numeric(x), function(v) {
    if (is.na(v)) return("nan")
    if (v == trunc(v) && abs(v) < 1e16) return(sprintf("%.1f", v))
    for (d in 1:17) { s <- formatC(v, digits = d, format = "g"); if (as.numeric(s) == v) break }
    s <- sub("e([+-])0?(\\d)", "e\\1\\2", s)
    if (grepl("e", s) && abs(v) >= 1e-4 && abs(v) < 1e16) s <- format(v, digits = d, scientific = FALSE)
    if (grepl("e", s)) s <- sub("e([+-])(\\d)$", "e\\10\\2", s)
    s
  }, "")
}

.sha20 <- function(keys) vapply(keys, function(k) substr(digest::digest(enc2utf8(k), algo = "sha256", serialize = FALSE), 1, 20),
                                "", USE.NAMES = FALSE)
