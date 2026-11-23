# The words of a report, with their numbers (text.json): the R twin of the toolkit's reporting/text.py.
# Same sentences, so a report says the same thing whichever language made the tables.

.GROUP <- list(
  images = list(device = "light trap", what = "insects", unit = "individual insects", unit_one = "individual insect",
                file = "photo", files = "photos", made = "took"),
  birds = list(device = "sound recorder", what = "birds", unit = "bird calling events", unit_one = "calling event",
               file = "recording", files = "recordings", made = "made"),
  bats = list(device = "bat detector", what = "bats", unit = "bat passes", unit_one = "bat pass",
              file = "recording", files = "recordings", made = "made"))

.CITATIONS <- c(
  birdnet = paste("BirdNET: Kahl, S., Wood, C. M., Eibl, M. & Klinck, H. (2021). BirdNET: a deep learning solution",
                  "for avian diversity monitoring. Ecological Informatics 61, 101236. Non-commercial use only."),
  perch = "Perch: Google DeepMind / Google Research, https://github.com/google-research/perch",
  batdetect = paste("BatDetect2: Mac Aodha, O. et al. (2022). Towards a general approach for bat echolocation",
                    "detection and classification. bioRxiv. Non-commercial use only."),
  flat = "flat-bug insect detector: Svenning, Geissmann et al., https://github.com/darsa-group/flat-bug",
  "moth-vs" = "Moth or not: Rolnick lab, Mila (AMI project), https://github.com/RolnickLab/ami-data-companion",
  order = paste("Insect order: Bjerge, K. et al. (2025). Towards edge processing of images from insect camera traps.",
                "Remote Sensing in Ecology and Conservation. doi:10.1002/rse2.70007"),
  "moth-species" = paste("Moth species models: The Alan Turing Institute and UKCEH, for the AMBER project.",
                         "Non-commercial use only."))

.HOW <- c(
  images = paste("A camera photographed the light trap's sheet through the night. A computer model found every insect",
                 "in each photo, a second said whether it was a moth, a third gave its insect order, and for moths a",
                 "fourth suggested the species. The same insect was then followed from photo to photo, so one moth",
                 "sitting on the sheet for an hour counts once."),
  birds = paste("A sound recorder recorded on a schedule. A computer model listened to each recording in short pieces",
                "and named the birds it heard. Calls of the same species in one recording, with pauses of up to a",
                "minute, count as one calling event."),
  bats = paste("A bat detector recorded the ultrasonic calls of passing bats. A computer model found each call and",
               "suggested the species. Calls of the same species in one recording, with pauses of up to a second,",
               "count as one bat pass."))

.CAVEAT <- paste("These identifications were made by computer models that are still in development. Treat every species",
                 "as a suggestion until an expert has checked it. The score next to each one is the model's own",
                 "confidence, not a measure of how often it is right: a low score means it was unsure, and a name from",
                 "outside the region (the models know some species that don't live here) is a sign of that too.")

.STYLE <- list(font = "Arial", ink = "#000000", ink_2 = "#4d4d4d", grid = "#e3e3e3", surface = "#ffffff",
               mint = "#D6EAE6", neutral = "#bdbdbd", main = "#133b64",
               categorical = c("#133b64", "#f4c03d", "#477AE2", "#e76124", "#67ccea", "#7f1518", "#4db264", "#cfbcd5"))

.MONTHS <- c("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December")
.long_date <- function(s) {
  d <- as.Date(substr(as.character(s), 1, 10))
  paste(as.integer(format(d, "%d")), .MONTHS[as.integer(format(d, "%m"))], format(d, "%Y"))
}
.n <- function(x) if (is.null(x) || length(x) == 0 || is.na(x)) "0" else formatC(as.integer(x), format = "d", big.mark = ",")

.model_names <- function(models) {
  m <- if (is.list(models) && !is.null(models$models)) models$models else models
  if (!is.list(m)) return(character())
  out <- character()
  for (k in names(m)) {
    v <- m[[k]]
    if (is.list(v) && !is.null(v$model)) {
      out <- c(out, paste0(v$model, if (!is.null(v$by)) paste0(", by ", v$by) else "",
                           if (!is.null(v$licence)) paste0(" (licence: ", v$licence, ")") else ""))
    } else if (k == "birdnet-analyzer" && length(v) && nzchar(v)) {
      out <- c(out, paste0("BirdNET Analyzer ", v, " (code MIT, model CC BY-NC-SA 4.0: non-commercial)"))
    } else if (k == "geo_model" && length(v) && !isFALSE(v) && nzchar(v)) {
      out <- c(out, "BirdNET's location filter (which species to expect where and when)")
    } else if (k == "batdetect2" && length(v) && nzchar(v)) {
      out <- c(out, paste0("BatDetect2 ", v, " (CC BY-NC 4.0: non-commercial)"))
    } else if (k == "perch_model" && length(v) && nzchar(v)) {
      parts <- strsplit(gsub("\\\\", "/", as.character(v)), "/")[[1]]
      parts <- parts[grepl("^(perch|bird-vocal)", tolower(parts))]
      out <- c(out, paste0("Perch, by Google DeepMind", if (length(parts)) paste0(" (", parts[length(parts)], ")") else "",
                           " (licence: Apache 2.0)"))
    }
  }
  out
}

