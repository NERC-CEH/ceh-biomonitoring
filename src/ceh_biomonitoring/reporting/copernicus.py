"""ERA5-Land weather from the Copernicus Climate Data Store (CDS), for commercial work.

Open-Meteo (the default weather) is free for NON-COMMERCIAL use only. For commercial reports, use
--weather era5-land: ECMWF's ERA5-Land reanalysis, about 9 km, CC BY 4.0 (commercial use allowed, with
credit). It needs each person's own free Copernicus account and key, set up once:

    cehbio weather-setup            walks you through it, checks it, and saves the key
    cehbio weather-setup --check    checks the key you saved

Steps it walks you through:
  1. make a free account at https://cds.climate.copernicus.eu (top right: Login - Register)
  2. accept the dataset's licence (CC-BY), once: the ERA5-Land time series page, Download tab, at the
     bottom: "Terms of use" - Accept
  3. copy your API key (Personal Access Token) from your profile page and paste it in

The key is saved as "CDSAPI_KEY" in your private credentials file (~/.config/ceh-biomonitoring/
credentials.json), never shown on screen, and never stored anywhere else. Accounts are personal: please
don't share a key. The same file is read by the R package (cehbio_weather_setup() does the same from R).
"""
from __future__ import annotations

import json
import os
import re
import stat
import time
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd

API = "https://cds.climate.copernicus.eu/api"
DATASET = "reanalysis-era5-land-timeseries"
LICENCE = "cc-by"
URLS = {
    "register": "https://cds.climate.copernicus.eu",
    "licence": f"https://cds.climate.copernicus.eu/datasets/{DATASET}?tab=download",
    "key": "https://cds.climate.copernicus.eu/profile",
}
HOW_TO = ("Set it up once (about 5 minutes): run  cehbio weather-setup  (in R: cehbio_weather_setup()). It walks "
          "you through making a free Copernicus account, accepting the licence and saving your key.")
INTRO = """Weather for commercial reports: ERA5-Land, from Copernicus

Open-Meteo (the usual weather) is free for non-commercial work only. For commercial reports the toolkit uses
ERA5-Land, which anyone may use (CC BY 4.0) but which needs your own free Copernicus account and key.
This takes about 5 minutes, once. Three steps:
"""
KEY_RX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class CDSError(SystemExit):
    pass


# ------------------------------------------------------------------ the key
def credentials_file(settings=None) -> Path:
    if os.environ.get("CEHBIO_CREDENTIALS"):
        return Path(os.environ["CEHBIO_CREDENTIALS"])
    if settings is not None:
        try:
            return Path(settings.path("credentials_file")).expanduser()
        except KeyError:
            pass
    from ..settings import CONFIG_DIR
    return CONFIG_DIR / "credentials.json"


def saved_key(settings=None) -> str | None:
    """The CDS key from the credentials file (or the CDSAPI_KEY environment variable), or None."""
    if os.environ.get("CDSAPI_KEY"):
        return os.environ["CDSAPI_KEY"].strip()
    f = credentials_file(settings)
    try:
        return (json.loads(f.read_text()).get("CDSAPI_KEY") or "").strip() or None
    except (OSError, ValueError):
        return None


def save_key(key: str, settings=None) -> Path:
    """Add the key to the credentials file, keeping everything else in it; private to you."""
    f = credentials_file(settings)
    f.parent.mkdir(parents=True, exist_ok=True)
    creds = {}
    if f.exists():
        try:
            creds = json.loads(f.read_text())
        except ValueError as e:
            raise CDSError(f"{f} isn't valid JSON, so the key wasn't added. Fix or move that file, then try again.") from e
    creds["CDSAPI_KEY"] = key
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(creds, indent=2))
    if os.name == "posix":
        tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(f)
    return f


# ------------------------------------------------------------------ talking to the CDS
class _Resp:
    def __init__(self, status_code: int, content: bytes):
        self.status_code, self.content = status_code, content
        self.text = content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)


