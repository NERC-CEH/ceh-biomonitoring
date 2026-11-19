"""cehbio clock-check: what time a trap's or recorder's clock was keeping, from when it worked each night.

A light trap (AMI, LepiSense) starts around dusk and stops around dawn. The times in its file names are
whatever its clock said. So, night by night, the first photo is compared with civil dusk (sun 6 degrees
below the horizon) and the last photo with civil dawn, worked out for the site's latitude and longitude.

    clock keeps UTC          first photos sit at the same distance from dusk in UTC all season
    clock keeps local time   ... from dusk in local time: the gap jumps by an hour when the clocks change
    clock is out             some other steady gap, e.g. +8 h (a camera set up in another country)
    clock jumped             nights where the gap changes suddenly (a reset, a flat battery)

It also lists nights the unit stopped well before its usual time (a flat battery, a full memory card)
and spells of photos that weren't a night's trapping (set-up tests in daylight). If the nights don't
cross a change of the clocks, a UTC clock and a local one can look the same; it then says so, with what
each would mean, rather than guessing.

It assumes the trap starts at dusk. If the first photos don't follow dusk (e.g. a trap run on a fixed
schedule, 21:00 to 05:00 on its clock), it says so and can't tell. Times are never changed: this only
reports. Record what you find with the deployment, e.g. --clock-timezone UTC when labelling.

    cehbio clock-check --folder E:/trap_photos --lat 51.60 --lon -1.12 --timezone Europe/London
    cehbio clock-check --results ~/ceh-biomonitoring-results/images/farm1/dep000123 --lat 51.60 --lon -1.12
    cehbio clock-check --bucket gbr --deployment dep000123 --lat 51.60 --lon -1.12 --timezone Europe/London
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

DUSK = 96.0              # civil twilight: the sun 6 degrees below the horizon (zenith 96)
JUMP_MIN = 40            # a gap this much different from the nights either side is a jump
FOLLOWS_DUSK_IQR_MIN = 45


def sun_time(day: date, lat: float, lon: float, rising: bool, zenith: float = DUSK) -> datetime | None:
    """UTC time the sun crosses `zenith` on `day` (morning if rising, evening if not), to a minute or two.
    None when it doesn't (no darkness at midsummer near the poles). NOAA's almanac method."""
    n = day.timetuple().tm_yday
    lng_hour = lon / 15
    t = n + ((6 if rising else 18) - lng_hour) / 24
    m = 0.9856 * t - 3.289
    L = (m + 1.916 * math.sin(math.radians(m)) + 0.020 * math.sin(math.radians(2 * m)) + 282.634) % 360
    ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(L)))) % 360
    ra = (ra + (math.floor(L / 90) * 90 - math.floor(ra / 90) * 90)) / 15
    sin_dec = 0.39782 * math.sin(math.radians(L))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(zenith)) - sin_dec * math.sin(math.radians(lat))) / (
        cos_dec * math.cos(math.radians(lat)))
    if not -1 <= cos_h <= 1:
        return None
    h = (360 - math.degrees(math.acos(cos_h)) if rising else math.degrees(math.acos(cos_h))) / 15
    ut = (h + ra - 0.06571 * t - 6.622 - lng_hour) % 24
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(hours=ut)


SESSION_GAP_H = 3        # a pause this long starts a new night's work


def nights(clock_times: pd.Series) -> pd.DataFrame:
    """First and last file of each spell of work, on the device's clock. A spell ends at a pause of 3 hours
    or more, not at noon: if the clock is far out, a night's photos can run across noon on that clock."""
    t = pd.to_datetime(pd.Series(clock_times), errors="coerce").dropna().sort_values().reset_index(drop=True)
    spell = (t.diff() > pd.Timedelta(hours=SESSION_GAP_H)).cumsum()
    g = pd.DataFrame({"t": t, "spell": spell}).groupby("spell")["t"]
    out = pd.DataFrame({"first": g.min(), "last": g.max(), "files": g.size()}).reset_index(drop=True)
    out["night"] = out["first"].dt.date
    return out


