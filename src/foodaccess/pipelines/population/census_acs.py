"""
Census ACS 5-Year estimates: population, households, income, poverty, and
SNAP participation, at census-tract granularity for the DFW metro.

Values are 5-year rolling averages (per settings.CENSUS_ACS_YEAR) and carry
margins of error not captured here — treat tract-level point estimates in
low-population tracts as approximate, not exact.
"""
from __future__ import annotations

import logging

from config import settings
from foodaccess.common.http_client import fetch_json
from foodaccess.pipelines.population.models import TractDemographics
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)

# ACS 5-Year detailed table variables.
VARIABLES = {
    "B01003_001E": "total_population",
    "B11001_001E": "total_households",
    "B19013_001E": "median_household_income",
    "B17001_001E": "poverty_universe",
    "B17001_002E": "poverty_count",
    "B22010_001E": "snap_universe",
    "B22010_002E": "snap_households",
}


def fetch() -> list[dict]:
    """
    Query the ACS 5-Year API once per DFW county (tract:* within that
    county) and return the raw rows tagged with their source county.

    Queried per county rather than once for the whole state so a single
    slow/failing county doesn't require re-fetching the entire metro.
    """
    get_clause = "NAME," + ",".join(VARIABLES.keys())
    all_rows: list[dict] = []

    for county_fips, county_name in settings.DFW_COUNTY_FIPS.items():
        county_code = county_fips[2:]  # strip the "48" state prefix
        params = {
            "get": get_clause,
            "for": "tract:*",
            "in": f"state:{settings.STATE_FIPS} county:{county_code}",
        }
        if settings.CENSUS_API_KEY:
            params["key"] = settings.CENSUS_API_KEY

        logger.info("Fetching ACS data for %s County", county_name)
        response = fetch_json(settings.CENSUS_ACS_BASE_URL, params=params)

        header, *data_rows = response
        for row in data_rows:
            record = dict(zip(header, row))
            record["_county_fips"] = county_fips
            all_rows.append(record)

    logger.info("Fetched %d tract rows across %d counties", len(all_rows), len(settings.DFW_COUNTY_FIPS))
    return all_rows


def _to_number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    # Census API uses large negative sentinels (e.g. -666666666) for
    # "not available" instead of a null.
    return None if number < 0 else number


def _to_int(value: float | None) -> int | None:
    return int(value) if value is not None else None


def transform(raw_rows: list[dict]) -> list[TractDemographics]:
    records: list[TractDemographics] = []

    for row in raw_rows:
        tract_geoid = f"{row['state']}{row['county']}{row['tract']}"
        values = {label: _to_number(row.get(code)) for code, label in VARIABLES.items()}

        records.append(
            TractDemographics(
                tract_geoid=tract_geoid,
                year=settings.CENSUS_ACS_YEAR,
                county_fips=row["_county_fips"],
                total_population=_to_int(values["total_population"]),
                total_households=_to_int(values["total_households"]),
                median_household_income=values["median_household_income"],
                poverty_count=_to_int(values["poverty_count"]),
                poverty_universe=_to_int(values["poverty_universe"]),
                snap_households=_to_int(values["snap_households"]),
                snap_universe=_to_int(values["snap_universe"]),
            )
        )

    return records


def store(records: list[TractDemographics]) -> int:
    fetched_at = utcnow_iso()
    rows = [r.to_row(fetched_at) for r in records]
    count = upsert_records("tract_demographics", rows, key_fields=["tract_geoid", "year", "source"])
    logger.info("Upserted %d tract demographic rows", count)
    return count


def run() -> int:
    raw_rows = fetch()
    records = transform(raw_rows)
    return store(records)


if __name__ == "__main__":
    run()