def _req(method: str, url: str, key: str | None = None, body: dict | None = None, timeout: int = 60) -> _Resp:
    """One web request, with the computer's own certificates (as Open-Meteo's), so it works behind
    organisation networks that check secure connections."""
    import urllib.error
    import urllib.request
    h = {"User-Agent": "ceh-biomonitoring"}
    if key:
        h["PRIVATE-TOKEN"] = key
    data = None
    if body is not None:
        data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _Resp(r.status, r.read())
    except urllib.error.HTTPError as e:
        return _Resp(e.code, e.read() or b"{}")


def check_key(key: str) -> tuple[str, str]:
    """('ok' | 'bad key' | 'no licence' | 'offline', what to tell the person)."""
    if not KEY_RX.match(key or ""):
        return "bad key", ("That doesn't look like a Copernicus key. It looks like "
                           "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (letters a-f and numbers). Copy the whole "
                           f"'API Token' from {URLS['key']}")
    try:
        r = _req("GET", f"{API}/profiles/v1/account/licences", key)
    except Exception as e:  # noqa: BLE001
        return "offline", f"Couldn't reach Copernicus ({type(e).__name__}). Check the internet connection."
    if r.status_code in (401, 403):
        return "bad key", f"Copernicus didn't accept that key. Copy it again from {URLS['key']} (the 'API Token')."
    if r.status_code != 200:
        return "offline", f"Copernicus answered {r.status_code}; it may be busy. Try again later."
    got = r.json()
    lic = got.get("licences", got) if isinstance(got, dict) else got
    ids = {str(x.get("id", "")).lower() for x in lic if isinstance(x, dict)}
    if LICENCE not in ids:
        return "no licence", ("The key works, but the ERA5-Land licence hasn't been accepted yet. Open "
                              f"{URLS['licence']} (logged in), scroll to the bottom of the Download tab, and under "
                              "'Terms of use' click Accept. It's the CC-BY licence and you only do it once.")
    return "ok", "Your Copernicus key works and the ERA5-Land licence is accepted."


def _explain(r) -> str:
    try:
        d = r.json()
        msg = d.get("detail") or d.get("title") or d.get("message") or ""
    except ValueError:
        msg = r.text[:200]
    if r.status_code == 401:
        return f"Copernicus didn't accept your key. {HOW_TO}"
    if r.status_code == 403 or "licen" in str(msg).lower():
        return ("Copernicus refused the request: the ERA5-Land licence hasn't been accepted on your account. Open "
                f"{URLS['licence']} (logged in), and at the bottom of the Download tab, under 'Terms of use', click "
                "Accept. Then run the report again. (cehbio weather-setup --check checks it.)")
    return f"Copernicus couldn't make the weather ({r.status_code}: {msg})."


def fetch(lat: float, lon: float, start, end, key: str, quiet: bool = False) -> pd.DataFrame:
    """Hourly ERA5-Land at a point (UTC), as raw CDS columns: valid_time, t2m, d2m, tp, u10, v10."""
    body = {"inputs": {"variable": ["2m_temperature", "2m_dewpoint_temperature", "total_precipitation",
                                    "10m_u_component_of_wind", "10m_v_component_of_wind"],
                       "location": {"latitude": round(lat, 3), "longitude": round(lon, 3)},
                       "date": [f"{start}/{end}"], "data_format": "csv"}}
    r = _req("POST", f"{API}/retrieve/v1/processes/{DATASET}/execution", key, body)
    if r.status_code not in (200, 201):
        raise CDSError(_explain(r))
    job = r.json()["jobID"]
    status_url = f"{API}/retrieve/v1/jobs/{job}"
    if not quiet:
        print("  ERA5-Land: request queued at Copernicus (usually a minute or two) ...", flush=True)
    for i in range(240):
        st = _req("GET", status_url, key).json().get("status")
        if st in ("successful", "failed", "rejected", "dismissed"):
            break
        time.sleep(min(30, 2 + 2 * i))
    if st != "successful":
        raise CDSError(f"Copernicus couldn't make the weather (the request was {st}). Try again later.")
    res = _req("GET", f"{status_url}/results", key).json()
    data = _req("GET", res["asset"]["value"]["href"], key, timeout=600).content
    parts = []
    if data[:2] == b"PK":
        with zipfile.ZipFile(BytesIO(data)) as z:
            parts = [pd.read_csv(z.open(n)) for n in z.namelist() if n.endswith(".csv")]
    else:
        parts = [pd.read_csv(BytesIO(data))]
    df = None
    for p in parts:
        t = next(c for c in p.columns if "time" in c.lower())
        p = p.rename(columns={t: "time_utc"})
        keep = ["time_utc"] + [c for c in p.columns if c in ("t2m", "d2m", "tp", "u10", "v10")]
        df = p[keep] if df is None else df.merge(p[keep], on="time_utc", how="outer")
    return df if df is not None else pd.DataFrame(columns=["time_utc"])


