# Reporting

Reports start from one set of tables, made from a project's results by `cehbio report-data` (Python) or `cehbio_report_data()` (R, with no Python needed). Both make identical tables by the same rules, and the same words, so the reports say the same thing whichever you use. Everything stays in your results folder.

## Summary reports

| Python | R ([using the toolkit from R](r.md)) |
|---|---|
| `cehbio report images --project farm1 --sites sites.csv` | `cehbio_report("images", "farm1", sites = "sites.csv")` |

Add `--format html docx pdf` (Python) or `formats = c("html", "docx", "pdf")` (R) for Word and PDF as well. Word and PDF need [Quarto](https://quarto.org), which the installer gets for you (`./install.sh`, `install-windows.bat` or `cehbio_install()` in R). PDF uses Quarto's own engine; where a managed laptop blocks that, the Word version is turned into a PDF by Microsoft Word, or by LibreOffice. `--reference-doc` / `reference_doc =` gives a Word file whose styles to use.

Both write one self-contained HTML page per deployment, and one for the project, to `ceh-biomonitoring-results/images/farm1/report/`. They describe what was recorded; they don't interpret it or compare it with other places. Each covers:

- a warning that the identifications are the models' suggestions;
- a summary: nights and hours working, individuals, species, and plain-language headlines;
- when the device was working, and activity per hour, with the night's temperature in its own chart below;
- what was recorded: insect groups (images), and the 20 most often recorded species, with a table and the full list to download;
- how it was done: the method, what an individual is, the night, the weather source and its credit, the models used and what to cite, and any assumptions.

The reports never show the user or computer names kept in the run records. Add `--refresh` (Python) or `refresh = TRUE` (R) after new results, to remake the tables first.

## The tables

```bash
cehbio report-data images --project farm1 --sites sites.csv
```

(`cehbio report` makes them for you the first time.) This writes the tables to `ceh-biomonitoring-results/images/farm1/report/data/`, as `.csv` (opens in Excel) and `.parquet` (smaller and faster):

| Table | One row per | What's in it |
|---|---|---|
| `deployments` | deployment | first and last night, nights and hours worked, files, failed files, individuals, species, place, clock used |
| `nights` | deployment and night | first and last file, hours worked, files, failed files, individuals and individuals per hour, the moon, and the weather over the hours it was working |
| `individuals` | individual | an insect followed through photos (a track), a bird's calling event or a bat pass, with its night, name, kind and score |
| `species` | deployment and species | individuals, nights seen, first and last night, mean and best score |
| `about.json` | | models and versions, weather source and its credit, and every assumption made (e.g. which clock) |
| `text.json` | | the reports' words with their numbers, and the colours, shared by the Python and R reports |
| `entoinsights/` | | the results in [EntoInsights](https://github.com/AMI-system/EntoInsights)' format, so its R functions work on them too |

**An individual** is the same unit that [manual validation](validation.md) uses:

- **images:** a track, so one moth sitting on the sheet for an hour counts once;
- **birds:** a species calling in one recording, with pauses of up to 60 s;
- **bats:** a pass, with pauses of up to 1 s.

**A night** runs from noon to noon on the device's own clock and is named by the evening it starts, as in the pipelines.

## The sites file

Weather and the moon need to know where each deployment was. The results may already say so (`latitude`, `longitude`). If not, give a `--sites` CSV:

```csv
deployment,latitude,longitude,timezone,clock,start,end
dep000123,51.60,-1.12,Europe/London,UTC,2026-05-11,2026-09-10
```

| Column | |
|---|---|
| `deployment`, `latitude`, `longitude` | where it was |
| `timezone` | e.g. `Europe/London`, `Asia/Singapore` |
| `clock` | what the device's clock kept: `UTC`, `local`, or an offset like `+08:00`. Leave it out and `cehbio clock-check` decides where it can ([Recorders](recorders.md#checking-a-light-traps-clock)); otherwise local time is assumed, and `about.json` says so |
| any other columns | e.g. `country` (England, Wales, Scotland, Northern Ireland: used for priority species lists in the in-house reports), `habitat`, `site_name`. They're kept in the deployments table |
| `start`, `end` | when the unit went out and came in. Nights outside them, such as set-up tests in daylight, stay in the nights table marked `in_deployment = False`, and are left out of the individuals, species and totals |

## Weather

The weather for each night covers **only the hours the device was working**: mean and lowest temperature, temperature at the start, rain (total and hours with rain), wind, cloud and humidity.

| `--weather` | Detail | Use | Needs |
|---|---|---|---|
| `open-meteo` (default) | from 2022, the finest weather model for the place (in the UK the Met Office's 2 km model); before 2022, ERA5 (about 25 km) | **non-commercial only** on the free service | internet |
| `era5-land` | ECMWF's ERA5-Land, about 9 km, from 1950, about 5 days behind. No cloud cover | **any use, commercial included**, if credited (CC BY 4.0) | your own free Copernicus key, set up once: [see below](#weather-for-commercial-work-era5-land) |
| `none` | | | |

The weather is cached in your model cache, so running the report again doesn't fetch it again. `about.json` holds the credit line to put in reports.

### Weather for commercial work (ERA5-Land)

Open-Meteo's free service is for non-commercial work only. For commercial reports, use `--weather era5-land` (in R: `weather = "era5-land"`). ERA5-Land is free for any use, but each person needs their **own** free Copernicus account and key. You set it up once, in about 5 minutes, and the toolkit walks you through it and checks each step:

```bash
cehbio weather-setup
```
```r
cehbio::cehbio_weather_setup()
```

The three steps it takes you through:

1. **Make a free account** at [cds.climate.copernicus.eu](https://cds.climate.copernicus.eu): **Login - Register** (top right). Confirm the email they send.
2. **Accept the ERA5-Land licence, once.** On the [ERA5-Land time series page](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-timeseries?tab=download), logged in, go to the **Download** tab, scroll to the bottom, and under **Terms of use** click **Accept** (it's the CC-BY licence). Without this, Copernicus refuses every request, even with a good key.
3. **Copy your key**: on [your profile page](https://cds.climate.copernicus.eu/profile), copy the **API Token** and paste it when asked. It stays hidden as you paste it.

It checks the key and the licence with Copernicus, then saves the key privately as `CDSAPI_KEY` in your credentials file (`~/.config/ceh-biomonitoring/credentials.json`), where both Python and R find it. It's never shown on screen. To check it later: `cehbio weather-setup --check` (in R: `cehbio_weather_setup(check = TRUE)`).

Then make the tables or reports as usual, with ERA5-Land:

```bash
cehbio report-data images --project farm1 --sites sites.csv --weather era5-land
```
```r
cehbio_report("images", "farm1", sites = "sites.csv", weather = "era5-land")
```

Each site's weather takes a minute or two the first time (Copernicus queues requests), then it's kept. If something's wrong, the message says what to do: no key yet, a key Copernicus doesn't accept, or a licence not yet accepted. **Accounts are personal: please don't share a key.** The credit line for reports is in `about.json`.

**The moon:** each night has how full the moon was (`moon_illumination`, 0 new to 1 full), and the share of the working hours it was above the horizon (`moon_up_share`).

## With EntoInsights (R)

```r
library(EntoInsights)
w <- wrangle_results("ceh-biomonitoring-results/images/farm1/report/data/entoinsights/dep000123_combined_results.csv",
                     taxa = "moth")
plot_device_operation_calendar(w)
get_top_species_total(moths_only(w), n = 10)
```

Two things to know:

- **Nights operating:** EntoInsights only counts nights with at least 10 photos (`calculate_device_operation`), so short nights, such as when a unit stopped early, aren't counted there. The `nights` table keeps them and says how many hours each worked.
- **Bird results:** EntoInsights reads BirdNET only. It takes the date from the first 15 characters of the file name, which works for AudioMoth names.
