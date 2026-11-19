"""The moon, for each night: how full it is, and whether it's up while the trap or recorder is working.

Low-precision positions (Paul Schlyter's method, "How to compute planetary positions"): about a
degree, which is plenty to say whether the moon is up. No extra packages.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

RAD = math.pi / 180


def _days(t: datetime) -> float:
    """Days since 2000-01-00 00:00 UTC (Schlyter's day number)."""
    t = t.astimezone(timezone.utc) if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return (t - datetime(1999, 12, 31, tzinfo=timezone.utc)).total_seconds() / 86400


def _rev(x: float) -> float:
    return x % 360


def _sun_ecliptic(d: float) -> tuple[float, float]:
    """(ecliptic longitude, mean longitude) of the sun, degrees."""
    w = 282.9404 + 4.70935e-5 * d
    e = 0.016709 - 1.151e-9 * d
    M = _rev(356.0470 + 0.9856002585 * d)
    E = M + e / RAD * math.sin(M * RAD) * (1 + e * math.cos(M * RAD))
    x, y = math.cos(E * RAD) - e, math.sin(E * RAD) * math.sqrt(1 - e * e)
    v = math.atan2(y, x) / RAD
    return _rev(v + w), _rev(M + w)


def _moon_ecliptic(d: float) -> tuple[float, float]:
    """(ecliptic longitude, latitude) of the moon, degrees, with the main perturbations."""
    N = _rev(125.1228 - 0.0529538083 * d)
    i, w = 5.1454, _rev(318.0634 + 0.1643573223 * d)
    a, e = 60.2666, 0.054900
    M = _rev(115.3654 + 13.0649929509 * d)
    E = M + e / RAD * math.sin(M * RAD) * (1 + e * math.cos(M * RAD))
    for _ in range(3):
        E = E - (E - e / RAD * math.sin(E * RAD) - M) / (1 - e * math.cos(E * RAD))
    x, y = a * (math.cos(E * RAD) - e), a * math.sqrt(1 - e * e) * math.sin(E * RAD)
    r, v = math.hypot(x, y), math.atan2(y, x) / RAD
    xe = r * (math.cos(N * RAD) * math.cos((v + w) * RAD) - math.sin(N * RAD) * math.sin((v + w) * RAD) * math.cos(i * RAD))
    ye = r * (math.sin(N * RAD) * math.cos((v + w) * RAD) + math.cos(N * RAD) * math.sin((v + w) * RAD) * math.cos(i * RAD))
    ze = r * math.sin((v + w) * RAD) * math.sin(i * RAD)
    lon, lat = _rev(math.atan2(ye, xe) / RAD), math.atan2(ze, math.hypot(xe, ye)) / RAD
    _, Ls = _sun_ecliptic(d)
    Ms = _rev(356.0470 + 0.9856002585 * d)
    Lm, D = _rev(N + w + M), _rev(_rev(N + w + M) - Ls)
    F = _rev(Lm - N)
    lon += (-1.274 * math.sin((M - 2 * D) * RAD) + 0.658 * math.sin(2 * D * RAD) - 0.186 * math.sin(Ms * RAD)
            - 0.059 * math.sin((2 * M - 2 * D) * RAD) - 0.057 * math.sin((M - 2 * D + Ms) * RAD)
            + 0.053 * math.sin((M + 2 * D) * RAD) + 0.046 * math.sin((2 * D - Ms) * RAD)
            + 0.041 * math.sin((M - Ms) * RAD) - 0.035 * math.sin(D * RAD))
    lat += -0.173 * math.sin((F - 2 * D) * RAD) - 0.055 * math.sin((M - F - 2 * D) * RAD)
    return _rev(lon), lat


def moon_illumination(t: datetime) -> float:
    """Fraction of the moon's disc lit, 0 (new) to 1 (full)."""
    d = _days(t)
    sun_lon, _ = _sun_ecliptic(d)
    lon, lat = _moon_ecliptic(d)
    elong = math.acos(math.cos((lon - sun_lon) * RAD) * math.cos(lat * RAD))
    return (1 - math.cos(elong)) / 2                 # elongation 180 degrees = full


def moon_altitude(t: datetime, lat: float, lon: float) -> float:
    """Height of the moon above the horizon, degrees (negative = below), ignoring parallax and refraction."""
    d = _days(t)
    mlon, mlat = _moon_ecliptic(d)
    ecl = 23.4393 - 3.563e-7 * d
    xe = math.cos(mlon * RAD) * math.cos(mlat * RAD)
    ye = math.sin(mlon * RAD) * math.cos(mlat * RAD)
    ze = math.sin(mlat * RAD)
    yq = ye * math.cos(ecl * RAD) - ze * math.sin(ecl * RAD)
    zq = ye * math.sin(ecl * RAD) + ze * math.cos(ecl * RAD)
    ra, dec = math.atan2(yq, xe) / RAD, math.atan2(zq, math.hypot(xe, yq)) / RAD
    _, Ls = _sun_ecliptic(d)
    ut = (t.astimezone(timezone.utc) if t.tzinfo else t).hour + (t.minute + t.second / 60) / 60
    lst = _rev(Ls + 180 + ut * 15 + lon)
    ha = (lst - ra) * RAD
    alt = math.asin(math.sin(lat * RAD) * math.sin(dec * RAD) + math.cos(lat * RAD) * math.cos(dec * RAD) * math.cos(ha))
    return alt / RAD - 0.95 * math.cos(alt)            # about the moon's parallax


def moon_over(start_utc: datetime, end_utc: datetime, lat: float, lon: float, step_min: int = 15) -> dict:
    """Over a spell of work: the moon's illumination at its middle, and the share of the time it was up."""
    from datetime import timedelta
    mid = start_utc + (end_utc - start_utc) / 2
    n = max(1, int((end_utc - start_utc).total_seconds() // (step_min * 60)))
    up = sum(moon_altitude(start_utc + timedelta(minutes=step_min * k), lat, lon) > 0 for k in range(n + 1))
    return {"moon_illumination": round(moon_illumination(mid), 3), "moon_up_share": round(up / (n + 1), 3)}
