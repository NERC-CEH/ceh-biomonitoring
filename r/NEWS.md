# cehbio 0.3.0

- `cehbio_install()` needs nothing installed first: it gets uv, which gets Python 3.11, and installs the
  toolkit into its own folder (`cehbio_home()`); it also gets Quarto and the R packages reports use, and
  makes the `cehbio` terminal command. No Miniforge, conda or admin rights. Old conda installs still work.
- `cehbio_uv()`, `cehbio_quarto()`, `cehbio_home()`.

# cehbio 0.2.0

- Reports in Word and PDF as well as HTML (`formats =`), with a Word template (`reference_doc =`).
- Matches ceh-biomonitoring 0.3.0.

# cehbio 0.1.0

- First version: `cehbio_install()`, `cehbio_run()`, `cehbio_status()`, `read_results()`, `read_report_data()`, the report charts, and `cehbio_report()`.
