# cehbio 0.3.0

- `use = "commercial"` or `"noncommercial"` in `cehbio_report_data()` and `cehbio_report()`: asked if not
  given, then remembered for the project. Decides the weather and licence warnings.
- `cehbio_weather_setup()`: walks you through setting up ERA5-Land weather for commercial reports (a free
  Copernicus account, the licence, your key), checks each step, and saves the key privately.
- The report tables are made in R (`cehbio_report_data()`), with no Python: the same tables, numbers and
  words as Python's `cehbio report-data`, checked by a test. `engine = "python"` uses Python instead.
  Reports from R need no Python at all; `cehbio_install("reports")` installs no Python.
- Reads .parquet with nanoparquet (small, no other dependencies) instead of arrow.
- `cehbio_install()` needs nothing installed first: it gets uv, which gets Python 3.11, and installs the
  toolkit into its own folder (`cehbio_home()`); it also gets Quarto and the R packages reports use, and
  makes the `cehbio` terminal command. No Miniforge, conda or admin rights. Old conda installs still work.
- `cehbio_uv()`, `cehbio_quarto()`, `cehbio_home()`.

# cehbio 0.2.0

- Reports in Word and PDF as well as HTML (`formats =`), with a Word template (`reference_doc =`).
- Matches ceh-biomonitoring 0.3.0.

# cehbio 0.1.0

- First version: `cehbio_install()`, `cehbio_run()`, `cehbio_status()`, `read_results()`, `read_report_data()`, the report charts, and `cehbio_report()`.