def _h(td) -> float:
    return td.total_seconds() / 3600


def check(clock_times: pd.Series, lat: float, lon: float, tz: str | None = None, min_files: int = 5) -> dict:
    """The clock verdict and a table of nights."""
    n = nights(clock_times)
    n = n[n["files"] >= min_files].copy()
    if n.empty:
        return {"verdict": "not enough nights with photos to tell", "nights": n}
    zone = None
    if tz:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(tz)
    rows = []
    for r in n.itertuples():
        first = r.first.to_pydatetime().replace(tzinfo=timezone.utc)      # the clock's reading, as if UTC
        last = r.last.to_pydatetime().replace(tzinfo=timezone.utc)
        # the dusk nearest the first photo, and the dawn nearest the last (the clock may be hours out)
        dusks = [d for d in (sun_time(r.night + timedelta(days=k), lat, lon, rising=False) for k in (-1, 0, 1)) if d]
        dawns = [d for d in (sun_time(r.night + timedelta(days=k), lat, lon, rising=True) for k in (0, 1, 2)) if d]
        dusk = min(dusks, key=lambda d: abs(first - d)) if dusks else None
        dawn = min(dawns, key=lambda d: abs(last - d)) if dawns else None
        if dusk:
            r = r._replace(night=dusk.date())
        local = _h(zone.utcoffset(datetime.combine(r.night, datetime.min.time()).replace(hour=22))) if zone else None
        rows.append({"night": r.night.isoformat(), "files": r.files,
                     "first_on_clock": r.first.strftime("%H:%M"), "last_on_clock": r.last.strftime("%H:%M"),
                     "civil_dusk_utc": dusk.strftime("%H:%M") if dusk else "", "civil_dawn_utc": dawn.strftime("%H:%M") if dawn else "",
                     "first_minus_dusk_h": round(_h(first - dusk), 2) if dusk else None,
                     "last_minus_dawn_h": round(_h(last - dawn), 2) if dawn else None,
                     "local_utc_offset_h": local})
    t = pd.DataFrame(rows)
    if t["first_minus_dusk_h"].dropna().empty:
        return {"verdict": "no dusk at this latitude on these dates: can't tell", "nights": t}
    # spells of work far from dusk aren't a night's trapping (a daytime test, a stray trigger)
    t["kind"] = "night"
    t.loc[(t["first_minus_dusk_h"] - t["first_minus_dusk_h"].median()).abs() > 3, "kind"] = "not at dusk (a test?)"
    night = t["kind"] == "night"
    gap = t.loc[night, "first_minus_dusk_h"].dropna()
    end = t.loc[night, "last_minus_dawn_h"]
    t["stopped_early"] = night & ((end.median() - t["last_minus_dawn_h"]) > STOPPED_EARLY_H)
    roll = gap.rolling(5, center=True, min_periods=3).median()
    t["jump"] = ((gap - roll).abs() * 60 > JUMP_MIN).reindex(t.index, fill_value=False)
    spread = lambda s: float((s.quantile(0.75) - s.quantile(0.25)) * 60)   # noqa: E731 - minutes
    out = {"nights": t, "n_nights": int(len(gap)), "gap_median_h": round(float(gap.median()), 2),
           "gap_spread_min": round(spread(gap))}
    local = t.loc[gap.index, "local_utc_offset_h"] if zone else None
    changes = zone is not None and local.nunique() > 1
    if changes:                                   # the nights cross a clock change: this decides it
        s_utc, s_local = spread(gap), spread(gap - local)
        if min(s_utc, s_local) > FOLLOWS_DUSK_IQR_MIN:
            out["verdict"] = _fixed(min(s_utc, s_local))
        elif s_local < s_utc:
            d = float((gap - local).median())
            if START_EARLIEST_H <= d <= START_LATEST_H:
                out.update(clock="local", verdict=f"the clock keeps local time ({tz}), changing with the clocks: "
                                                  f"the first photos keep step with dusk in local time across the "
                                                  f"change, starting {_mins(d)} civil dusk")
            else:
                out.update(clock=f"local {round(d):+d} h", verdict=(
                    f"the clock changes with the clocks ({tz}) but is about {abs(round(d))} h "
                    f"{'ahead' if d > 0 else 'behind'}, if the unit starts near dusk: it was probably set wrongly"))
        else:
            g = float(gap.median())
            if START_EARLIEST_H <= g <= START_LATEST_H:
                out.update(clock="UTC", verdict=f"the clock keeps UTC: the first photos keep step with dusk in UTC "
                                                f"across the change of the clocks, starting {_mins(g)} civil dusk")
            else:
                out.update(clock=_fmt(round(g)), verdict=(
                    f"the clock is about {_fmt(round(g))} (it doesn't change with the clocks), if the unit starts "
                    f"near dusk: that's neither UTC nor local time ({tz}). It was probably set up somewhere else, "
                    f"or set wrongly"))
    elif spread(gap) > FOLLOWS_DUSK_IQR_MIN:
        out["verdict"] = _fixed(spread(gap))
    else:
        g = float(gap.median())
        cands = {"UTC": 0.0}
        if zone and float(local.iloc[0]) != 0:
            cands[f"local time ({tz}, {_fmt(float(local.iloc[0]))})"] = float(local.iloc[0])
        fits = {name: g - x for name, x in cands.items() if START_EARLIEST_H <= g - x <= START_LATEST_H}
        if len(fits) == 1:
            name, delay = next(iter(fits.items()))
            out.update(clock="UTC" if name == "UTC" else "local",
                       verdict=f"the clock keeps {name}: the unit starts {_mins(delay)} civil dusk")
        elif len(fits) > 1:
            out.update(clock=None, verdict=(
                "the first photos follow dusk closely, but these nights can't tell which clock: "
                + "; or ".join(f"if it keeps {n}, the unit starts {_mins(d)} civil dusk" for n, d in fits.items())
                + ". The nights don't cross a change of the clocks, which would settle it. Check one photo against "
                  "a known time instead (when the unit was switched on, or a photo of a phone's clock)"))
        else:
            off = round(g)
            out.update(clock=_fmt(off), verdict=(
                f"the clock is about {_fmt(off)}, if the unit starts near dusk: that's neither UTC nor local time"
                + (f" ({tz})" if tz else "") + ". It was probably set up somewhere else, or set wrongly"))
        if not zone and out.get("clock") == "UTC":
            out["verdict"] += ". Give --timezone to check it against local time too"
    if t["jump"].any():
        out["jumps"] = t.loc[t["jump"], "night"].tolist()
    if t["stopped_early"].any():
        out["stopped_early"] = t.loc[t["stopped_early"], "night"].tolist()
    if (~night).any():
        out["not_at_dusk"] = t.loc[~night, "night"].tolist()
    return out