.citations <- function(names, pipeline) {
  text <- paste(tolower(paste(names, collapse = " ")), pipeline)
  picked <- .CITATIONS[vapply(names(.CITATIONS), function(k) grepl(k, text, fixed = TRUE), TRUE)]
  if (pipeline == "images") picked <- c(picked, .CITATIONS[c("flat", "moth-vs", "order", "moth-species")])
  unname(unique(picked))
}

.build_text <- function(tables, about) {
  pipe <- about$pipeline
  g <- .GROUP[[pipe]]
  deps <- tables$deployments
  nights <- tables$nights
  species <- tables$species
  per <- list()
  for (i in seq_len(nrow(deps))) {
    d <- deps[i, ]
    n <- nights[nights$deployment_id == d$deployment_id & (if ("in_deployment" %in% names(nights)) nights$in_deployment else TRUE), , drop = FALSE]
    sp <- if (nrow(species)) species[species$deployment_id == d$deployment_id, , drop = FALSE] else species
    main <- if (pipe == "images" && nrow(sp)) sp[sp$kind != "other insect", , drop = FALSE] else sp
    lines <- character()
    if (d$nights_worked) lines <- c(lines, paste0("The ", g$device, " worked on ", d$nights_worked, " nights between ",
      .long_date(d$first_night), " and ", .long_date(d$last_night), ", for ", .n(round(d$hours_worked)), " hours in all, and ",
      g$made, " ", .n(d$files), " ", g$files, "."))
    if (d$files_failed) lines <- c(lines, paste0(.n(d$files_failed), " ", if (d$files_failed != 1) g$files else g$file, " couldn't be read."))
    lines <- c(lines, paste0("It recorded ", .n(d$individuals), " ", g$unit,
                             if (nrow(main)) paste0(" of ", .n(nrow(main)), " different ", if (pipe == "images") "moth species" else "species") else "", "."))
    if (pipe == "images" && nrow(sp)) {
      moths <- sum(sp$individuals[sp$kind == "moth"])
      others <- sp[sp$kind == "other insect", , drop = FALSE]
      others <- others[order(-others$individuals, method = "radix"), , drop = FALSE]
      if (d$individuals) lines <- c(lines, paste0(round(100 * moths / d$individuals), "% of the insects were moths",
        if (nrow(others)) paste0("; the commonest other group was ", others$taxon[1]) else "", "."))
    }
    if (nrow(n) && max(n$individuals) > 0) {
      best <- n[order(-n$individuals, method = "radix"), , drop = FALSE][1, ]
      tm <- if ("temperature_mean_c" %in% names(best)) best$temperature_mean_c else NA
      lines <- c(lines, paste0("The busiest night was ", .long_date(best$night), ", with ", .n(best$individuals), " ", g$unit,
                               if (!is.na(tm)) sprintf(" at %.0f \u00b0C on average", tm) else "", "."))
    }
    if (nrow(main)) {
      top <- utils::head(main[order(-main$individuals, method = "radix"), , drop = FALSE], 3)
      cn <- if ("common_name" %in% names(top)) top$common_name else rep(NA, nrow(top))
      nm <- ifelse(!is.na(cn) & is.character(cn), paste0(cn, " (", top$taxon, ")"), top$taxon)
      lines <- c(lines, paste0("The most often recorded were ", paste(nm[-length(nm)], collapse = ", "),
                               if (length(nm) > 1) " and " else "", nm[length(nm)], " (all still to be checked)."))
    }
    per[[d$deployment_id]] <- lines
  }
  proj <- character()
  if (nrow(deps) > 1) {
    proj <- c(proj, paste0(nrow(deps), " deployments recorded ", .n(sum(deps$individuals)), " ", g$unit, " over ",
                           .n(sum(deps$nights_worked)), " nights."))
    if (nrow(species)) {
      main <- if (pipe == "images") species[species$kind != "other insect", , drop = FALSE] else species
      at_all <- sum(tapply(main$deployment_id, main$taxon, function(x) length(unique(x))) == nrow(deps))
      proj <- c(proj, paste0("Together they recorded ", .n(length(unique(main$taxon))), " different ",
                             if (pipe == "images") "moth species" else "species", "; ", .n(at_all), " were recorded at every deployment."))
    }
  }
  names_ <- .model_names(about$models %||% list())
  w <- about$weather
  methods <- list(
    how = .HOW[[pipe]], caveat = .CAVEAT,
    night = paste("A night runs from noon to noon on the device's own clock and is named by the evening it starts.",
                  "Activity is given per hour the device was working, so nights of different lengths can be compared."),
    unit = if (!is.null(about$individual)) paste0("Counts are of ", g$unit, ": each is ", about$individual, ".") else "",
    weather = if (!is.null(w)) paste0("Weather for each night covers only the hours the device was working. ", w$credit %||% "", ".")
              else "No weather was added.",
    moon = paste("How full the moon was, and how long it was above the horizon while the device worked, are worked out",
                 "from astronomical formulas."),
    models = I(names_), citations = I(.citations(names_, pipe)), notes = I(about$notes %||% character()),
    made_with = paste0("Made with the UKCEH ceh-biomonitoring toolkit, version ", about$toolkit_version, ", on ",
                       .long_date(substr(about$made_at, 1, 10)), "."))
  list(pipeline = pipe, project = about$project, labels = g, deployments = lapply(per, I), project_summary = I(proj),
       methods = methods, style = .STYLE)
}
