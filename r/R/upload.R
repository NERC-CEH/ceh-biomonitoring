# Uploading recordings or images to UKCEH, and asking for deployments, from R with no Python: the R twin
# of the toolkit's upload.py and sites.py. Same upload service, same questions, and the same upload log,
# so an upload started in R can be finished in Python (or the other way round): files already sent are
# skipped. The password is never shown, logged or saved by this; the upload links aren't logged.

.UPLOAD_URL <- "https://connect-apps.ceh.ac.uk/ceh-biomonitoring-upload/"
.MIN_BYTES <- 10 * 1024
.SKIP_PARTS <- c("$RECYCLE.BIN", ".Trashes", ".Trash-0", "System Volume Information")
.SALTMARSH <- "united kingdom (saltmarsh soundscapes)"

.saved_login <- function() {
  f <- .credentials_file()
  if (!file.exists(f)) return(list())
  saved <- tryCatch(jsonlite::fromJSON(f, simplifyVector = TRUE), error = function(e) list())
  # as the Python tool: a login other people can read isn't used (the rest, e.g. UPLOAD_URL, isn't secret)
  if (.Platform$OS.type == "unix" && length(saved) && any(c("UKCEH_username", "UKCEH_password") %in% names(saved)) &&
      bitwAnd(as.integer(file.info(f)$mode), strtoi("44", 8L)) != 0) {
    message("Not using the login in ", f, ": other people can read it (fix with chmod 600 ", f, ").")
    saved[c("UKCEH_username", "UKCEH_password")] <- NULL
  }
  saved
}

.service <- function() {
  saved <- .saved_login()
  user <- Sys.getenv("CEHBIO_UPLOAD_USER")
  if (!nzchar(user)) user <- saved$UKCEH_username %||% ""
  if (!nzchar(user)) user <- .need_answer("Upload service username: ")
  pw <- Sys.getenv("CEHBIO_UPLOAD_PASSWORD")
  if (!nzchar(pw)) pw <- saved$UKCEH_password %||% ""
  if (!nzchar(pw)) {
    if (!interactive()) stop("No upload password: set CEHBIO_UPLOAD_PASSWORD, or run this in an interactive R session.", call. = FALSE)
    pw <- .ask_secret("Upload service password (hidden):")
  }
  list(url = sub("/?$", "/", saved$UPLOAD_URL %||% .UPLOAD_URL), user = user, pw = pw)
}

.need_answer <- function(prompt, default = NULL) {
  if (!interactive()) stop("Missing an answer for '", sub(":? *$", "", prompt), "': give it as an argument.", call. = FALSE)
  v <- trimws(readline(paste0(prompt, if (!is.null(default)) paste0("[", default, "] ") else "")))
  if (!nzchar(v) && !is.null(default)) default else v
}

.retry <- function(f, attempts = 5, base = 2) {
  for (i in seq_len(attempts)) {
    r <- tryCatch(f(), error = function(e) e)
    if (!inherits(r, "error")) return(r)
    if (i == attempts || inherits(r, "cehbio_refused") || grepl("did not accept your username", conditionMessage(r))) stop(r)
    Sys.sleep(min(60, base * 2^(i - 1)))
  }
}

.svc_post <- function(svc, path, fields) {
  all <- c(as.list(fields), list(username = svc$user, password = svc$pw))
  vals <- vapply(all, function(v) as.character(unname(v))[1], "")
  body <- paste0(curl::curl_escape(names(all)), "=", curl::curl_escape(vals), collapse = "&")
  h <- curl::new_handle(timeout = 300, postfields = body)
  curl::handle_setheaders(h, "Content-Type" = "application/x-www-form-urlencoded", "User-Agent" = "ceh-biomonitoring")
  if (.Platform$OS.type == "windows") curl::handle_setopt(h, ssl_options = 2)
  r <- curl::curl_fetch_memory(paste0(svc$url, path), handle = h)
  txt <- rawToChar(r$content)
  Encoding(txt) <- "UTF-8"
  if (r$status_code == 401) stop("The upload service did not accept your username or password.", call. = FALSE)
  if (r$status_code %in% c(403, 422)) {
    why <- tryCatch(jsonlite::fromJSON(txt)$detail, error = function(e) NULL)
    stop(structure(class = c("cehbio_refused", "error", "condition"),
                   list(message = substr(if (is.character(why)) why else txt, 1, 500), call = NULL)))
  }
  if (r$status_code >= 400) stop(sprintf("HTTP %d at %s: %s", r$status_code, path, substr(txt, 1, 500)), call. = FALSE)
  tryCatch(jsonlite::fromJSON(txt, simplifyVector = FALSE), error = function(e) txt)
}