START_EARLIEST_H, START_LATEST_H = -1.0, 1.5   # a light trap starts between 1 h before and 1.5 h after civil dusk
STOPPED_EARLY_H = 1.5


def _fixed(spread_min: float) -> str:
    return (f"the first photos don't follow dusk (they wander by about {round(spread_min)} min), so the trap "
            f"probably runs on a fixed schedule: its clock can't be told from this")


def _mins(h: float) -> str:
    m = round(h * 60)
    return "at" if m == 0 else f"{abs(m)} min {'after' if m > 0 else 'before'}"


def _fmt(h: float) -> str:
    sign = "+" if h >= 0 else "-"
    h = abs(h)
    return f"UTC{sign}{int(h)}" + (f":{round((h % 1) * 60):02d}" if h % 1 else "")


def times_from(args, settings) -> tuple[pd.Series, str]:
    """The device clock's times for each file, from file names (a folder, a bucket, or a run's results)."""
    from . import devices, objectstore, times
    device = devices.get(args.device) if args.device else None

    def when(name: str):
        if device:
            got = devices.parse_filename(name, device, None)["file_datetime"]
            if got:
                return got
        return times.from_name(Path(name).name)
    if args.results:
        r = Path(args.results)
        f = r if r.is_file() else next(iter(sorted(r.glob("*_files.csv"))), None)
        if f is None:
            raise SystemExit(f"No *_files.csv in {r}: give the folder of a finished run.")
        names = pd.read_csv(f)["source_key"].astype(str)
        what = f.name
    elif args.folder:
        names = pd.Series([str(p) for p in Path(args.folder).rglob("*") if p.is_file()])
        what = args.folder
    elif args.bucket and args.deployment:
        prefix = f"{args.deployment}/{args.data_type or (device or {}).get('data_type') or 'snapshot_images'}/"
        names = pd.Series(objectstore.list_keys(objectstore.client(settings), args.bucket, prefix,
                                                tuple((device or {}).get("extensions") or (".jpg", ".jpeg", ".wav"))))
        what = f"s3://{args.bucket}/{prefix}"
    else:
        raise SystemExit("Give --folder, --results (a run's folder) or --bucket with --deployment.")
    t = pd.to_datetime(names.map(when), errors="coerce")
    if t.notna().sum() == 0:
        raise SystemExit(f"No dates could be read from the file names in {what}. Try --device.")
    return t, f"{int(t.notna().sum()):,} files in {what}"


