# ERA5-Land weather from the Copernicus Climate Data Store, for commercial work: the R twin of the
# toolkit's copernicus.py. Each person needs their own free Copernicus key, set up once with
# cehbio_weather_setup(); it's saved as "CDSAPI_KEY" in the private credentials file that Python reads too.

.CDS_API <- "https://cds.climate.copernicus.eu/api"
.CDS_DATASET <- "reanalysis-era5-land-timeseries"
.CDS_URLS <- c(register = "https://cds.climate.copernicus.eu",
               licence = "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-timeseries?tab=download",
               key = "https://cds.climate.copernicus.eu/profile")
.CDS_HOW_TO <- paste("Set it up once (about 5 minutes): run cehbio_weather_setup() in R (or cehbio weather-setup in a",
                     "terminal). It walks you through making a free Copernicus account, accepting the licence and",
                     "saving your key.")

.credentials_file <- function() {
  f <- Sys.getenv("CEHBIO_CREDENTIALS")
  if (nzchar(f)) f else file.path(.config_dir(), "credentials.json")
}

.cds_saved_key <- function() {
  k <- Sys.getenv("CDSAPI_KEY")
  if (nzchar(k)) return(trimws(k))
  f <- .credentials_file()
  if (!file.exists(f)) return(NULL)
  k <- tryCatch(jsonlite::fromJSON(f, simplifyVector = TRUE)$CDSAPI_KEY, error = function(e) NULL)
  if (is.null(k) || !nzchar(trimws(k))) NULL else trimws(k)
}

.cds_save_key <- function(key) {
  f <- .credentials_file()
  dir.create(dirname(f), recursive = TRUE, showWarnings = FALSE)
  creds <- if (file.exists(f)) tryCatch(jsonlite::fromJSON(f, simplifyVector = FALSE), error = function(e)
    stop(f, " isn't valid JSON, so the key wasn't added. Fix or move that file, then try again.", call. = FALSE)) else list()
  creds$CDSAPI_KEY <- key
  tmp <- paste0(f, ".tmp")
  jsonlite::write_json(creds, tmp, auto_unbox = TRUE, pretty = TRUE)
  if (.Platform$OS.type != "windows") Sys.chmod(tmp, "600")
  file.rename(tmp, f)
  f
}

.cds_handle <- function(key = NULL, timeout = 60) {
  h <- curl::new_handle(useragent = "ceh-biomonitoring", timeout = timeout)
  if (!is.null(key)) curl::handle_setheaders(h, "PRIVATE-TOKEN" = key)
  if (.Platform$OS.type == "windows") curl::handle_setopt(h, ssl_options = 2)
  h
}

.cds_check <- function(key) {
  if (is.null(key) || !grepl("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", key, ignore.case = TRUE))
    return(list(state = "bad key", msg = paste0("That doesn't look like a Copernicus key. It looks like ",
      "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (letters a-f and numbers). Copy the whole 'API Token' from ", .CDS_URLS[["key"]])))
  r <- tryCatch(curl::curl_fetch_memory(paste0(.CDS_API, "/profiles/v1/account/licences"), handle = .cds_handle(key)),
                error = function(e) NULL)
  if (is.null(r)) return(list(state = "offline", msg = "Couldn't reach Copernicus. Check the internet connection."))
  if (r$status_code %in% c(401, 403)) return(list(state = "bad key", msg = paste0(
    "Copernicus didn't accept that key. Copy it again from ", .CDS_URLS[["key"]], " (the 'API Token').")))
  if (r$status_code != 200) return(list(state = "offline", msg = paste0("Copernicus answered ", r$status_code,
                                                                        "; it may be busy. Try again later.")))
  got <- jsonlite::fromJSON(rawToChar(r$content), simplifyVector = FALSE)
  lic <- if (!is.null(got$licences)) got$licences else got
  ids <- tolower(unlist(lapply(lic, function(x) if (is.list(x)) x$id else NULL)))
  if (!"cc-by" %in% ids) return(list(state = "no licence", msg = paste0(
    "The key works, but the ERA5-Land licence hasn't been accepted yet. Open ", .CDS_URLS[["licence"]],
    " (logged in), scroll to the bottom of the Download tab, and under 'Terms of use' click Accept. It's the CC-BY ",
    "licence and you only do it once.")))
  list(state = "ok", msg = "Your Copernicus key works and the ERA5-Land licence is accepted.")
}

