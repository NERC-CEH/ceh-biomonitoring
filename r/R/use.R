# Commercial or not: the R twin of the toolkit's reporting/use.py (same rules, same words).
#   noncommercial  weather from Open-Meteo (free for non-commercial use)
#   commercial     weather from ERA5-Land (needs your own free Copernicus key: cehbio_weather_setup()), and
#                  a warning for any model licensed for non-commercial use only
# Asked if not given, then remembered for the project (report/data/about.json).

.USES <- c("commercial", "noncommercial")
.USE_EXPLAIN <- paste(
  "Is this a commercial project (work for a paying client or business)? It decides what the report may use:",
  "non-commercial projects get weather from Open-Meteo; commercial ones get ERA5-Land weather (needs a free",
  "Copernicus key, set up once) and a warning for any model licensed for non-commercial use only.")
.NC_MODELS <- list(list(words = "birdnet", label = "BirdNET (its model is CC BY-NC-SA 4.0)"),
                   list(words = "batdetect", label = "BatDetect2 (CC BY-NC 4.0)"),
                   list(words = c("moth-species", "moth_species", "regional species"),
                        label = "the moth species models (CC BY-NC 4.0)"))

.yes_no <- function(prompt) {
  repeat {
    a <- tolower(trimws(readline(prompt)))
    if (a %in% c("y", "yes")) return(TRUE)
    if (a %in% c("n", "no")) return(FALSE)
    message("Please type yes or no.")
  }
}

.decide_use <- function(given, out) {
  if (!is.null(given)) {
    g <- gsub("[-_ ]", "", tolower(given))
    if (!g %in% .USES) stop("use must be \"commercial\" or \"noncommercial\", not '", given, "'.", call. = FALSE)
    return(g)
  }
  f <- file.path(out, "about.json")
  before <- if (file.exists(f)) tryCatch(jsonlite::fromJSON(f)$use, error = function(e) NULL) else NULL
  if (!is.null(before) && before %in% .USES) {
    message("  This project is ", before, " (as before). Give use = to change it.")
    return(before)
  }
  if (!interactive()) stop("Say whether this project is commercial: use = \"commercial\" or \"noncommercial\" ",
                           "(in a terminal: --use commercial or --use noncommercial). ", .USE_EXPLAIN, call. = FALSE)
  message(.USE_EXPLAIN)
  if (.yes_no("Commercial project? (yes/no): ")) "commercial" else "noncommercial"
}

.weather_for <- function(use, weather) {
  if (identical(weather, "none")) return("none")
  if (use == "noncommercial") return(weather %||% "open-meteo")
  if (identical(weather, "open-meteo"))
    stop("This is a commercial project, and Open-Meteo's free weather is for non-commercial use only. ",
         "Use weather = \"era5-land\" (or weather = \"none\").", call. = FALSE)
  if (!is.null(.cds_saved_key())) return("era5-land")
  message("\nCommercial project: the weather comes from ERA5-Land, which needs your own free Copernicus key, and ",
          "there isn't one on this computer yet.")
  if (!interactive()) stop("No Copernicus key yet. ", .CDS_HOW_TO, " Or use weather = \"none\" for a report without weather.",
                           call. = FALSE)
  if (.yes_no("Set it up now? It takes about 5 minutes. (yes/no): ")) {
    cehbio_weather_setup()
    if (!is.null(.cds_saved_key())) return("era5-land")
  }
  if (.yes_no("Make the tables without weather for now? You can add it later with refresh = TRUE. (yes/no): ")) return("none")
  stop("Stopped. ", .CDS_HOW_TO, call. = FALSE)
}

.licence_notes <- function(use, model_names, pipeline) {
  if (use != "commercial") return(character())
  text <- paste(tolower(paste(model_names, collapse = " ")), pipeline)
  hit <- character()
  for (m in .NC_MODELS) if (any(vapply(m$words, function(w) grepl(w, text, fixed = TRUE), TRUE))) hit <- c(hit, m$label)
  if (pipeline == "images" && !.NC_MODELS[[3]]$label %in% hit) hit <- c(hit, .NC_MODELS[[3]]$label)
  if (pipeline == "bats" && !.NC_MODELS[[2]]$label %in% hit) hit <- c(hit, .NC_MODELS[[2]]$label)
  if (!length(hit)) return(character())
  paste0("Commercial project: ", hit, " is licensed for non-commercial use only. Check with its makers before using ",
         "these results commercially.")
}