def add_command(sub, common) -> None:
    import argparse
    p = sub.add_parser("clock-check", parents=[common], help="what time a trap's clock kept (UTC, local, out?)",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--folder", help="the photos or recordings")
    p.add_argument("--results", help="or a finished run's results folder (reads its _files.csv)")
    p.add_argument("--bucket", help="or an object-store bucket, with --deployment")
    p.add_argument("--deployment")
    p.add_argument("--data-type")
    p.add_argument("--device", help="e.g. lepisense, ami-trap, audiomoth (helps read the file names)")
    p.add_argument("--lat", type=float, required=True, help="the site's latitude, e.g. 51.60")
    p.add_argument("--lon", type=float, required=True, help="the site's longitude, e.g. -1.12 (west is minus)")
    p.add_argument("--timezone", help="the site's time zone, e.g. Europe/London, Asia/Singapore, America/Costa_Rica")
    p.add_argument("--out", help="also write the night-by-night table here (.csv)")

    def go(a):
        from .settings import Settings
        t, what = times_from(a, Settings.load(getattr(a, "profile", None)))
        res = check(t, a.lat, a.lon, a.timezone)
        tab = res["nights"]
        print(f"{what}: {len(tab)} nights with photos\n")
        if len(tab):
            cols = ["night", "files", "first_on_clock", "civil_dusk_utc", "first_minus_dusk_h", "last_on_clock",
                    "civil_dawn_utc", "last_minus_dawn_h"]
            show = tab if len(tab) <= 14 else pd.concat([tab.head(7), tab.tail(7)])
            print(show[cols].to_string(index=False))
            if len(tab) > 14:
                print(f"   ... {len(tab) - 14} more nights (--out writes them all)")
        if "gap_median_h" in res:
            print(f"\nFirst photo minus civil dusk (UTC): {res['gap_median_h']:+.2f} h on a typical night, "
                  f"varying by about {res['gap_spread_min']} min")
        print(f"\nVerdict: {res['verdict']}.")
        for k, what in (("jumps", "The clock seems to jump on"),
                        ("stopped_early", "The unit stopped well before its usual time (battery? memory card?) on"),
                        ("not_at_dusk", "Photos that weren't a night's trapping (set-up tests in daylight?) on")):
            if res.get(k):
                print(f"{what}: {', '.join(res[k][:12])}" + (f" and {len(res[k]) - 12} more" if len(res[k]) > 12 else ""))
        print("This assumes the trap starts at dusk. Times are never changed: note the clock with the deployment.")
        if a.out:
            tab.to_csv(a.out, index=False)
            print(f"Night by night: {a.out}")
    p.set_defaults(func=go)
