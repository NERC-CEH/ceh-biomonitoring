"""Hourly weather at a site, summarised over the hours a trap or recorder was actually working.

Two sources (--weather):

  open-meteo  (default) Open-Meteo's historical weather: for 2022 on, the finest weather model it has for
              the place (in the UK the Met Office's 2 km model), earlier years ERA5 (about 25 km).
              Free for NON-COMMERCIAL use only; data CC BY 4.0 (credit: Open-Meteo.com and the weather
              services behind it). https://open-meteo.com
  era5-land   ECMWF's ERA5-Land reanalysis from the Copernicus Climate Data Store: about 9 km, from 1950,
              about 5 days behind. Free for any use, commercial included, if credited ("Contains modified
              Copernicus Climate Change Service information"). Needs your own free Copernicus key, set
              up once with `cehbio weather-setup` (see copernicus.py). No cloud cover in ERA5-Land.

Hourly values are cached in <models cache>/weather/, so re-running a report doesn't ask again.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

VARIABLES = ["temperature_c", "precipitation_mm", "wind_speed_ms", "cloud_cover_pct", "relative_humidity_pct"]
SOURCES = {
    "open-meteo": {"licence": "CC BY 4.0; free API for non-commercial use only",
                   "credit": "Weather data by Open-Meteo.com (Met Office, ECMWF and other national weather services)",
                   "commercial": False},
    "era5-land": {"licence": "Copernicus licence: free for any use, commercial included, with credit",
                  "credit": "Contains modified Copernicus Climate Change Service information (ERA5-Land, ECMWF)",
                  "commercial": True},
}


def cache_dir(settings) -> Path:
    d = Path(settings.get("models.cache_dir") or "~/.cache/ceh-biomonitoring/models").expanduser() / "weather"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_json(url: str, params: dict) -> dict:
    import urllib.parse
    import urllib.request
    q = url + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "ceh-biomonitoring"}),
                                timeout=60) as r:
        return json.loads(r.read().decode())


def open_meteo(lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
    """Hourly UTC weather from Open-Meteo: the high-resolution archive from 2022, ERA5 before."""
    hourly = "temperature_2m,precipitation,wind_speed_10m,cloud_cover,relative_humidity_2m"
    frames = []
    spans = []
    if start < date(2022, 1, 1):
        spans.append(("https://archive-api.open-meteo.com/v1/archive", start, min(end, date(2021, 12, 31)), "era5"))
    if end >= date(2022, 1, 1):
        spans.append(("https://historical-forecast-api.open-meteo.com/v1/forecast", max(start, date(2022, 1, 1)), end,
                      "best_match"))
    for url, a, b, model in spans:
        js = _get_json(url, {"latitude": round(lat, 4), "longitude": round(lon, 4), "start_date": a.isoformat(),
                             "end_date": b.isoformat(), "hourly": hourly, "timezone": "GMT", "wind_speed_unit": "ms",
                             "models": model})
        h = js.get("hourly") or {}
        if not h.get("time"):
            continue
        frames.append(pd.DataFrame({
            "time_utc": pd.to_datetime(h["time"]), "temperature_c": h.get("temperature_2m"),
            "precipitation_mm": h.get("precipitation"), "wind_speed_ms": h.get("wind_speed_10m"),
            "cloud_cover_pct": h.get("cloud_cover"), "relative_humidity_pct": h.get("relative_humidity_2m"),
            "weather_model": model}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["time_utc", *VARIABLES])


def era5_land(lat: float, lon: float, start: date, end: date, key: str) -> pd.DataFrame:
    """Hourly UTC weather from ERA5-Land point time series (Copernicus CDS: see copernicus.py)."""
    from .copernicus import fetch
    df = fetch(lat, lon, start.isoformat(), end.isoformat(), key)
    if df is None or not len(df) or "t2m" not in df.columns:
        return pd.DataFrame(columns=["time_utc", *VARIABLES])
    df["time_utc"] = pd.to_datetime(df["time_utc"]).dt.tz_localize(None)
    df = df.sort_values("time_utc").reset_index(drop=True)
    t = df.get("t2m") - 273.15
    d = df.get("d2m") - 273.15
    out = pd.DataFrame({"time_utc": df["time_utc"], "temperature_c": t})
    out["relative_humidity_pct"] = 100 * (pd.Series(map(math.exp, 17.625 * d / (243.04 + d)))
                                          / pd.Series(map(math.exp, 17.625 * t / (243.04 + t)))).clip(upper=100)
    # ERA5-Land precipitation accumulates from 00 UTC: hourly amounts are the differences
    tp = df.get("tp") * 1000
    out["precipitation_mm"] = tp.diff().where(df["time_utc"].dt.hour != 1, tp).clip(lower=0)
    out["wind_speed_ms"] = (df.get("u10") ** 2 + df.get("v10") ** 2) ** 0.5
    out["cloud_cover_pct"] = float("nan")
    out["weather_model"] = "era5-land"
    return out.sort_values("time_utc").reset_index(drop=True)


def hourly(settings, source: str, lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
    """Hourly UTC weather for a site and dates, from the cache where possible."""
    if source not in SOURCES:
        raise SystemExit(f"Unknown weather source '{source}'. Choose from: {', '.join(SOURCES)}, or none")
    f = cache_dir(settings) / f"{source}_{lat:.3f}_{lon:.3f}_{start}_{end}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    if source == "open-meteo":
        df = open_meteo(lat, lon, start, end)
    else:
        from .copernicus import HOW_TO, saved_key
        key = saved_key(settings)
        if not key:
            raise SystemExit(f"ERA5-Land weather needs your own free Copernicus key. {HOW_TO}")
        df = era5_land(lat, lon, start, end, key)
    if len(df) and end < date.today() - timedelta(days=7):      # recent days may still be filled in later
        df.to_parquet(f, index=False)
    return df


def over(hours: pd.DataFrame, start_utc, end_utc) -> dict:
    """The weather over one spell of work: mean, minimum and total where they make sense."""
    a, b = pd.Timestamp(start_utc).floor("h"), pd.Timestamp(end_utc).ceil("h")
    h = hours[(hours["time_utc"] >= a) & (hours["time_utc"] <= b)]
    if h.empty:
        return {}
    out = {"temperature_mean_c": h["temperature_c"].mean(), "temperature_min_c": h["temperature_c"].min(),
           "temperature_at_start_c": h["temperature_c"].iloc[0], "precipitation_total_mm": h["precipitation_mm"].sum(),
           "rain_hours": int((h["precipitation_mm"] >= 0.1).sum()), "wind_speed_mean_ms": h["wind_speed_ms"].mean(),
           "cloud_cover_mean_pct": h["cloud_cover_pct"].mean(),
           "relative_humidity_mean_pct": h["relative_humidity_pct"].mean()}
    return {k: (round(float(v), 2) if isinstance(v, float) and not math.isnan(v) else (None if isinstance(v, float) else v))
            for k, v in out.items()}
