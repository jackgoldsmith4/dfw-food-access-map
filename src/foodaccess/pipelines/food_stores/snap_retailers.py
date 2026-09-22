"""
USDA SNAP-authorized retailer locations.

This is the backbone food-store source: it's free, national, includes a
store-type classification, and (unlike scraping Google Maps) has no ToS
restriction on storing or displaying the data.

Verified against a real query (2026-09): USDA's retailer locator is a
live, queryable ArcGIS FeatureServer (found via the DCAT feed at
https://usda-snap-retailers-usda-fns.hub.arcgis.com/), not a static bulk
file — see config.settings.USDA_SNAP_RETAILER_QUERY_URL. Real distinct
Store_Type values, confirmed via a returnDistinctValues query: "Supermarket",
"Grocery Store", "Super Store", "Convenience Store", "Farmers and Markets",
"Specialty Store", "Restaurant Meals Program", "Other".
"""
from __future__ import annotations

import logging

from config import settings
from foodaccess.common.http_client import fetch_arcgis_features
from foodaccess.pipelines.food_stores.models import (
    CONVENIENCE,
    GROCERY,
    MASS_MERCHANDISER,
    OTHER,
    FoodStore,
)
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)

STORE_TYPE_MAP = {
    "supermarket": GROCERY,
    "grocery store": GROCERY,
    "super store": MASS_MERCHANDISER,
    "convenience store": CONVENIENCE,
}

OUT_FIELDS = (
    "Record_ID,Store_Name,Store_Street_Address,City,State,Zip_Code,County,"
    "Store_Type,Latitude,Longitude"
)


def _where_clause() -> str:
    county_list = ", ".join(f"'{name.upper()}'" for name in settings.DFW_COUNTY_FIPS.values())
    return f"State='TX' AND County IN ({county_list})"


def fetch() -> list[dict]:
    logger.info("Querying USDA SNAP retailer FeatureServer for DFW counties")
    features = fetch_arcgis_features(
        settings.USDA_SNAP_RETAILER_QUERY_URL, where=_where_clause(), out_fields=OUT_FIELDS
    )
    logger.info("Fetched %d SNAP-authorized stores in scope", len(features))
    return features


def _normalize_store_type(raw_type: str | None) -> str:
    if not raw_type:
        return OTHER
    return STORE_TYPE_MAP.get(raw_type.strip().lower(), OTHER)


def transform(raw_features: list[dict]) -> list[FoodStore]:
    county_fips_by_name = {name.upper(): fips for fips, name in settings.DFW_COUNTY_FIPS.items()}

    stores = []
    for feature in raw_features:
        props = feature.get("properties", {})
        county_name = (props.get("County") or "").strip().upper()

        stores.append(
            FoodStore(
                source="usda_snap",
                source_id=str(props["Record_ID"]),
                name=props.get("Store_Name"),
                store_type=_normalize_store_type(props.get("Store_Type")),
                raw_category=props.get("Store_Type"),
                address=props.get("Store_Street_Address"),
                city=props.get("City"),
                state=props.get("State"),
                zip_code=props.get("Zip_Code"),
                county_fips=county_fips_by_name.get(county_name),
                latitude=props.get("Latitude"),
                longitude=props.get("Longitude"),
                snap_authorized=True,
            )
        )

    logger.info("Parsed %d SNAP-authorized stores in scope", len(stores))
    return stores


def store(stores: list[FoodStore]) -> int:
    fetched_at = utcnow_iso()
    rows = [s.to_row(fetched_at) for s in stores]
    count = upsert_records("food_stores", rows, key_fields=["source", "source_id"])
    logger.info("Upserted %d SNAP retailer rows", count)
    return count


def run() -> int:
    raw_features = fetch()
    stores = transform(raw_features)
    return store(stores)


if __name__ == "__main__":
    run()