.cds_explain <- function(r) {
  msg <- tryCatch({ d <- jsonlite::fromJSON(rawToChar(r$content)); d$detail %||% d$title %||% "" }, error = function(e) "")
  if (r$status_code == 401) return(paste("Copernicus didn't accept your key.", .CDS_HOW_TO))
  if (r$status_code == 403 || grepl("licen", msg, ignore.case = TRUE))
    return(paste0("Copernicus refused the request: the ERA5-Land licence hasn't been accepted on your account. Open ",
                  .CDS_URLS[["licence"]], " (logged in), and at the bottom of the Download tab, under 'Terms of use', ",
                  "click Accept. Then make the report again. (cehbio_weather_setup(check = TRUE) checks it.)"))
  paste0("Copernicus couldn't make the weather (", r$status_code, ": ", msg, ").")
}

# Hourly ERA5-Land at a point, raw CDS columns (time_utc, t2m, d2m, tp, u10, v10).
.cds_fetch <- function(lat, lon, start, end, key) {
  body <- jsonlite::toJSON(list(inputs = list(
    variable = c("2m_temperature", "2m_dewpoint_temperature", "total_precipitation",
                 "10m_u_component_of_wind", "10m_v_component_of_wind"),
    location = list(latitude = round(lat, 3), longitude = round(lon, 3)),
    date = I(paste0(start, "/", end)), data_format = "csv")), auto_unbox = TRUE)
  h <- .cds_handle(key)
  curl::handle_setheaders(h, "PRIVATE-TOKEN" = key, "Content-Type" = "application/json")
  curl::handle_setopt(h, postfields = body)
  r <- curl::curl_fetch_memory(paste0(.CDS_API, "/retrieve/v1/processes/", .CDS_DATASET, "/execution"), handle = h)
  if (!r$status_code %in% c(200, 201)) stop(.cds_explain(r), call. = FALSE)
  job <- jsonlite::fromJSON(rawToChar(r$content))$jobID
  status_url <- paste0(.CDS_API, "/retrieve/v1/jobs/", job)
  message("  ERA5-Land: request queued at Copernicus (usually a minute or two) ...")
  st <- ""
  for (i in 1:240) {
    st <- jsonlite::fromJSON(rawToChar(curl::curl_fetch_memory(status_url, handle = .cds_handle(key))$content))$status
    if (st %in% c("successful", "failed", "rejected", "dismissed")) break
    Sys.sleep(min(30, 2 + 2 * i))
  }
  if (!identical(st, "successful")) stop("Copernicus couldn't make the weather (the request was ", st, "). Try again later.", call. = FALSE)
  res <- jsonlite::fromJSON(rawToChar(curl::curl_fetch_memory(paste0(status_url, "/results"), handle = .cds_handle(key))$content))
  tmp <- tempfile()
  curl::curl_download(res$asset$value$href, tmp, handle = .cds_handle(key, 600))
  files <- if (identical(readBin(tmp, "raw", 2), charToRaw("PK"))) {
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
  df
}

.ask <- function(prompt) {
  if (!interactive()) stop("cehbio_weather_setup() needs someone at the keyboard (an interactive R session).", call. = FALSE)
  readline(prompt)
}
.open_page <- function(url) {
  message("     ", url)
  if (tolower(trimws(.ask("     Press Enter to open it in your browser (or type n and Enter to skip): "))) != "n") utils::browseURL(url)
}
.ask_secret <- function(prompt) {
  if (requireNamespace("askpass", quietly = TRUE)) return(askpass::askpass(prompt) %||% "")
  if (requireNamespace("rstudioapi", quietly = TRUE) && rstudioapi::isAvailable()) return(rstudioapi::askForPassword(prompt) %||% "")
  readline(paste0(prompt, " "))
}

#' Set up ERA5-Land weather for commercial reports (once)
#'
#' Open-Meteo, the usual weather, is free for non-commercial work only. Commercial reports use ERA5-Land
#' (`weather = "era5-land"`), which anyone may use (CC BY 4.0) but which needs your own free Copernicus
#' account and key. This walks you through the three steps (an account, accepting the licence, your
#' key), checks each one, and saves the key privately as `CDSAPI_KEY` in your credentials file
#' (`~/.config/ceh-biomonitoring/credentials.json`), which the Python toolkit reads too. The key is never
#' shown. Accounts are personal: please don't share a key.
#' @param check only check the key you've already saved
#' @return TRUE if it's ready, invisibly
#' @export
cehbio_weather_setup <- function(check = FALSE) {
  if (check) {
    k <- .cds_saved_key()
    if (is.null(k)) { message("No Copernicus key saved yet. ", .CDS_HOW_TO); return(invisible(FALSE)) }
    res <- .cds_check(k)
    message(res$msg)
    return(invisible(res$state == "ok"))
  }
  message("Weather for commercial reports: ERA5-Land, from Copernicus\n\n",
          "Open-Meteo (the usual weather) is free for non-commercial work only. For commercial reports the toolkit uses\n",
          "ERA5-Land, which anyone may use (CC BY 4.0) but which needs your own free Copernicus account and key.\n",
          "This takes about 5 minutes, once. Three steps:\n")
  k <- .cds_saved_key()
  if (!is.null(k)) {
    res <- .cds_check(k)
    if (res$state == "ok") { message("You're already set up. ", res$msg); return(invisible(TRUE)) }
    message("You have a key saved, but: ", res$msg, "\n")
  }
  message("STEP 1 of 3: a free Copernicus account\n",
          "  If you don't have one: open the page below, click 'Login - Register' (top right) and register.\n",
          "  You'll get an email to confirm it.")
  .open_page(.CDS_URLS[["register"]])
  .ask("  Press Enter when you have an account and are logged in ... ")
  message("\nSTEP 2 of 3: accept the ERA5-Land licence (once)\n",
          "  On the page below, go to the 'Download' tab, scroll to the bottom, and under 'Terms of use' click\n",
          "  'Accept' (it's the CC-BY licence). If it already says accepted, that's fine.")
  .open_page(.CDS_URLS[["licence"]])
  .ask("  Press Enter when it's accepted ... ")
  message("\nSTEP 3 of 3: your key\n  On your profile page (below), find 'API Token' and copy it (the copy button next to it).")
  .open_page(.CDS_URLS[["key"]])
  for (attempt in 1:5) {
    key <- trimws(.ask_secret("  Paste your key and press Enter (it stays hidden, which is normal):"))
    res <- .cds_check(key)
    if (res$state == "ok") {
      f <- .cds_save_key(key)
      message("\nDone. ", res$msg, "\nYour key is saved privately in ", f, " (as CDSAPI_KEY).\n",
              "Make commercial reports with weather = \"era5-land\" (in a terminal: --weather era5-land).")
      return(invisible(TRUE))
    }
    message("  ", res$msg)
    if (res$state == "no licence") {
      f <- .cds_save_key(key)
      .open_page(.CDS_URLS[["licence"]])
      .ask("  Press Enter once you've clicked Accept ... ")
      res <- .cds_check(key)
      message("  ", res$msg)
      if (res$state == "ok") { message("\nDone. Your key is saved privately in ", f, " (as CDSAPI_KEY)."); return(invisible(TRUE)) }
      message("  Your key is saved in ", f, ". If you're sure you accepted the licence, carry on: the first ERA5-Land ",
              "report will say if it's still missing.")
      return(invisible(FALSE))
    }
    if (res$state == "offline") return(invisible(FALSE))
  }
  message("Stopped after several tries. Run cehbio_weather_setup() again when you're ready, or ask for help.")
  invisible(FALSE)
}
