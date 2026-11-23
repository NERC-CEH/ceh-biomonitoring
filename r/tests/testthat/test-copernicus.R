test_that("a key that isn't one is caught before asking Copernicus", {
  r <- cehbio:::.cds_check("my password")
  expect_equal(r$state, "bad key")
  expect_match(r$msg, "API Token")
})

test_that("saving the weather key keeps the other credentials", {
  f <- tempfile(fileext = ".json")
  withr_env <- Sys.getenv(c("CEHBIO_CREDENTIALS", "CDSAPI_KEY"), unset = NA)
  on.exit(for (n in names(withr_env)) if (is.na(withr_env[[n]])) Sys.unsetenv(n) else do.call(Sys.setenv, setNames(list(withr_env[[n]]), n)))
  Sys.setenv(CEHBIO_CREDENTIALS = f)
  Sys.unsetenv("CDSAPI_KEY")
  jsonlite::write_json(list(AWS_ACCESS_KEY_ID = "a"), f, auto_unbox = TRUE)
  key <- "0123abcd-4567-89ab-cdef-0123456789ab"
  cehbio:::.cds_save_key(key)
  saved <- jsonlite::fromJSON(f)
  expect_equal(saved$AWS_ACCESS_KEY_ID, "a")
  expect_equal(saved$CDSAPI_KEY, key)
  expect_equal(cehbio:::.cds_saved_key(), key)
})

test_that("checking with no key saved points to the walkthrough", {
  old <- Sys.getenv(c("CEHBIO_CREDENTIALS", "CDSAPI_KEY"), unset = NA)
  on.exit(for (n in names(old)) if (is.na(old[[n]])) Sys.unsetenv(n) else do.call(Sys.setenv, setNames(list(old[[n]]), n)))
  Sys.setenv(CEHBIO_CREDENTIALS = tempfile())
  Sys.unsetenv("CDSAPI_KEY")
  expect_message(ok <- cehbio_weather_setup(check = TRUE), "cehbio_weather_setup")
  expect_false(ok)
})
