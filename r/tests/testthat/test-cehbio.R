fake_project <- function() {
  root <- file.path(tempfile("cehbio"), "results")
  data <- file.path(root, "images", "farm", "report", "data")
  dir.create(data, recursive = TRUE)
  utils::write.csv(data.frame(deployment_id = "trap-1", first_night = "2026-05-11", last_night = "2026-05-12",
                              nights_worked = 2, hours_worked = 9, files = 300, files_failed = 1, individuals = 40,
                              taxa = 3), file.path(data, "deployments.csv"), row.names = FALSE)
  utils::write.csv(data.frame(deployment_id = "trap-1", night = c("2026-05-11", "2026-05-12"), hours_worked = c(4, 5),
                              files = c(140, 160), individuals = c(10, 30), individuals_per_hour = c(2.5, 6),
                              in_deployment = c(TRUE, TRUE), temperature_mean_c = c(9.5, 12)),
                   file.path(data, "nights.csv"), row.names = FALSE)
  utils::write.csv(data.frame(deployment_id = "trap-1", kind = c("moth", "moth", "other insect"),
                              taxon = c("Noctua pronuba", "Biston betularia", "Diptera Brachycera"),
                              individuals = c(25, 5, 10), nights = c(2, 1, 2), first_night = "2026-05-11",
                              last_night = "2026-05-12", score_mean = c(0.9, 0.6, NA)),
                   file.path(data, "species.csv"), row.names = FALSE)
  utils::write.csv(data.frame(deployment_id = "trap-1", unit_id = "a", taxon = "Noctua pronuba"),
                   file.path(data, "individuals.csv"), row.names = FALSE)
  jsonlite::write_json(list(pipeline = "images", project = "farm", labels = list(unit = "individual insects"),
                            style = list(main = "#133b64")), file.path(data, "text.json"), auto_unbox = TRUE)
  root
}

test_that("report tables are read, with nights as dates", {
  withr_root <- fake_project()
  old <- options(cehbio.results = withr_root)
  on.exit(options(old))
  d <- read_report_data("images", "farm")
  expect_equal(nrow(d$nights), 2)
  expect_s3_class(d$nights$night, "Date")
  expect_equal(d$text$labels$unit, "individual insects")
  expect_error(read_report_data("bats", "farm"), "cehbio_report_data")
})

test_that("the charts are drawn in the report's colours", {
  skip_if_not_installed("ggplot2")
  old <- options(cehbio.results = fake_project())
  on.exit(options(old))
  d <- read_report_data("images", "farm")
  expect_s3_class(plot_working(d, "trap-1"), "ggplot")
  expect_s3_class(plot_activity(d, "trap-1"), "ggplot")
  expect_s3_class(plot_temperature(d, "trap-1"), "ggplot")
  g <- plot_groups(d, "trap-1")
  expect_setequal(as.character(g$data$label), c("Moths", "Diptera Brachycera"))
  expect_equal(report_style(d)$main, "#133b64")
})

test_that("options become command-line flags", {
  expect_equal(cehbio:::.opt("project", "woods"), c("--project", "woods"))
  expect_equal(cehbio:::.opt("here", TRUE), "--here")
  expect_length(cehbio:::.opt("device", NULL), 0)
})

test_that("R drives the Python toolkit", {
  py <- Sys.getenv("CEHBIO_TEST_PYTHON")
  skip_if(!nzchar(py), "set CEHBIO_TEST_PYTHON to a python with the toolkit installed")
  old <- options(cehbio.python = py)
  on.exit(options(old))
  out <- cehbio("pipelines", echo = FALSE)
  expect_true(any(grepl("birds", out)))
  expect_true(nzchar(results_folder()))
})
