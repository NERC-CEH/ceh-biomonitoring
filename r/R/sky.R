# The moon and the sun: the R twins of the toolkit's sky.py (Schlyter's low-precision method, about a
# degree) and clockcheck.py's civil dusk and dawn (NOAA's almanac method). All times UTC.

.RAD <- pi / 180
.rev <- function(x) x %% 360
.days <- function(t) (as.numeric(t) - as.numeric(as.POSIXct("1999-12-31", tz = "UTC"))) / 86400

.sun_ecl <- function(d) {
  w <- 282.9404 + 4.70935e-5 * d
  e <- 0.016709 - 1.151e-9 * d
  M <- .rev(356.0470 + 0.9856002585 * d)
  E <- M + e / .RAD * sin(M * .RAD) * (1 + e * cos(M * .RAD))
  x <- cos(E * .RAD) - e
  y <- sin(E * .RAD) * sqrt(1 - e * e)
  v <- atan2(y, x) / .RAD
  c(lon = .rev(v + w), mean = .rev(M + w))
}

.moon_ecl <- function(d) {
  N <- .rev(125.1228 - 0.0529538083 * d)
  i <- 5.1454
  w <- .rev(318.0634 + 0.1643573223 * d)
  a <- 60.2666
  e <- 0.054900
  M <- .rev(115.3654 + 13.0649929509 * d)
  E <- M + e / .RAD * sin(M * .RAD) * (1 + e * cos(M * .RAD))
  for (k in 1:3) E <- E - (E - e / .RAD * sin(E * .RAD) - M) / (1 - e * cos(E * .RAD))
  x <- a * (cos(E * .RAD) - e)
  y <- a * sqrt(1 - e * e) * sin(E * .RAD)
  r <- sqrt(x^2 + y^2)
  v <- atan2(y, x) / .RAD
  xe <- r * (cos(N * .RAD) * cos((v + w) * .RAD) - sin(N * .RAD) * sin((v + w) * .RAD) * cos(i * .RAD))
  ye <- r * (sin(N * .RAD) * cos((v + w) * .RAD) + cos(N * .RAD) * sin((v + w) * .RAD) * cos(i * .RAD))
  ze <- r * sin((v + w) * .RAD) * sin(i * .RAD)
  lon <- .rev(atan2(ye, xe) / .RAD)
  lat <- atan2(ze, sqrt(xe^2 + ye^2)) / .RAD
  Ls <- .sun_ecl(d)[["mean"]]
  Ms <- .rev(356.0470 + 0.9856002585 * d)
  Lm <- .rev(N + w + M)
  D <- .rev(Lm - Ls)
  F <- .rev(Lm - N)
  lon <- lon + (-1.274 * sin((M - 2 * D) * .RAD) + 0.658 * sin(2 * D * .RAD) - 0.186 * sin(Ms * .RAD)
                - 0.059 * sin((2 * M - 2 * D) * .RAD) - 0.057 * sin((M - 2 * D + Ms) * .RAD)
                + 0.053 * sin((M + 2 * D) * .RAD) + 0.046 * sin((2 * D - Ms) * .RAD)
                + 0.041 * sin((M - Ms) * .RAD) - 0.035 * sin(D * .RAD))
  lat <- lat - 0.173 * sin((F - 2 * D) * .RAD) - 0.055 * sin((M - F - 2 * D) * .RAD)
  c(lon = .rev(lon), lat = lat)
}

#' How full the moon is
#' @param t times (POSIXct, UTC)
#' @return the fraction of the disc lit, 0 (new) to 1 (full)
#' @export
moon_illumination <- function(t) {
  vapply(.days(t), function(d) {
    s <- .sun_ecl(d)[["lon"]]
    m <- .moon_ecl(d)
    elong <- acos(cos((m[["lon"]] - s) * .RAD) * cos(m[["lat"]] * .RAD))
    (1 - cos(elong)) / 2
  }, 0)
}

#' How high the moon is
#' @param t times (POSIXct, UTC)
#' @param lat,lon the place
#' @return degrees above the horizon (negative = below)
#' @export
moon_altitude <- function(t, lat, lon) {
  t <- .ct(t)
  ut <- as.numeric(format(t, "%H", tz = "UTC")) + (as.numeric(format(t, "%M", tz = "UTC")) +
                                                      as.numeric(format(t, "%OS", tz = "UTC")) %/% 1 / 60) / 60
  mapply(function(d, u) {
    m <- .moon_ecl(d)
    ecl <- 23.4393 - 3.563e-7 * d
    xe <- cos(m[["lon"]] * .RAD) * cos(m[["lat"]] * .RAD)
    ye <- sin(m[["lon"]] * .RAD) * cos(m[["lat"]] * .RAD)
    ze <- sin(m[["lat"]] * .RAD)
    yq <- ye * cos(ecl * .RAD) - ze * sin(ecl * .RAD)
    zq <- ye * sin(ecl * .RAD) + ze * cos(ecl * .RAD)
    ra <- atan2(yq, xe) / .RAD
    dec <- atan2(zq, sqrt(xe^2 + yq^2)) / .RAD
    lst <- .rev(.sun_ecl(d)[["mean"]] + 180 + u * 15 + lon)
    ha <- (lst - ra) * .RAD
    alt <- asin(sin(lat * .RAD) * sin(dec * .RAD) + cos(lat * .RAD) * cos(dec * .RAD) * cos(ha))
    alt / .RAD - 0.95 * cos(alt)
  }, .days(t), ut)
}

.moon_over <- function(start, end, lat, lon, step_min = 15) {
  mid <- start + (as.numeric(end) - as.numeric(start)) / 2
  n <- max(1, (as.numeric(end) - as.numeric(start)) %/% (step_min * 60))
  up <- sum(moon_altitude(start + step_min * 60 * (0:n), lat, lon) > 0)
  c(moon_illumination = round(moon_illumination(mid), 3), moon_up_share = round(up / (n + 1), 3))
}

# UTC time the sun crosses `zenith` on a day (morning if rising), or NA. As clockcheck.sun_time.
.sun_time <- function(day, lat, lon, rising, zenith = 96) {
  day <- as.Date(day)
  n <- as.integer(format(day, "%j"))
  lng_hour <- lon / 15
  t <- n + ((if (rising) 6 else 18) - lng_hour) / 24
  m <- 0.9856 * t - 3.289
  L <- (m + 1.916 * sin(m * .RAD) + 0.020 * sin(2 * m * .RAD) + 282.634) %% 360
  ra <- (atan(0.91764 * tan(L * .RAD)) / .RAD) %% 360
  ra <- (ra + (floor(L / 90) * 90 - floor(ra / 90) * 90)) / 15
  sin_dec <- 0.39782 * sin(L * .RAD)
  cos_dec <- cos(asin(sin_dec))
  cos_h <- (cos(zenith * .RAD) - sin_dec * sin(lat * .RAD)) / (cos_dec * cos(lat * .RAD))
  if (cos_h < -1 || cos_h > 1) return(.na_time())
  h <- (if (rising) 360 - acos(cos_h) / .RAD else acos(cos_h) / .RAD) / 15
  ut <- (h + ra - 0.06571 * t - 6.622 - lng_hour) %% 24
  .ct(paste(format(day), "00:00:00")) + ut * 3600
}