.svc_deployments <- function(svc) .svc_post(svc, "get-deployments/", list())

.svc_exists <- function(svc, base, filename) {
  d <- .retry(function() .svc_post(svc, "check-file-exist/", c(base, list(filename = filename))))
  if (is.list(d)) {
    if (!is.null(d$exists)) return(isTRUE(as.logical(d$exists)))
    if (is.list(d$result) && !is.null(d$result$exists)) return(isTRUE(as.logical(d$result$exists)))
    if (!is.null(d[[filename]]) && (is.logical(d[[filename]]) || is.numeric(d[[filename]]))) return(isTRUE(as.logical(d[[filename]])))
  }
  stop("Unexpected reply from check-file-exist: ", substr(paste(d, collapse = " "), 1, 300), call. = FALSE)
}

.svc_link <- function(svc, base, filename, file_type) {
  d <- .retry(function() .svc_post(svc, "generate-presigned-url/", c(base, list(filename = filename, file_type = file_type))))
  if (is.character(d)) return(gsub('^"|"$', "", trimws(d)))
  if (is.list(d)) for (v in list(d$url, d[[filename]], if (is.list(d$result)) d$result$url)) if (is.character(v)) return(v)
  stop("Unexpected reply from generate-presigned-url", call. = FALSE)
}

.file_type <- function(path) {
  ext <- tolower(tools::file_ext(path))
  t <- c(jpg = "image/jpeg", jpeg = "image/jpeg", wav = "audio/x-wav")[ext]
  if (is.na(t)) "application/octet-stream" else unname(t)
}

.choose <- function(prompt, options, given = NULL) {
  if (!is.null(given)) {
    hit <- options[tolower(options) == tolower(given)]
    if (!length(hit)) hit <- options[grepl(tolower(given), tolower(options), fixed = TRUE)]
    if (length(hit) == 1) return(hit)
    stop("'", given, "' doesn't match one of: ", paste(options, collapse = ", "), call. = FALSE)
  }
  if (!interactive()) stop(prompt, " needed: give it as an argument (one of: ", paste(options, collapse = ", "), ")", call. = FALSE)
  message(prompt)
  i <- utils::menu(options)
  if (i == 0) stop("Stopped.", call. = FALSE)
  options[i]
}

.find_files <- function(folder, data_type) {
  exts <- if (data_type == "snapshot_images") c("jpg", "jpeg") else "wav"
  f <- list.files(folder, recursive = TRUE, full.names = TRUE, all.files = TRUE)
  f <- f[tolower(tools::file_ext(f)) %in% exts]
  f <- f[!vapply(f, function(p) any(vapply(.SKIP_PARTS, function(s) grepl(s, p, fixed = TRUE), TRUE)), TRUE)]
  sz <- file.size(f)
  sort(f[!is.na(sz) & sz >= .MIN_BYTES], method = "radix")
}

.log_path <- function(log_dir, bucket, dep, data_type) {
  safe <- function(s) gsub("[/ ]", "_", s)
  file.path(log_dir, sprintf("upload_status_%s_%s_%s.csv", safe(bucket), safe(dep), safe(data_type)))
}

