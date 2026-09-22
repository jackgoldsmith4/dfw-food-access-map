"""
Geocoding pass: fills in latitude/longitude for stored records that only
have a text address — currently the Dallas, Tarrant, and Collin CAD
parcels (Denton's source already includes coordinates; see
pipelines/housing/denton_cad.py).

Uses the Census Bureau's free Bulk Geocoding API
(https://geocoding.geo.census.gov/geocoder/Geocoding_Services.html) — no
key required, no per-request cost, matched against the same TIGER/Line
address-range data referenced elsewhere in this project. It accepts up to
10,000 addresses per request (its documented limit).

Verified against a real batch call (2026-09): the response is a CSV with
one row per input address — id, input address, match status
("Match"/"No_Match"), and, only on a match, match type, matched address, a
combined "longitude,latitude" field, TIGER line id, and side.

Not every address matches. In testing, a legitimate, currently-occupied
apartment address failed to match (newer developments and non-standard
address formats are the main causes) — this is logged as an unmatched
count per batch rather than silently swallowed, since it's a real data
gap, not a bug to hide.
"""
from __future__ import annotations

import csv
import io
import logging

from foodaccess.common.http_client import post_multipart
from foodaccess.storage.database import get_connection

logger = logging.getLogger(__name__)

GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
BENCHMARK = "Public_AR_Current"
BATCH_SIZE = 10000  # Census's documented per-request maximum
BATCH_TIMEOUT_SECONDS = 300  # a full 10k-address batch can take minutes server-side


def fetch_addresses_to_geocode() -> list[dict]:
    """Find housing_properties rows with an address but no coordinates yet."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT source, source_id, address, city, state, zip_code
            FROM housing_properties
            WHERE latitude IS NULL AND address IS NOT NULL AND address != ''
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _build_batch_csv(addresses: list[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in addresses:
        batch_id = f"{row['source']}::{row['source_id']}"
        writer.writerow(
            [batch_id, row["address"], row.get("city") or "", row.get("state") or "", row.get("zip_code") or ""]
        )
    return buffer.getvalue().encode("utf-8")


def geocode_batch(addresses: list[dict]) -> str:
    """POST one batch (<=10,000 addresses) to the Census geocoder; return the raw CSV response."""
    csv_bytes = _build_batch_csv(addresses)
    return post_multipart(
        GEOCODER_URL,
        files={"addressFile": ("addresses.csv", csv_bytes, "text/csv")},
        data={"benchmark": BENCHMARK},
        timeout=BATCH_TIMEOUT_SECONDS,
    )


def transform(raw_csv_text: str) -> list[dict]:
    """Parse the Census response CSV into source/source_id/latitude/longitude records for matches."""
    matched: list[dict] = []
    unmatched = 0

    for row in csv.reader(io.StringIO(raw_csv_text)):
        if len(row) < 3:
            continue
        batch_id, _input_address, match_status = row[0], row[1], row[2]
        if match_status != "Match":
            unmatched += 1
            continue

        longitude_str, latitude_str = row[5].split(",")
        source, source_id = batch_id.split("::", 1)
        matched.append(
            {
                "source": source,
                "source_id": source_id,
                "latitude": float(latitude_str),
                "longitude": float(longitude_str),
            }
        )

    if unmatched:
        logger.warning("%d of %d addresses in this batch did not geocode", unmatched, unmatched + len(matched))
    return matched


def store(records: list[dict]) -> int:
    if not records:
        return 0
    with get_connection() as conn:
        conn.executemany(
            """
            UPDATE housing_properties SET latitude = :latitude, longitude = :longitude
            WHERE source = :source AND source_id = :source_id
            """,
            records,
        )
    logger.info("Updated coordinates for %d housing_properties rows", len(records))
    return len(records)


def _chunk(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def run() -> int:
    addresses = fetch_addresses_to_geocode()
    logger.info("%d housing_properties rows need geocoding", len(addresses))
    if not addresses:
        return 0

    total_updated = 0
    for i, batch in enumerate(_chunk(addresses, BATCH_SIZE), start=1):
        logger.info("Geocoding batch %d (%d addresses)", i, len(batch))
        raw_csv_text = geocode_batch(batch)
        total_updated += store(transform(raw_csv_text))

    return total_updated


if __name__ == "__main__":
    run()
