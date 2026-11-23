# Hourly weather at a site, summarised over the hours a device was working: the R twin of the toolkit's
# weather.py. Two sources:
#   open-meteo  (default) Open-Meteo's historical weather: from 2022 the finest model for the place (in the
#               UK the Met Office's 2 km model), earlier ERA5. Non-commercial use only; CC BY 4.0.
#   era5-land   ERA5-Land (Copernicus): about 9 km, any use including commercial, with credit. Needs a free
#               CDS key, as "CDSAPI_KEY" in your credentials file.
# Hourly values are cached (in the same folder as the Python toolkit's), so a report doesn't ask twice.

.WEATHER_SOURCES <- list(
  "open-meteo" = list(licence = "CC BY 4.0; free API for non-commercial use only",
                      credit = "Weather data by Open-Meteo.com (Met Office, ECMWF and other national weather services)",
                      commercial = FALSE),
  "era5-land" = list(licence = "Copernicus licence: free for any use, commercial included, with credit",
                     credit = "Contains modified Copernicus Climate Change Service information (ERA5-Land, ECMWF)",
                     commercial = TRUE))

.config_dir <- function() Sys.getenv("CEHBIO_CONFIG_DIR", file.path(.user_home(), ".config", "ceh-biomonitoring"))
.user_home <- function() if (.Platform$OS.type == "windows") Sys.getenv("USERPROFILE") else path.expand("~")

.weather_cache <- function() {
  d <- file.path(.setting("cache_dir", file.path(.user_home(), ".cache", "ceh-biomonitoring", "models")), "weather")
  dir.create(d, recursive = TRUE, showWarnings = FALSE)
  d
}

.http_json <- function(url) {
  h <- curl::new_handle(useragent = "ceh-biomonitoring", timeout = 120)
  if (.Platform$OS.type == "windows") curl::handle_setopt(h, ssl_options = 2)
  r <- curl::curl_fetch_memory(url, handle = h)
  if (r$status_code != 200) stop("HTTP ", r$status_code, " from ", sub("\\?.*", "", url))
  jsonlite::fromJSON(rawToChar(r$content), simplifyVector = TRUE)
}

.open_meteo <- function(lat, lon, start, end) {
  spans <- list()
  if (start < as.Date("2022-01-01"))
    spans[[length(spans) + 1]] <- list("https://archive-api.open-meteo.com/v1/archive", start, min(end, as.Date("2021-12-31")), "era5")
  if (end >= as.Date("2022-01-01"))
    spans[[length(spans) + 1]] <- list("https://historical-forecast-api.open-meteo.com/v1/forecast",
                                       max(start, as.Date("2022-01-01")), end, "best_match")
  parts <- lapply(spans, function(s) {
    q <- paste0(s[[1]], "?latitude=", round(lat, 4), "&longitude=", round(lon, 4), "&start_date=", s[[2]],
                "&end_date=", s[[3]], "&hourly=temperature_2m%2Cprecipitation%2Cwind_speed_10m%2Ccloud_cover%2Crelative_humidity_2m",
                "&timezone=GMT&wind_speed_unit=ms&models=", s[[4]])
    h <- .http_json(q)$hourly
    if (is.null(h$time) || !length(h$time)) return(NULL)
    num <- function(v) if (is.null(v)) rep(NA_real_, length(h$time)) else as.numeric(v)
    data.frame(time_utc = as.POSIXct(h$time, format = "%Y-%m-%dT%H:%M", tz = "UTC"),
               temperature_c = num(h$temperature_2m), precipitation_mm = num(h$precipitation),
               wind_speed_ms = num(h$wind_speed_10m), cloud_cover_pct = num(h$cloud_cover),
               relative_humidity_pct = num(h$relative_humidity_2m), weather_model = s[[4]])
  })
  do.call(rbind, parts)
}