.log <- function(path, local, stage, status, detail = "") {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  row <- data.frame(timestamp_utc = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
                    local_path = normalizePath(local, mustWork = FALSE), filename = basename(local), stage = stage,
                    status = status, detail = substr(detail, 1, 1000))
  utils::write.table(row, path, sep = ",", row.names = FALSE, col.names = !file.exists(path), append = file.exists(path),
                     qmethod = "double", fileEncoding = "UTF-8")
}

.already_uploaded <- function(path) {
  if (!file.exists(path)) return(character())
  l <- tryCatch(utils::read.csv(path, stringsAsFactors = FALSE, colClasses = "character"), error = function(e) NULL)
  if (is.null(l)) return(character())
  unique(l$filename[l$stage == "UPLOAD" & l$status == "OK"])
}

# PUT several files at once, each to its own upload link; returns TRUE/FALSE per file, with the reasons.
.put_many <- function(links, files, types, tries = 5) {
  ok <- rep(FALSE, length(files)); why <- rep("", length(files))
  for (attempt in seq_len(tries)) {
    todo <- which(!ok)
    if (!length(todo)) break
    pool <- curl::new_pool()
    for (i in todo) local({
      i <- i
      size <- file.size(files[i])
      con <- file(files[i], "rb")
      h <- curl::new_handle(upload = TRUE, infilesize_large = size, customrequest = "PUT", timeout = 3600,
                            readfunction = function(n) readBin(con, raw(), n))
      curl::handle_setheaders(h, "Content-Type" = types[i])
      if (.Platform$OS.type == "windows") curl::handle_setopt(h, ssl_options = 2)
      curl::curl_fetch_multi(links[i], handle = h, pool = pool,
        done = function(r) { close(con); if (r$status_code < 400) ok[i] <<- TRUE else why[i] <<- sprintf("upload failed HTTP %d", r$status_code) },
        fail = function(e) { close(con); why[i] <<- conditionMessage(e) })
    })
    curl::multi_run(pool = pool)
    if (all(ok)) break
    Sys.sleep(min(60, 2 * 2^(attempt - 1)))
  }
  list(ok = ok, why = why)
}

