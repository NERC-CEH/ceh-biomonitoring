# Reporting

Reports start from one set of tables, made from a project's results by `cehbio report-data`. Reports made in Python and reports made in R both read these tables, so they give the same numbers. Everything stays in your results folder.

```bash
cehbio report-data images --project farm1 --sites sites.csv
```

This writes the tables to `ceh-biomonitoring-results/images/farm1/report/data/`, as `.csv` (opens in Excel) and `.parquet` (smaller and faster):

| Table | One row per | What's in it |
|---|---|---|
| `deployments` | deployment | first and last night, nights and hours worked, files, failed files, individuals, species, place, clock used |
| `nights` | deployment and night | first and last file, hours worked, files, failed files, individuals and individuals per hour, the moon, and the weather over the hours it was working |
| `individuals` | individual | an insect followed through photos (a track), a bird's calling event or a bat pass, with its night, name, kind and score |
| `species` | deployment and species | individuals, nights seen, first and last night, mean and best score |
| `about.json` | | models and versions, weather source and its credit, and every assumption made (e.g. which clock) |
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
| `start`, `end` | when the unit went out and came in. Nights outside them, such as set-up tests in daylight, stay in the nights table marked `in_deployment = False`, and are left out of the individuals, species and totals |

## Weather

The weather for each night covers **only the hours the device was working**: mean and lowest temperature, temperature at the start, rain (total and hours with rain), wind, cloud and humidity.

| `--weather` | Detail | Use | Needs |
|---|---|---|---|
| `open-meteo` (default) | from 2022, the finest weather model for the place (in the UK the Met Office's 2 km model); before 2022, ERA5 (about 25 km) | **non-commercial only** on the free service | internet |
| `era5-land` | ECMWF's ERA5-Land, about 9 km, from 1950, about 5 days behind. No cloud cover | **any use, commercial included**, if credited | a free [Copernicus CDS](https://cds.climate.copernicus.eu) account: add `"CDSAPI_KEY"` to your credentials file, and `pip install cdsapi` |
| `none` | | | |

The weather is cached in your model cache, so running the report again doesn't fetch it again. `about.json` holds the credit line to put in reports.

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