# ERA5-Land point time series through the Copernicus CDS API (submit, wait, download).
.era5_land <- function(lat, lon, start, end, key) {
  api <- "https://cds.climate.copernicus.eu/api/retrieve/v1/processes/reanalysis-era5-land-timeseries/execution"
  body <- jsonlite::toJSON(list(inputs = list(
    variable = c("2m_temperature", "2m_dewpoint_temperature", "total_precipitation",
                 "10m_u_component_of_wind", "10m_v_component_of_wind"),
    location = list(longitude = round(lon, 3), latitude = round(lat, 3)),
    date = paste0(start, "/", end), data_format = "csv")), auto_unbox = TRUE)
  h <- function() {
    x <- curl::new_handle(timeout = 300)
    curl::handle_setheaders(x, "PRIVATE-TOKEN" = key, "Content-Type" = "application/json")
    if (.Platform$OS.type == "windows") curl::handle_setopt(x, ssl_options = 2)
    x
  }
  p <- h()
  curl::handle_setopt(p, postfields = body)
  job <- jsonlite::fromJSON(rawToChar(curl::curl_fetch_memory(api, handle = p)$content))
  status_url <- sprintf("https://cds.climate.copernicus.eu/api/retrieve/v1/jobs/%s", job$jobID)
  for (i in 1:240) {
    st <- jsonlite::fromJSON(rawToChar(curl::curl_fetch_memory(status_url, handle = h())$content))
    if (st$status %in% c("successful", "failed", "rejected", "dismissed")) break
    Sys.sleep(min(30, 2 * i))
  }
  if (!identical(st$status, "successful")) stop("ERA5-Land request ", st$status)
  res <- jsonlite::fromJSON(rawToChar(curl::curl_fetch_memory(paste0(status_url, "/results"), handle = h())$content))
  tmp <- tempfile()
  curl::curl_download(res$asset$value$href, tmp, handle = h())
  files <- if (grepl("^PK", readChar(tmp, 2, useBytes = TRUE))) {
    d <- tempfile(); utils::unzip(tmp, exdir = d); list.files(d, "\\.csv$", full.names = TRUE, recursive = TRUE)
  } else tmp
  df <- NULL
  for (f in files) {
    p <- utils::read.csv(f, stringsAsFactors = FALSE)
    tc <- grep("time", names(p), ignore.case = TRUE, value = TRUE)[1]
    names(p)[names(p) == tc] <- "time_utc"
    p <- p[, intersect(names(p), c("time_utc", "t2m", "d2m", "tp", "u10", "v10")), drop = FALSE]
    df <- if (is.null(df)) p else merge(df, p, by = "time_utc", all = TRUE)
  }
  df$time_utc <- .parse_times(df$time_utc)
  df <- df[order(df$time_utc), ]
  t <- df$t2m - 273.15
  dp <- df$d2m - 273.15
  rh <- pmin(100, 100 * exp(17.625 * dp / (243.04 + dp)) / exp(17.625 * t / (243.04 + t)))
  tp <- df$tp * 1000
  hourly_tp <- c(NA, diff(tp))
  first_hour <- format(df$time_utc, "%H", tz = "UTC") == "01"
  hourly_tp[first_hour] <- tp[first_hour]
  data.frame(time_utc = df$time_utc, temperature_c = t, relative_humidity_pct = rh,
             precipitation_mm = pmax(0, hourly_tp), wind_speed_ms = sqrt(df$u10^2 + df$v10^2),
             cloud_cover_pct = NA_real_, weather_model = "era5-land")
}

.credentials <- function() {
  f <- file.path(.config_dir(), "credentials.json")
  if (!file.exists(f)) return(list())
  tryCatch(jsonlite::fromJSON(f, simplifyVector = TRUE), error = function(e) list())
}

.hourly_weather <- function(source, lat, lon, start, end) {
  if (!source %in% names(.WEATHER_SOURCES))
    stop("Unknown weather source '", source, "'. Choose from: open-meteo, era5-land, or none", call. = FALSE)
  f <- file.path(.weather_cache(), sprintf("%s_%.3f_%.3f_%s_%s.parquet", source, lat, lon, start, end))
  if (file.exists(f)) {
    d <- as.data.frame(nanoparquet::read_parquet(f))
    d$time_utc <- .ct(d$time_utc)
    return(d)
  }
  d <- if (source == "open-meteo") .open_meteo(lat, lon, start, end) else {
    key <- .credentials()$CDSAPI_KEY
    if (is.null(key)) stop("ERA5-Land needs a Copernicus CDS key: add \"CDSAPI_KEY\" to your credentials file ",
                           "(free account at https://cds.climate.copernicus.eu)", call. = FALSE)
    .era5_land(lat, lon, start, end, key)
  }
  if (!is.null(d) && nrow(d) && end < Sys.Date() - 7) nanoparquet::write_parquet(d, f)
  d
}

.WX_COLS <- c("temperature_mean_c", "temperature_min_c", "temperature_at_start_c", "precipitation_total_mm",
              "rain_hours", "wind_speed_mean_ms", "cloud_cover_mean_pct", "relative_humidity_mean_pct")

# The weather over one spell of work, as weather.over.
.weather_over <- function(hours, start, end) {
  a <- .ct(floor(as.numeric(start) / 3600) * 3600)
  b <- .ct(ceiling(as.numeric(end) / 3600) * 3600)
  h <- hours[hours$time_utc >= a & hours$time_utc <= b, , drop = FALSE]
  if (!nrow(h)) return(NULL)
  m <- function(x) { x <- x[!is.na(x)]; if (length(x)) mean(x) else NA_real_ }
  v <- c(temperature_mean_c = m(h$temperature_c), temperature_min_c = suppressWarnings(min(h$temperature_c, na.rm = TRUE)),
         temperature_at_start_c = h$temperature_c[1], precipitation_total_mm = sum(h$precipitation_mm, na.rm = TRUE),
         rain_hours = sum(h$precipitation_mm >= 0.1, na.rm = TRUE), wind_speed_mean_ms = m(h$wind_speed_ms),
         cloud_cover_mean_pct = m(h$cloud_cover_pct), relative_humidity_mean_pct = m(h$relative_humidity_pct))
  v[is.infinite(v)] <- NA
  v[names(v) != "rain_hours"] <- round(v[names(v) != "rain_hours"], 2)
  v
}