#' Upload recordings or images to UKCEH
#'
#' The same as `cehbio upload`, in R with no Python: it signs in to the UKCEH upload service, asks which
#' deployment and what kind of data (or takes them as arguments), finds the files, and uploads them. Every
#' file is logged in `<results>/upload_logs/`, so running it again carries on where it stopped (and an
#' upload started with the Python tool can be finished here, and the other way round).
#'
#' Use your own upload login from UKCEH (the old shared login no longer works). It's read from your
#' `credentials.json` (`UKCEH_username`, `UKCEH_password`) or the `CEHBIO_UPLOAD_USER` and
#' `CEHBIO_UPLOAD_PASSWORD` environment variables, or asked for (the password stays hidden). Each login
#' sees and can upload to only the deployments UKCEH has given it, plus any it asked for once approved;
#' the service refuses anything else, with the reason. Your files are never changed, moved or deleted.
#'
#' @param folder the folder or SD card with this deployment's data
#' @param country,deployment as listed by the service (part of the name is enough if it's unique)
#' @param data_type "snapshot_images", "audible_recordings" or "ultrasound_recordings"
#' @param name your full name
#' @param test upload 10 random files only (asked if not given)
#' @param yes don't ask for confirmation
#' @param parallel files at once
#' @param check_remote ask the service whether each file is already there
#' @param log_dir where to keep the upload log
#' @return the counts (uploaded, already there, failed), invisibly
#' @export
cehbio_upload <- function(folder = NULL, country = NULL, deployment = NULL, data_type = NULL, name = NULL,
                          test = NULL, yes = FALSE, parallel = 5, check_remote = TRUE, log_dir = NULL) {
  svc <- .service()
  message("Fetching the list of deployments...")
  deps <- Filter(function(d) identical(d$status, "active"), .svc_deployments(svc))
  if (!length(deps)) message("Your login has no active deployments yet. Each login only sees the deployments UKCEH has given it.\n",
                             "  - If you're expecting one, ask UKCEH to add it to your login.\n",
                             "  - To ask for a new one: cehbio_request_deployment()\n",
                             "  - You can still try a test upload: country = \"Test\".")
  name <- name %||% .need_answer("Your full name: ")
  countries <- c(sort(unique(vapply(deps, function(d) d$country, ""))), "Test")
  country <- .choose("\nCountry:", countries, country)
  if (country == "Test") {
    bucket <- "test-upload"; dep_id <- "dep_test"
  } else {
    here <- Filter(function(d) d$country == country, deps)
    labels <- vapply(here, function(d) paste(d$location_name, "-", d$camera_id), "")
    label <- .choose("\nDeployment:", labels, deployment)
    d <- here[[match(label, labels)]]
    bucket <- tolower(d$country_code); dep_id <- d$deployment_id
  }
  types <- if (tolower(country) == .SALTMARSH) c("terrestrial_recordings", "aquatic_recordings")
           else c("snapshot_images", "audible_recordings", "ultrasound_recordings")
  data_type <- .choose("\nWhat are you uploading?", types, data_type)
  folder <- folder %||% .need_answer("\nFolder with the files (e.g. the SD card): ")
  folder <- gsub("^[\"']|[\"']$", "", trimws(folder))
  while (!dir.exists(folder)) {
    if (!interactive()) stop("Folder not found: ", folder, call. = FALSE)
    folder <- gsub("^[\"']|[\"']$", "", trimws(.need_answer("That folder doesn't exist. Folder path: ")))
  }
  files <- .find_files(folder, data_type)
  if (!length(files)) stop("No ", data_type, " files found in ", folder, call. = FALSE)
  logp <- .log_path(log_dir %||% file.path(results_folder(), "upload_logs"), bucket, dep_id, data_type)
  done <- .already_uploaded(logp)
  if (length(done)) {
    before <- length(files)
    files <- files[!basename(files) %in% done]
    message("\nResuming: ", before - length(files), " files already uploaded earlier, ", length(files), " still to do.")
  }
  if (is.null(test)) test <- !yes && interactive() && grepl("^y", tolower(.need_answer("\nTry 10 random files first as a test? (yes/no) ", "no")))
  if (isTRUE(test) && length(files)) { files <- sample(files, min(10, length(files))); message("Test run with ", length(files), " files.") }
  message(sprintf("\n  Name:        %s\n  Destination: %s / %s / %s\n  Files:       %d from %s\n  Log:         %s",
                  name, bucket, dep_id, data_type, length(files), folder, logp))
  if (!length(files)) { message("Nothing left to upload."); return(invisible(c(uploaded = 0))) }
  if (!yes && !grepl("^y", tolower(.need_answer("\nStart uploading? (yes/no) ", "no")))) { message("Cancelled."); return(invisible(NULL)) }

  base <- list(name = name, country = bucket, deployment = dep_id, data_type = data_type)
  counts <- c(uploaded = 0, `already there` = 0, failed = 0)
  batches <- split(seq_along(files), ceiling(seq_along(files) / max(1, parallel)))
  n_done <- 0
  for (b in batches) {
    links <- rep(NA_character_, length(b)); types <- unname(vapply(files[b], .file_type, ""))
    for (k in seq_along(b)) {
      f <- files[b[k]]
      if (check_remote) {
        there <- tryCatch(.svc_exists(svc, base, basename(f)), error = function(e) { .log(logp, f, "CHECK_REMOTE", "FAIL", conditionMessage(e)); NA })
        if (isTRUE(there)) { .log(logp, f, "CHECK_REMOTE", "OK", "exists=True"); counts[["already there"]] <- counts[["already there"]] + 1; next }
        if (identical(there, FALSE)) .log(logp, f, "CHECK_REMOTE", "OK", "exists=False")
      }
      links[k] <- tryCatch({ l <- .svc_link(svc, base, basename(f), types[k]); .log(logp, f, "PRESIGN", "OK"); l },
                           error = function(e) { .log(logp, f, "PRESIGN", "FAIL", conditionMessage(e)); NA })
      if (is.na(links[k])) counts[["failed"]] <- counts[["failed"]] + 1
    }
    go <- which(!is.na(links) & grepl("^https?://", links, ignore.case = TRUE))
    if (length(go)) {
      res <- .put_many(links[go], files[b[go]], types[go])
      for (j in seq_along(go)) {
        f <- files[b[go[j]]]
        if (res$ok[j]) { .log(logp, f, "UPLOAD", "OK"); counts[["uploaded"]] <- counts[["uploaded"]] + 1 }
        else { .log(logp, f, "UPLOAD", "FAIL", res$why[j]); counts[["failed"]] <- counts[["failed"]] + 1 }
      }
    }
    n_done <- n_done + length(b)
    if (n_done %% 25 < length(b) || n_done == length(files))
      message(sprintf("  %d/%d done: %s", n_done, length(files), paste(names(counts)[counts > 0], counts[counts > 0], collapse = ", ")))
  }
  message("\nFinished: ", paste(names(counts), counts, collapse = ", "), "\nLog: ", logp)
  if (counts[["failed"]]) message("Some files failed. Run the same command again to retry just those.")
  invisible(counts)
}

