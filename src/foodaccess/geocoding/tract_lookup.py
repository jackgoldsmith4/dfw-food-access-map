"""
Fills in `housing_properties.tract_geoid` for every row that already has
coordinates — the join key the opportunity-score composite metric needs
to pull in tract-level context (median household income, poverty rate,
SNAP participation, USDA's own low-access measure) alongside a
property's own fields. See BACKLOG.md's "Housing opportunity score"
entry for why.

Uses the same free Census Bulk Geocoder service as
geocoding/census_geocoder.py, but its coordinate-lookup endpoint rather
than the address-batch one — verified against a real call (2026-09):
GET .../geographies/coordinates?x=<lon>&y=<lat>&benchmark=...&vintage=...
returns the Census Tract GEOID (state+county+tract, matching the format
already stored in tract_demographics.tract_geoid) for a single point.

Deliberately coordinate-based, not address-based: every housing row
already has a trusted latitude/longitude (from its own source, CAD
geocoding, or Denton's native parcel coordinates), so looking up the
tract for that exact point avoids the two failure modes an address-batch
approach would add — re-deriving a possibly-different coordinate, and
addresses that don't match at all.

Unlike the address batch geocoder, this endpoint has no bulk/multi-point
form — one HTTP request per row. run() only processes rows with
`tract_geoid IS NULL`, so this is a real cost exactly once: the initial
backfill of every existing housing row (confirmed 2026-09: ~41,000 rows,
~4.7 hours at one request at a time). Every run after that only pays for
rows added since — a routine pipeline refresh adds at most a few hundred
new properties, not tens of thousands, so it finishes in well under a
minute with no concurrency needed.

That one-time cost is why this is the one module in the project that
runs its requests concurrently (a small thread pool) rather than the
sequential style every other pipeline uses — a deliberate, scoped
exception for a backfill that only ever happens once, not a general
pattern to reuse elsewhere.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from foodaccess.common.http_client import FetchError, fetch_json
from foodaccess.storage.database import get_connection

logger = logging.getLogger(__name__)

GEOGRAPHIES_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
BENCHMARK = "Public_AR_Current"
VINTAGE = "Current_Current"
MAX_WORKERS = 8
LOG_EVERY = 500
STORE_EVERY = 200  # commit progress periodically so a long run isn't all-or-nothing


def fetch_rows_needing_tract() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT source, source_id, latitude, longitude
            FROM housing_properties
            WHERE latitude IS NOT NULL AND tract_geoid IS NULL
            """
        ).fetchall()
    return [dict(row) for row in rows]


def lookup_tract(latitude: float, longitude: float) -> str | None:
    """Return the 11-digit Census Tract GEOID for a point, or None if the
    lookup fails or Census has no tract on file for it."""
    try:
        response = fetch_json(
            GEOGRAPHIES_URL,
            params={
                "x": longitude,
                "y": latitude,
                "benchmark": BENCHMARK,
                "vintage": VINTAGE,
                "layers": "Census Tracts",
                "format": "json",
            },
        )
    except FetchError:
        logger.warning("Tract lookup failed for (%s, %s)", latitude, longitude)
        return None

    tracts = response.get("result", {}).get("geographies", {}).get("Census Tracts", [])
    return tracts[0]["GEOID"] if tracts else None


def store(records: list[dict]) -> int:
    if not records:
        return 0
    with get_connection() as conn:
        conn.executemany(
            "UPDATE housing_properties SET tract_geoid = :tract_geoid WHERE source = :source AND source_id = :source_id",
            records,
        )
    return len(records)


def run() -> int:
    rows = fetch_rows_needing_tract()
    logger.info("%d housing_properties rows need a tract lookup", len(rows))
    if not rows:
        return 0

    total = 0
    not_found = 0
    completed = 0
    pending: list[dict] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_row = {pool.submit(lookup_tract, row["latitude"], row["longitude"]): row for row in rows}

        for future in as_completed(future_to_row):
            row = future_to_row[future]
            geoid = future.result()
            completed += 1

            if geoid is None:
                not_found += 1
            else:
                pending.append({"source": row["source"], "source_id": row["source_id"], "tract_geoid": geoid})

            if len(pending) >= STORE_EVERY:
                total += store(pending)
                pending = []

            if completed % LOG_EVERY == 0:
                logger.info("Tract lookup progress: %d/%d (%d not found)", completed, len(rows), not_found)

    total += store(pending)
    logger.info("Tract lookup done: %d of %d rows matched, %d not found", total, len(rows), not_found)
    return total


if __name__ == "__main__":
    from foodaccess.common.logging_config import configure_logging

    configure_logging()
    run()
