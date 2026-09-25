"""
Shared spatial-grid-index helpers used by both cross-source dedupe
passes (pipelines/food_stores/dedupe.py, pipelines/housing/dedupe.py).

A cheap, non-geodesic proximity index: rounding lat/lon to `precision`
decimal places buckets nearby points into the same grid cell (at the
default precision, ~1km cells), so a match search only has to check a
3x3 neighborhood of cells instead of comparing every row to every other
row. Each dedupe pass keeps its own distance thresholds and matching
rules — only this grid/name/distance machinery is identical between them.
"""
from __future__ import annotations

import re
from math import asin, cos, radians, sin, sqrt

GRID_PRECISION = 2  # ~1km cells — a cheap proximity index, not real spatial indexing


def normalize_name(name: str | None) -> str:
    name = re.sub(r"[^A-Za-z\s]", "", name or "").upper()
    return re.sub(r"\s+", " ", name).strip()


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * r * asin(sqrt(a))


def grid_key(lat: float, lon: float, precision: int = GRID_PRECISION) -> tuple[float, float]:
    return (round(lat, precision), round(lon, precision))


def neighboring_keys(lat: float, lon: float, precision: int = GRID_PRECISION):
    step = 10**-precision
    base_lat, base_lon = grid_key(lat, lon, precision)
    for d_lat in (-step, 0, step):
        for d_lon in (-step, 0, step):
            yield (round(base_lat + d_lat, precision), round(base_lon + d_lon, precision))