#' Your deployments
#'
#' The deployments your login can use on the UKCEH upload service (the ones UKCEH has given it, and
#' any you asked for), and whether each is active (ready for uploads) or pending (waiting for UKCEH to
#' check it). The same as `cehbio deployments list`.
#' @param country only this country
#' @param all include inactive and rejected ones
#' @return a data frame, invisibly
#' @export
cehbio_deployments <- function(country = NULL, all = FALSE) {
  deps <- .svc_deployments(.service())
  g <- function(d, k) if (is.null(d[[k]])) "" else as.character(d[[k]])
  t <- data.frame(id = vapply(deps, g, "", "deployment_id"), status = vapply(deps, g, "", "status"),
                  country = vapply(deps, g, "", "country"), site = vapply(deps, g, "", "location_name"),
                  device = vapply(deps, g, "", "camera_id"), start = vapply(deps, g, "", "start_date"),
                  end = vapply(deps, g, "", "end_date"), stringsAsFactors = FALSE)
  if (!is.null(country)) t <- t[grepl(tolower(country), tolower(t$country), fixed = TRUE), , drop = FALSE]
  if (!all) t <- t[t$status %in% c("active", "pending"), , drop = FALSE]
  t <- t[order(t$country, t$site, method = "radix"), , drop = FALSE]
  rownames(t) <- NULL
  if (!nrow(t)) message("No deployments found.", if (!all) " (all = TRUE includes inactive ones.)")
  else { print(t); message("\nOnly 'active' deployments can be uploaded to. 'pending' ones are waiting for UKCEH to check them.") }
  invisible(t)
}

