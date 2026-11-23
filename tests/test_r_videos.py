"""The R package's videos and soundscapes (r/R/videos.R), from the same made-up photos and recordings as
the Python ones: the same files, frame counts, sound and lengths. Needs R with cehbio, magick and av."""
from __future__ import annotations

import subprocess

import pytest

from test_r_matches_python import RSCRIPT, _r_has_cehbio
from test_videos import _frames, _photos, _recordings, av, settings  # noqa: F401 - fixtures

pytestmark = pytest.mark.skipif(not _r_has_cehbio(), reason="needs R with the cehbio package")


def _r(code: str, results):
    r = subprocess.run([RSCRIPT, "-e", f'options(cehbio.results = "{results.as_posix()}"); {code}'],
                       capture_output=True, text=True)
    if "needs the magick" in r.stderr or "needs the av" in r.stderr:
        pytest.skip("R magick/av not installed")
    assert r.returncode == 0, r.stderr[-2500:]
    return r


def test_r_night_and_one_insect(settings, tmp_path):  # noqa: F811
    rp = _photos(settings, tmp_path)
    _r('cehbio::cehbio_video("farm", "trap-1", individuals = 1)', settings.outputs_root)
    v = rp.root / "videos"
    assert sorted(p.name for p in v.glob("*.mp4")) == ["trap-1_2026-05-11.mp4", "trap-1_2026-05-11_Track_000001.mp4"]
    n, codec, kinds = _frames(v / "trap-1_2026-05-11.mp4")
    assert n == 12 and codec == "h264" and kinds == ["video"]
    assert _frames(v / "trap-1_2026-05-11_Track_000001.mp4")[0] == 12


def test_r_bird_soundscape(settings, tmp_path):  # noqa: F811
    rp = _recordings(settings, tmp_path)
    _r('cehbio::cehbio_soundscape("birds", "woods", "wood-1")', settings.outputs_root)
    v = rp.root / "videos"
    n, codec, kinds = _frames(v / "wood-1_2026-05-11_soundscape.mp4")
    assert kinds == ["video", "audio"] and 20 * 20 * 0.9 < n < 21 * 20 * 1.1
    assert (v / "wood-1_2026-05-11_overview.png").stat().st_size > 10_000


def test_r_bats_slowed(settings, tmp_path):  # noqa: F811
    rp = _recordings(settings, tmp_path, "bats")
    _r('cehbio::cehbio_soundscape("bats", "woods", "wood-1", day = "2026-05-10")', settings.outputs_root)
    with av.open(str(rp.root / "videos" / "wood-1_2026-05-10_soundscape.mp4")) as c:
        assert 19 < float(c.duration) / 1e6 < 22
