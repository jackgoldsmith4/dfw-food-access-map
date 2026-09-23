"""
Census tract centroid + land area reference geometry.

The tract-level opportunity score needs each DFW tract's centroid (to
compute distance to the nearest food store, the same way a housing
point does) and land area (to turn a raw population count into an
actual density — "densely populated" was part of this project's
original brief from day one, and total_population alone can't tell a
dense urban tract from a sparse rural one of the same population).

Source: the Census Bureau's 2020 Gazetteer Files — a small,
state-specific plain-text table of every tract's GEOID, land/water area,
and centroid, published once per decennial census (verified real,
2026-09: https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_gaz_tracts_48.txt,
~7,000 Texas tracts, tab-delimited with trailing padding on each field).
This is a different Census product from the Bulk Geocoder used elsewhere
in this project (geocoding/census_geocoder.py, geocoding/tract_lookup.py)
— those go coordinate-or-address -> tract; a Gazetteer file already has
every tract's own centroid in one bulk download, so there's no reason to
query one tract at a time for data that's fixed for the whole decade.
"""
from __future__ import annotations

import logging

from config import settings
from foodaccess.common.http_client import fetch_text
from foodaccess.pipelines.population.models import TractGeometry
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)

GAZETTEER_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_gaz_tracts_48.txt"


def fetch() -> str:
    return fetch_text(GAZETTEER_URL)


def transform(raw_text: str) -> list[TractGeometry]:
    records: list[TractGeometry] = []
    lines = raw_text.splitlines()[1:]  # skip header row

    for line in lines:
        fields = [f.strip() for f in line.split("\t")]
        if len(fields) < 8:
            continue

        tract_geoid = fields[1]
        if tract_geoid[:5] not in settings.DFW_COUNTY_FIPS:
            continue

        records.append(
            TractGeometry(
                tract_geoid=tract_geoid,
                land_sqmi=float(fields[4]),
                centroid_lat=float(fields[6]),
                centroid_lon=float(fields[7]),
            )
        )

    return records


def store(records: list[TractGeometry]) -> int:
    fetched_at = utcnow_iso()
    rows = [r.to_row(fetched_at) for r in records]
    count = upsert_records("tract_geometry", rows, key_fields=["tract_geoid"])
    logger.info("Upserted %d tract geometry rows", count)
    return count


def run() -> int:
    raw_text = fetch()
    records = transform(raw_text)
    logger.info("Parsed %d DFW-metro tract geometry rows from the Gazetteer file", len(records))
    return store(records)


if __name__ == "__main__":
    run()
