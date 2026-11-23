# Changes

## Unreleased

**Uploading from R**
- `cehbio_upload()`, `cehbio_deployments()` and `cehbio_request_deployment()` in the R package, with no Python: the same questions and the same upload log as `cehbio upload`, so an upload can be started in one and finished in the other. Tested against a stand-in upload service on every push.

**Commercial or not**
- Reports and report tables need to know whether the project is commercial (`--use`, R: `use =`): asked if not given, then remembered. Commercial projects get ERA5-Land weather (with the set-up offered if there's no key) and a warning for each model licensed for non-commercial use only.

**Weather for commercial work**
- `cehbio weather-setup` (R: `cehbio_weather_setup()`) walks you through the free Copernicus account, accepting the ERA5-Land licence and saving your key, checking each step. Clear messages for a missing key, a wrong key or a licence not yet accepted. `cdsapi` is no longer needed, and a weather key no longer needs object-store keys beside it.

**Reporting in R with no Python**
- The R package makes the report tables itself, by the same rules (`tests/test_r_matches_python.py` checks they're identical, on every push). Sorting ties now break the same way in both.

**Installing**
- Nothing to install first: `install.sh` (Mac, Linux, JASMIN), `install-windows.bat` (double-click) and `cehbio_install()` in R get uv, which gets Python 3.11, and put everything in one folder (`CEHBIO_HOME`). The `cehbio` command works in any new terminal, with no `conda activate`. Reports are always included. `./install.sh --conda` keeps the old way.

## 0.3.0 (19 November 2026)

**Folders and progress**
- Results go in `~/ceh-biomonitoring-results/<pipeline>/<project>/<deployment>/`, kept apart from the code. New `--project` option. The pipeline's own files are in `working/`. Each folder has a `READ ME.txt` and a `PROGRESS.txt`.
- `cehbio status`: every run, with a progress bar, time left, parts waiting or running on the cluster, and why any stopped. `--watch` keeps checking.
- On a cluster, the results are joined automatically when the last part finishes.
- `cehbio tidy` moves results made before this version into the new folders, after asking.
- Results are also written as CSV.

**Images**
- `ring_light: auto` (on with `--device lepisense`): the ring light is found in each night's photos, and only boxes on the ring, its LED board or its screws are removed. Writes a ring file and a preview sheet. `cehbio mask rings` checks photos first.
- Photos whose file ends early are read as far as they go (`photo_repaired`).

**Clocks and labelling**
- `cehbio clock-check`: what a trap's clock kept (UTC, local, out by hours), from dusk and dawn; also nights a unit stopped early.
- Audio labelling packages: spectrograms, bat clips slowed 10 times, and an `index.html` to work through.
- Labelling projects: `--project` gives each step its own folder (`1_sample`, `2_for_experts`, `3_answers`).
- Mothbot: site names, strict ISO dates, package check uses the settings' temporary folder.

**Reports**
- `cehbio report-data`: report-ready tables (deployments, nights with weather and moon, individuals, species), the reports' words, and a copy in EntoInsights' format.
- `cehbio report`: summary reports per deployment and project, in HTML, Word and PDF.
- The `cehbio` R package (`r/`): the whole toolkit from R, from installing to reports.

## 0.2.0 (16 November 2026)

First release of the unified toolkit: birds (BirdNET, Perch), bats (BatDetect2), images, uploads, examples, manual validation.