# ------------------------------------------------------------------ the walkthrough
def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        raise CDSError("Stopped: this needs someone at the keyboard.") from None


def _open(url: str) -> None:
    print(f"     {url}")
    if _ask("     Press Enter to open it in your browser (or type n and Enter to skip): ").strip().lower() != "n":
        import webbrowser
        webbrowser.open(url)


def setup(settings=None, check_only: bool = False) -> int:
    if check_only:
        key = saved_key(settings)
        if not key:
            print(f"No Copernicus key saved yet. {HOW_TO}")
            return 1
        state, msg = check_key(key)
        print(msg)
        return 0 if state == "ok" else 1
    print(INTRO)
    key = saved_key(settings)
    if key:
        state, msg = check_key(key)
        if state == "ok":
            print(f"You're already set up. {msg}")
            return 0
        print(f"You have a key saved, but: {msg}\n")
    print("STEP 1 of 3: a free Copernicus account")
    print("  If you don't have one: open the page below, click 'Login - Register' (top right) and register.")
    print("  You'll get an email to confirm it.")
    _open(URLS["register"])
    _ask("  Press Enter when you have an account and are logged in ... ")
    print("\nSTEP 2 of 3: accept the ERA5-Land licence (once)")
    print("  On the page below, go to the 'Download' tab, scroll to the bottom, and under 'Terms of use' click")
    print("  'Accept' (it's the CC-BY licence). If it already says accepted, that's fine.")
    _open(URLS["licence"])
    _ask("  Press Enter when it's accepted ... ")
    print("\nSTEP 3 of 3: your key")
    print("  On your profile page (below), find 'API Token' and copy it (the copy button next to it).")
    _open(URLS["key"])
    import getpass
    for attempt in range(5):
        key = getpass.getpass("  Paste it here and press Enter (it stays hidden, which is normal): ").strip()
        state, msg = check_key(key)
        if state == "ok":
            f = save_key(key, settings)
            print(f"\nDone. {msg}\nYour key is saved privately in {f} (as CDSAPI_KEY).")
            print("Make commercial reports with:  --weather era5-land   (in R: weather = \"era5-land\")")
            return 0
        print(f"  {msg}")
        if state == "no licence":
            f = save_key(key, settings)
            _open(URLS["licence"])
            _ask("  Press Enter once you've clicked Accept ... ")
            state, msg = check_key(key)
            print(f"  {msg}")
            if state == "ok":
                print(f"\nDone. Your key is saved privately in {f} (as CDSAPI_KEY).")
                return 0
            print(f"  Your key is saved in {f}. If you're sure you accepted the licence, carry on: the first "
                  "ERA5-Land report will say if it's still missing.")
            return 1
        if state == "offline":
            return 1
    print("Stopped after several tries. Run  cehbio weather-setup  again when you're ready, or ask for help.")
    return 1


def add_command(sub, common) -> None:
    import argparse
    p = sub.add_parser("weather-setup", parents=[common], help="set up ERA5-Land weather for commercial reports (once)",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="only check the key you've saved")

    def go(a):
        from ..settings import Settings
        raise SystemExit(setup(Settings.load(getattr(a, "profile", None)), check_only=a.check))
    p.set_defaults(func=go)