#' Ask UKCEH for a new deployment
#'
#' One device at one site for one survey period. Asks step by step for anything not given, shows it all to
#' confirm, and sends it; it's then 'pending' until UKCEH checks it. The same as `cehbio deployments request`.
#' @param name,country,site,lat,lon,device_type,device_id,start,end,notes the details (asked if not given)
#' @param yes send without asking for confirmation
#' @export
cehbio_request_deployment <- function(name = NULL, country = NULL, site = NULL, lat = NULL, lon = NULL, device_type = NULL,
                                      device_id = NULL, start = NULL, end = NULL, notes = NULL, yes = FALSE) {
  svc <- .service()
  deps <- .svc_deployments(svc)
  countries <- sort(unique(unlist(lapply(deps, function(d) d$country))))
  message("Ask UKCEH for a new deployment: one device at one site for one survey period.\n")
  name <- name %||% .need_answer("Your full name: ")
  country <- .choose("Country:", countries, country)
  site <- site %||% .need_answer("Site name (short and clear, e.g. 'Wytham Woods 1'): ")
  num <- function(prompt, low, high, given) {
    repeat {
      v <- if (!is.null(given)) as.character(given) else .need_answer(paste0(prompt, ": "))
      x <- suppressWarnings(as.numeric(v))
      if (!is.na(x) && x >= low && x <= high) return(v)
      if (!is.null(given)) stop(prompt, ": must be a number between ", low, " and ", high, call. = FALSE)
      message("Please type a number between ", low, " and ", high, ", e.g. 51.6")
    }
  }
  day <- function(prompt, given, required) {
    repeat {
      v <- if (!is.null(given)) given else .need_answer(paste0(prompt, if (required) " (YYYY-MM-DD): " else " (YYYY-MM-DD, or leave empty): "))
      if ((!nzchar(v) && !required) || grepl("^\\d{4}-\\d{2}-\\d{2}$", v)) return(v)
      if (!is.null(given)) stop(prompt, ": use the form 2026-05-01", call. = FALSE)
      message("Please use the form 2026-05-01")
    }
  }
  if (is.null(lat) || is.null(lon)) message("Where exactly is the device? Decimal degrees, e.g. 51.7714 and -1.3389 (copy from a map app).")
  lat <- num("Latitude", -90, 90, lat)
  lon <- num("Longitude", -180, 180, lon)
  device_type <- device_type %||% .choose("Device type:", c("AMI trap", "LepiSense / AMI-mini", "AudioMoth", "Song Meter",
                                                            "Insect Detect", "Other"))
  device_id <- device_id %||% .need_answer("Device ID or serial number (as written on the device or in its file names): ")
  start <- day("First day of recording", start, TRUE)
  end <- day("Last day of recording", if (!is.null(end) || !yes) end else "", FALSE)
  notes <- if (!is.null(notes) || yes) notes %||% "" else .need_answer("Anything else UKCEH should know (or leave empty): ")
  message(sprintf("\n  %s / %s (%s, %s)\n  %s %s, from %s%s\n  requested by %s", country, site, lat, lon, device_type,
                  device_id, start, if (nzchar(end)) paste(" to", end) else "", name))
  if (!yes && !grepl("^y", tolower(.need_answer("\nSend this request? (yes/no) ", "no")))) { message("Not sent."); return(invisible(NULL)) }
  r <- tryCatch(.svc_post(svc, "request-deployment/", list(country = country, location_name = site, lat = lat, lon = lon,
                                                           camera_id = device_id, requested_by = name, device_type = device_type,
                                                           start_date = start, end_date = end, notes = notes)),
                error = function(e) {
                  m <- conditionMessage(e)
                  if (grepl("HTTP 422", m)) {
                    j <- tryCatch(jsonlite::fromJSON(sub("^[^:]*: [^:]*: ", "", m))$message, error = function(e2) NULL)
                    stop("UKCEH's service could not accept this request:\n  ", j %||% m, call. = FALSE)
                  }
                  stop(e)
                })
  message("\nSent. Your deployment ID is ", r$deployment_id, " (pending).\n",
          "UKCEH will check it and make it active; you'll then see it in cehbio_upload().\n",
          "Check with: cehbio_deployments()")
  invisible(r$deployment_id)
}

.find_deployment <- function(deps, given) {
  g <- tolower(trimws(given %||% ""))
  ids <- vapply(deps, function(d) tolower(d$deployment_id %||% ""), "")
  if (g %in% ids) return(deps[[match(g, ids)]])
  labels <- vapply(deps, function(d) tolower(paste(d$location_name %||% "", d$camera_id %||% "")), "")
  hits <- which(nzchar(g) & grepl(g, labels, fixed = TRUE))
  if (length(hits) == 1) return(deps[[hits]])
  shown <- paste(vapply(deps[if (length(hits)) hits else seq_along(deps)][seq_len(min(15, max(1, length(deps))))],
                        function(d) paste0(d$deployment_id, " (", d$location_name %||% "", ")"), ""), collapse = ", ")
  stop(if (length(hits)) "Several" else "No", " deployments match '", given, "'. Yours: ",
       if (length(deps)) shown else "none yet", call. = FALSE)
}

