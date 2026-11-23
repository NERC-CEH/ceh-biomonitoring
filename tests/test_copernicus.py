"""ERA5-Land set-up: the key is checked, saved privately beside other credentials, and every problem says
what to do next. No real Copernicus account is used: the web calls are faked."""
from __future__ import annotations

import json

import pytest

from ceh_biomonitoring.reporting import copernicus as C

GOOD = "0123abcd-4567-89ab-cdef-0123456789ab"


class _R:
    def __init__(self, code, body):
        self.status_code, self._body, self.text = code, body, json.dumps(body)

    def json(self):
        return self._body


@pytest.fixture
def creds(tmp_path, monkeypatch):
    f = tmp_path / "credentials.json"
    monkeypatch.setenv("CEHBIO_CREDENTIALS", str(f))
    monkeypatch.delenv("CDSAPI_KEY", raising=False)
    return f


def test_a_key_that_isnt_one_is_caught_before_asking_copernicus():
    state, msg = C.check_key("my password")
    assert state == "bad key" and "API Token" in msg


@pytest.mark.parametrize("code,body,state,words", [
    (401, {"title": "Authentication failed"}, "bad key", "didn't accept"),
    (200, {"licences": []}, "no licence", "Terms of use"),
    (200, {"licences": [{"id": "cc-by", "revision": 1}]}, "ok", "works"),
    (200, [{"id": "CC-BY"}], "ok", "works"),
    (503, {}, "offline", "busy"),
])
def test_key_check_says_what_to_do(monkeypatch, code, body, state, words):
    monkeypatch.setattr(C, "_req", lambda *a, **k: _R(code, body))
    got, msg = C.check_key(GOOD)
    assert got == state and words in msg


def test_saving_keeps_the_other_credentials(creds):
    creds.write_text(json.dumps({"AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "b"}))
    C.save_key(GOOD)
    saved = json.loads(creds.read_text())
    assert saved["AWS_ACCESS_KEY_ID"] == "a" and saved["CDSAPI_KEY"] == GOOD
    assert C.saved_key() == GOOD


def test_a_weather_key_needs_no_object_store_keys(creds):
    creds.write_text(json.dumps({"CDSAPI_KEY": GOOD}))        # no AWS keys at all
    assert C.saved_key() == GOOD


def test_no_key_points_to_the_walkthrough(creds, tmp_path):
    from datetime import date

    from ceh_biomonitoring.reporting import weather as W
    from ceh_biomonitoring.settings import Settings
    s = Settings.load(profile="local", overrides={"models": {"cache_dir": str(tmp_path / "cache")}},
                      settings_file=tmp_path / "none.yml")
    with pytest.raises(SystemExit) as e:
        W.hourly(s, "era5-land", 51.6, -1.1, date(2025, 6, 1), date(2025, 6, 2))
    assert "weather-setup" in str(e.value) and "cehbio_weather_setup()" in str(e.value)


def test_a_refused_request_explains_the_licence(monkeypatch):
    monkeypatch.setattr(C, "_req", lambda *a, **k: _R(403, {"detail": "required licences not accepted"}))
    with pytest.raises(SystemExit) as e:
        C.fetch(51.6, -1.1, "2025-06-01", "2025-06-02", GOOD, quiet=True)
    assert "Terms of use" in str(e.value) and "Accept" in str(e.value)


def test_check_only_without_a_key(creds, capsys):
    assert C.setup(check_only=True) == 1
    assert "weather-setup" in capsys.readouterr().out
