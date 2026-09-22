"""
Feeding America "Map the Meal Gap" county-level food insecurity rate.

Feeding America doesn't publish this as an official bulk-download API —
their research pages point to a report plus a data-request form. But
their own interactive map (map.feedingamerica.org) renders from a plain
JSON endpoint loaded client-side, found by inspecting that page's network
requests in a browser (2026-09) and confirmed to work with a normal HTTP
client, no auth or browser required: config.settings.FEEDING_AMERICA_MAPDATA_URL.
One request returns every U.S. county in a single JSON payload — no
per-county requests needed.

This is undocumented and informal, not an endpoint Feeding America
publishes or supports as an API — it could change or disappear without
notice, unlike the other sources in this project. It's the same data
their own public map displays, not anything behind a paywall or login.

Remember this source is COUNTY-level only — there is no tract-level food
insecurity product from Feeding America. A tract-level estimate means
disaggregating this county rate using a proxy (e.g. ACS poverty/SNAP
rate), which belongs in the map's compute stage, not here.
"""
from __future__ import annotations

import logging

from config import settings
from foodaccess.common.http_client import fetch_json
from foodaccess.pipelines.population.models import FoodInsecurityCounty
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)


def fetch() -> list[dict]:
    params = {"maptype": "county", "year": settings.FEEDING_AMERICA_YEAR, "type": "overall"}
    logger.info("Fetching Feeding America county-level data for %s", settings.FEEDING_AMERICA_YEAR)
    data = fetch_json(settings.FEEDING_AMERICA_MAPDATA_URL, params=params)
    counties = data.get("county", [])
    logger.info("Fetched %d counties nationally", len(counties))
    return counties


def transform(raw_counties: list[dict]) -> list[FoodInsecurityCounty]:
    dfw_codes = set(settings.DFW_COUNTY_FIPS)

    records = [
        FoodInsecurityCounty(
            county_fips=county["fips"],
            year=settings.FEEDING_AMERICA_YEAR,
            food_insecurity_rate=county.get("insecurity"),
        )
        for county in raw_counties
        if county.get("fips") in dfw_codes
    ]

    logger.info("Parsed %d DFW county food insecurity rows", len(records))
    return records


def store(records: list[FoodInsecurityCounty]) -> int:
    fetched_at = utcnow_iso()
    rows = [r.to_row(fetched_at) for r in records]
    count = upsert_records("food_insecurity_county", rows, key_fields=["county_fips", "year", "source"])
    logger.info("Upserted %d county food insecurity rows", count)
    return count


def run() -> int:
    raw_counties = fetch()
    records = transform(raw_counties)
    return store(records)


if __name__ == "__main__":
    run()
