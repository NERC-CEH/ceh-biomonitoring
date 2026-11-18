"""Reading dates and times, whatever form they come in.

Results and files carry times in many forms: text in several layouts ("2024-11-01 20:57:39",
"2024-11-01T20:57:39+08:00", "2024:11:01 20:57:39" as in photo EXIF), real timestamps (with or without a
time zone), numbers (seconds or milliseconds since 1970), and times in file names
(20240725204340-snapshot.jpg, 01-20240204211800-snapshot.jpg, ami-mini-20250428T210338.jpg,
SMA01234_20240705_043000.wav, Mothbox's name_2026-07-06T22-03-07+02-00.jpg).

Everything here gives the LOCAL CLOCK time as written (a time zone, when there is one, is dropped, not
converted): nights and months follow the trap's or recorder's own clock, which is what the people who set
it up planned around. A column of times can mix layouts: each value is read on its own.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

_SEP = r"[-_:.]?"
NAME_PATTERNS = [
    # 2026-07-06T22-03-07, 2024-07-05 04:30:00, 2024_07_05_04_30_00
    re.compile(r"(?<!\d)(\d{4})[-_](\d{2})[-_](\d{2})[T _-](\d{2})[-_:.](\d{2})[-_:.](\d{2})(?!\d)"),
    # 20240725204340, 20260806T025318, 20240705_043000, 20240705-043000
    re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})[T_-]?(\d{2})(\d{2})(\d{2})(?!\d)"),
]
DATE_PATTERNS = [re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"),
                 re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)"),
                 re.compile(r"(?<!\d)(\d{4})_(\d{2})_(\d{2})(?!\d)")]
_OFFSET = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")
_EXIF = re.compile(r"^(\d{4}):(\d{2}):(\d{2})([ T].*)?$")
YEARS = (1990, 2100)


def _ok(dt: datetime) -> bool:
    return YEARS[0] <= dt.year <= YEARS[1]


def from_name(name: str, device: dict | None = None, pattern: str | None = None) -> datetime | None:
    """The date and time in a file name (local clock), or None. A device's own patterns go first."""
    name = Path(str(name)).name
    if device or pattern:
        from . import devices
        dt = devices.parse_filename(name, device, pattern)["file_datetime"]
        if dt:
            return datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
    for rx in NAME_PATTERNS:
        for m in rx.finditer(name):
            try:
                dt = datetime(*map(int, m.groups()))
            except ValueError:
                continue
            if _ok(dt):
                return dt
    return None


def date_from_name(name: str) -> date | None:
    """Just the date in a file name (when there's no time in it)."""
    dt = from_name(name)
    if dt:
        return dt.date()
    name = Path(str(name)).name
    for rx in DATE_PATTERNS:
        for m in rx.finditer(name):
            try:
                d = date(*map(int, m.groups()))
            except ValueError:
                continue
            if YEARS[0] <= d.year <= YEARS[1]:
                return d
    return None


def parse(values) -> pd.Series:
    """Any column of times -> local-clock datetimes (NaT where a value can't be read)."""
    s = values if isinstance(values, pd.Series) else pd.Series(values)
    if isinstance(s.dtype, pd.CategoricalDtype):
        s = s.astype(object)
    if isinstance(s.dtype, pd.DatetimeTZDtype):
        return s.dt.tz_localize(None)
    if pd.api.types.is_datetime64_any_dtype(s.dtype):
        return s.astype("datetime64[ns]")
    if pd.api.types.is_numeric_dtype(s.dtype) and not pd.api.types.is_bool_dtype(s.dtype):
        n = pd.to_numeric(s, errors="coerce")
        ms = n.abs() > 1e11                                  # milliseconds, not seconds
        out = pd.to_datetime(n.where(~ms, n / 1000), unit="s", errors="coerce")
        return out.where(n.notna() & (n != 0))
    st = s.astype("string").str.strip()
    empty = st.isna() | st.str.lower().isin(["", "nan", "nat", "none", "null"]).fillna(True)
    # fast path: the usual layouts, all at once (time zones dropped, keeping the clock time)
    out = pd.to_datetime(st.where(~empty).str.replace(_OFFSET.pattern, "", regex=True).str.strip(),
                         errors="coerce", format="ISO8601")
    if isinstance(out.dtype, pd.DatetimeTZDtype):
        out = out.dt.tz_localize(None)
    rest = out.isna() & ~empty
    if rest.any():                                        # anything else, one distinct value at a time
        found = {v: _one_text(v) for v in st[rest].unique()}
        out = out.astype("datetime64[ns]")
        out[rest] = pd.to_datetime(st[rest].map(found), errors="coerce")
    out = out.astype("datetime64[ns]")
    return out.where((out.dt.year >= YEARS[0]) & (out.dt.year <= YEARS[1]))


def _one_text(v):
    if isinstance(v, datetime):
        return pd.Timestamp(v).tz_localize(None) if v.tzinfo else pd.Timestamp(v)
    t = str(v).strip()
    if not t or t.lower() in ("nan", "nat", "none", "null"):
        return None
    m = _EXIF.match(t)
    if m:
        t = f"{m.group(1)}-{m.group(2)}-{m.group(3)}{m.group(4) or ''}"
    if re.fullmatch(r"\d{14}", t):
        t = f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}:{t[12:]}"
    t = _OFFSET.sub("", t).strip()
    try:
        ts = pd.Timestamp(t)
    except (ValueError, TypeError, OverflowError):
        return None
    if ts is pd.NaT or pd.isna(ts):
        return None
    ts = ts.tz_localize(None) if ts.tzinfo else ts
    return ts if YEARS[0] <= ts.year <= YEARS[1] else None


def best(column, names, device: dict | None = None) -> tuple[pd.Series, pd.Series, int]:
    """Times from a results column, falling back to the file name. Returns (times, source, disagree):
    source is 'results', 'file name' or 'unknown'; disagree counts the files whose results time is more
    than a minute from their file name's time. The results win when both are known: they hold any clock corrections made
    when the results were built (e.g. a camera set to the wrong year)."""
    names = pd.Series(names).astype(str).reset_index(drop=True)
    col = (parse(pd.Series(column).reset_index(drop=True)) if column is not None
           else pd.Series(pd.NaT, index=names.index, dtype="datetime64[ns]"))
    from_file = pd.to_datetime(names.map({n: from_name(n, device) for n in names.unique()}), errors="coerce")
    both = col.notna() & from_file.notna()
    off = both & ((col - from_file).abs() > pd.Timedelta(minutes=1))
    n_disagree = int(names[off].nunique())                 # photos (or recordings), not rows
    when = col.fillna(from_file)
    src = pd.Series("unknown", index=names.index, dtype=object)
    src[from_file.notna()] = "file name"
    src[col.notna()] = "results"
    return when, src, n_disagree


def exif_time(image) -> datetime | None:
    """When a photo was taken, from its EXIF (DateTimeOriginal, else DateTime), or None."""
    try:
        ex = image.getexif()
        v = ex.get_ifd(0x8769).get(36867) or ex.get(306)
    except Exception:  # noqa: BLE001
        return None
    ts = _one_text(v) if v else None
    return ts.to_pydatetime() if ts is not None else None
