"""Insect outlines from flat-bug, measured for biomass.

flat-bug gives the outline (polygon) of every insect it finds, not just a box. From it we measure:
  area    the pixels inside the outline
  length  the long side of the smallest rotated rectangle around the outline (body length,
          wherever the insect points)
  width   the short side of that rectangle
With pixels_per_mm (the camera's scale) these are also given in mm and mm². Length and area are the
usual inputs to length-weight / area-weight equations for insect biomass.
"""
from __future__ import annotations

import json

import numpy as np


def _hull(pts: np.ndarray) -> np.ndarray:
    """Convex hull (Andrew's monotone chain), counter-clockwise."""
    pts = np.unique(pts, axis=0)
    if len(pts) <= 2:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def measure(polygon) -> dict:
    """area, length and width (pixels) of one outline: a sequence of (x, y) points."""
    p = np.asarray(polygon, dtype=float).reshape(-1, 2)
    if len(p) < 3:
        return {"outline_area_px": 0.0, "outline_length_px": 0.0, "outline_width_px": 0.0}
    x, y = p[:, 0], p[:, 1]
    area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    h = _hull(p)
    best = None
    for i in range(len(h)):                       # the smallest rectangle has a side along a hull edge
        e = h[(i + 1) % len(h)] - h[i]
        n = np.hypot(*e)
        if n == 0:
            continue
        u = e / n
        v = np.array([-u[1], u[0]])
        a, b = h @ u, h @ v
        w1, w2 = a.max() - a.min(), b.max() - b.min()
        if best is None or w1 * w2 < best[0]:
            best = (w1 * w2, max(w1, w2), min(w1, w2))
    _, length, width = best if best else (0, 0, 0)
    return {"outline_area_px": float(area), "outline_length_px": float(length), "outline_width_px": float(width)}


def columns(polygon, pixels_per_mm: float | None = None, keep_points: bool = True) -> dict:
    m = measure(polygon)
    if pixels_per_mm:
        s = float(pixels_per_mm)
        m.update({"outline_area_mm2": m["outline_area_px"] / s ** 2, "outline_length_mm": m["outline_length_px"] / s,
                  "outline_width_mm": m["outline_width_px"] / s})
    if keep_points:
        pts = np.asarray(polygon, dtype=float).reshape(-1, 2)
        m["outline"] = json.dumps(np.round(pts).astype(int).tolist(), separators=(",", ":"))
    return m