#' Files already stored for one of your deployments
#'
#' Asks the UKCEH upload service which files are stored for one of your deployments (finished ones too),
#' with your own upload login: no object-store key is needed, and you only see your own deployments.
#' The store gives 1,000 files at a time, so a big deployment takes a while; `name_prefix` (e.g. a date,
#' `"202605"`) lists part of it. The same as `cehbio uploaded` in the Python toolkit.
#'
#' @param deployment deployment ID (e.g. `"dep000123"`) or part of its site name
#' @param data_type e.g. `"snapshot_images"`, `"audible_recordings"`, `"ultrasound_recordings"`
#' @param name_prefix only files whose names start with this
#' @param out optional CSV file to write the list to
#' @return a data frame: `filename`, `size` (bytes), `stored` (when it was stored)
#' @export
cehbio_uploaded_files <- function(deployment, data_type = "snapshot_images", name_prefix = "", out = NULL) {
  svc <- .service()
  d <- .find_deployment(.svc_deployments(svc), deployment)
  base <- list(country = tolower(d$country_code), deployment = d$deployment_id, data_type = data_type)
  message("Listing ", d$deployment_id, " (", d$location_name %||% "", "), ", data_type,
          if (nzchar(name_prefix)) paste0(", names starting '", name_prefix, "'") else "", "...")
  files <- list(); token <- ""
  repeat {
    r <- .retry(function() .svc_post(svc, "list-files/", c(base, list(name_prefix = name_prefix, continuation_token = token))))
    files <- c(files, r$files)
    token <- r[["next"]] %||% ""
    if (!nzchar(token)) break
    message("  ", length(files), " files so far...")
  }
  t <- data.frame(filename = vapply(files, function(f) f$filename, ""),
                  size = vapply(files, function(f) as.numeric(f$size %||% NA), 0),
                  stored = vapply(files, function(f) f$stored %||% "", ""), stringsAsFactors = FALSE)
  message(nrow(t), " files (", format(round(sum(t$size, na.rm = TRUE) / 1e9, 2), nsmall = 2), " GB)")
  if (!is.null(out)) utils::write.csv(t, out, row.names = FALSE)
  attr(t, "deployment") <- base
  t
}

#' Download files from one of your deployments
#'
#' Downloads files stored for one of your deployments through the UKCEH upload service (no object-store
#' key needed). Files already in `dest` with the right size are skipped, so it's safe to run again.
#'
#' @param deployment deployment ID or part of its site name
#' @param filenames file names to download, e.g. from [cehbio_uploaded_files()] (all of them if `NULL`)
#' @param data_type as in [cehbio_uploaded_files()]
#' @param dest folder to download into
#' @return the paths of the downloaded files, invisibly
#' @export
cehbio_download_files <- function(deployment, filenames = NULL, data_type = "snapshot_images", dest = "downloads") {
  listed <- cehbio_uploaded_files(deployment, data_type)
  base <- attr(listed, "deployment")
  want <- if (is.null(filenames)) listed else listed[listed$filename %in% filenames, , drop = FALSE]
  if (!is.null(filenames) && length(missing <- setdiff(filenames, listed$filename)))
    warning("Not stored for this deployment: ", paste(utils::head(missing, 10), collapse = ", "), call. = FALSE)
  dir.create(dest, showWarnings = FALSE, recursive = TRUE)
  svc <- .service()
  paths <- character()
  for (i in seq_len(nrow(want))) {
    p <- file.path(dest, want$filename[i])
    if (!(file.exists(p) && isTRUE(file.size(p) == want$size[i]))) {
      link <- .retry(function() .svc_post(svc, "download-link/", c(base, list(filename = want$filename[i]))))$url
      h <- curl::new_handle()
      if (.Platform$OS.type == "windows") curl::handle_setopt(h, ssl_options = 2)
      curl::curl_download(link, p, handle = h, quiet = TRUE)
    }
    paths <- c(paths, p)
    if (i %% 50 == 0 || i == nrow(want)) message("  downloaded ", i, "/", nrow(want))
  }
  invisible(paths)
}
