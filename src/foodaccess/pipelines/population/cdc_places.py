"""
CDC PLACES: tract-level obesity prevalence.

PLACES values are small-area *model estimates* (from BRFSS survey data plus
ACS covariates), not a direct census of every tract — treat them as
modeled prevalence, not measured fact, when presenting this on the map.
"""
from __future__ import annotations

import logging

from config import settings
from foodaccess.common.http_client import fetch_json
from foodaccess.pipelines.population.models import TractHealthEstimate
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)

MEASURE_IDS = ["OBESITY"]


def fetch() -> list[dict]:
    """Query the CDC PLACES Socrata endpoint for DFW-county tract rows."""
    county_list = ",".join(f"'{fips}'" for fips in settings.DFW_COUNTY_FIPS)
    measure_list = ",".join(f"'{m}'" for m in MEASURE_IDS)
    where_clause = f"countyfips in ({county_list}) AND measureid in ({measure_list})"

    params = {
        "$where": where_clause,
        "$select": "locationname,countyfips,measureid,short_question_text,data_value,year",
        "$limit": 50000,
    }
    headers = {"X-App-Token": settings.CDC_APP_TOKEN} if settings.CDC_APP_TOKEN else None

    logger.info("Fetching CDC PLACES data for measures %s", MEASURE_IDS)
    rows = fetch_json(settings.CDC_PLACES_TRACT_ENDPOINT, params=params, headers=headers)
    logger.info("Fetched %d PLACES rows", len(rows))
    return rows


def transform(raw_rows: list[dict]) -> list[TractHealthEstimate]:
    records: list[TractHealthEstimate] = []

    for row in raw_rows:
        data_value = row.get("data_value")
        year = row.get("year")

        records.append(
            TractHealthEstimate(
                tract_geoid=row["locationname"],
                measure_id=row["measureid"],
                measure_name=row.get("short_question_text"),
                data_value=float(data_value) if data_value not in (None, "") else None,
                year=int(year) if year else 0,
            )
        )

    return records


def store(records: list[TractHealthEstimate]) -> int:
    fetched_at = utcnow_iso()
    rows = [r.to_row(fetched_at) for r in records]
    count = upsert_records("tract_health_estimates", rows, key_fields=["tract_geoid", "measure_id", "year"])
    logger.info("Upserted %d tract health estimate rows", count)
    return count


def run() -> int:
    raw_rows = fetch()
    records = transform(raw_rows)
    return store(records)


if __name__ == "__main__":
    run()
