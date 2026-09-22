"""
Collin Central Appraisal District (CCAD) parcel data — multifamily parcels.

Unlike Dallas and Tarrant, Collin publishes its full appraisal roll as a
live Socrata dataset on the Texas open data portal
(https://collincad.org/open-data-portal/, "Collin CAD Appraisal Data") —
queryable directly via the SODA API, no bulk file download or ZIP/CSV
parsing needed. Verified against a real query (2026-09).

propCategoryCode follows the same statewide PTAD category scheme seen in
Dallas/Tarrant: "B" = Multi-Family Residential (4,577 real rows). This
pipeline deliberately does NOT include the "MFU" (multi-family-use)
propUseCode on its own — a real sample of category "A" + "MFU" rows turned
out to be single-family build-to-rent homes (individual houses, one per
propid, no imprvUnits), which isn't the dense-apartment-building signal
this project wants; sticking to category "B" keeps the definition
consistent with how Dallas (SPTD B11/B12) and Tarrant (Property_Class
B/BC) are scoped.

imprvUnits gives a real unit count when present, but confirmed against a
real pull that most category-B rows (roughly 5 out of 6) don't have it
populated — leave it None rather than guess. situsConcat/situsZip give a
full address including zip (unlike Tarrant, which publishes none). No
coordinates are included — see dallas_cad.py's note on geocoding as a
shared follow-up step.
"""
from __future__ import annotations

import logging

from config import settings
from foodaccess.common.http_client import fetch_json
from foodaccess.pipelines.housing.models import MARKET_RATE, HousingProperty
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)

PAGE_SIZE = 2000


def fetch() -> list[dict]:
    """Page through the Socrata dataset for category-B (multi-family) parcels."""
    rows: list[dict] = []
    offset = 0
    while True:
        params = {
            "$where": "propcategorycode='B'",
            "$select": (
                "propid,ownername,dbaname,situsconcat,situscity,situszip,"
                "imprvyearbuilt,imprvunits,currvalmarket"
            ),
            "$limit": PAGE_SIZE,
            "$offset": offset,
        }
        page = fetch_json(settings.COLLIN_CAD_SODA_ENDPOINT, params=params)
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    logger.info("Fetched %d Collin County multi-family parcel rows", len(rows))
    return rows


def _to_int(value: str | None) -> int | None:
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def transform(raw_rows: list[dict]) -> list[HousingProperty]:
    records = [
        HousingProperty(
            source="county_parcel_collin",
            source_id=row["propid"],
            name=(row.get("dbaname") or "").strip() or None,
            property_type=MARKET_RATE,
            address=(row.get("situsconcat") or "").split(",")[0].strip() or None,
            city=(row.get("situscity") or "").strip().title() or None,
            state="TX",
            zip_code=(row.get("situszip") or "").strip() or None,
            county_fips="48085",  # Collin County
            latitude=None,
            longitude=None,
            total_units=_to_int(row.get("imprvunits")),
            is_subsidized=None,
        )
        for row in raw_rows
    ]
    logger.info("Parsed %d Collin County multifamily parcels", len(records))
    return records


def store(records: list[HousingProperty]) -> int:
    fetched_at = utcnow_iso()
    rows = [r.to_row(fetched_at) for r in records]
    count = upsert_records("housing_properties", rows, key_fields=["source", "source_id"])
    logger.info("Upserted %d Collin County parcel rows", count)
    return count


def run() -> int:
    raw_rows = fetch()
    records = transform(raw_rows)
    return store(records)


if __name__ == "__main__":
    run()
