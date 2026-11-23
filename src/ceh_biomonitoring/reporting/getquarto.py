"""Quarto, for Word and PDF reports: found, or downloaded once into the toolkit's own folder.

The folder is $CEHBIO_HOME (default %LOCALAPPDATA%/ceh-biomonitoring on Windows,
~/.local/share/ceh-biomonitoring elsewhere): the same one the installers and R's cehbio_install() use, so
R and Python share one Quarto. Run `python -m ceh_biomonitoring.reporting.getquarto` to fetch it now.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

FALLBACK_VERSION = "1.8.27"


def home() -> Path:
    h = os.environ.get("CEHBIO_HOME")
    if h:
        return Path(h)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ceh-biomonitoring"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "ceh-biomonitoring"


def _exe(folder: Path) -> Path:
    return folder / "bin" / ("quarto.exe" if os.name == "nt" else "quarto")


def find() -> str | None:
    cands = [os.environ.get("QUARTO_PATH"), str(_exe(home() / "quarto")), shutil.which("quarto")]
    if os.name == "nt":
        cands += [str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Quarto/bin/quarto.exe"),
                  "C:/Program Files/Quarto/bin/quarto.exe"]
    return next((c for c in cands if c and Path(c).exists()), None)


def _get(url: str, dest: Path | None = None) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": "ceh-biomonitoring"})
    with urllib.request.urlopen(req, timeout=600) as r:
        if dest is None:
            return r.read()
        with open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    return None


def install(quiet: bool = False) -> str:
    """Download Quarto into <CEHBIO_HOME>/quarto (once) and return its path."""
    try:
        version = json.loads(_get("https://api.github.com/repos/quarto-dev/quarto-cli/releases/latest"))["tag_name"].lstrip("v")
    except Exception:  # noqa: BLE001 - the API is rate-limited; a known release works too
        version = FALLBACK_VERSION
    system, machine = platform.system(), platform.machine().lower()
    if system == "Windows":
        name = f"quarto-{version}-win.zip"
    elif system == "Darwin":
        name = f"quarto-{version}-macos.tar.gz"
    else:
        name = f"quarto-{version}-linux-{'arm64' if machine in ('aarch64', 'arm64') else 'amd64'}.tar.gz"
    if not quiet:
        print(f"Getting Quarto {version} for Word and PDF reports (once, about 150 MB) ...")
    dest = home() / "quarto"
    with tempfile.TemporaryDirectory() as tmp:
        arc = Path(tmp) / name
        _get(f"https://github.com/quarto-dev/quarto-cli/releases/download/v{version}/{name}", arc)
        un = Path(tmp) / "un"
        if name.endswith(".zip"):
            zipfile.ZipFile(arc).extractall(un)
        else:
            with tarfile.open(arc) as t:
                t.extractall(un)
        top = list(un.iterdir())
        src = top[0] if len(top) == 1 and (top[0] / "bin").is_dir() else un      # Linux/Mac: one top folder
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(src, dest)
    exe = _exe(dest)
    if not exe.exists():
        raise SystemExit(f"Quarto didn't unpack as expected into {dest}.")
    if os.name != "nt":
        exe.chmod(0o755)
    return str(exe)


def quarto(auto_install: bool = True) -> str:
    q = find()
    if q:
        return q
    if not auto_install:
        raise SystemExit("Word and PDF reports need Quarto. HTML reports don't.")
    try:
        return install()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"Word and PDF reports need Quarto, and it couldn't be downloaded ({e}). Check the "
                         "internet connection, or install it from https://quarto.org. HTML reports don't need it.")


if __name__ == "__main__":
    print(quarto())
