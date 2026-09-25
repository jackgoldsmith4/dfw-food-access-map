"""
TDHCA (Texas Dept. of Housing & Community Affairs) Housing Tax Credit
Property Inventory.

Verified against a real download (2026-09), found via TDHCA's "Apply for
Funds" page: a clean, stable Excel file (HTCPropertyInventory_2.xlsx),
updated monthly as new 4% HTC applications are approved, no bot-protection
on the download. It's a genuinely good source — 3,356 statewide LIHTC
properties, and 85% of rows already include Latitude/Longitude directly
(no geocoding needed for those; the rest fall through to the geocoding
pipeline like any other address-only housing row, since it just looks for
NULL coordinates regardless of source).

This is Texas-specific and catches recently-approved deals faster than
HUD's national LIHTC database (hud_lihtc.py) — the two overlap
substantially, so expect the same physical property to appear from both
sources under different source_id values; deduplicating across sources by
address/name is a later data-quality step, not done here.

Population Served is used as a direct senior-housing flag — more
reliable than HUD's inferred 202/811 indicator (see hud_resource_locator.py)
since TDHCA states the target population outright rather than inferring
it from overlapping program codes. Verified the real category set
against a real download (2026-09, statewide): General (2285), Elderly
(874), Elderly Limitation (57), Supportive Housing (43), Elderly
Preference (28) — "Elderly Limitation" and "Elderly Preference" are also
age-restricted-adjacent and are now treated as senior, not just an exact
"Elderly" match. Missing "Population Served" is left unknown (None), not
collapsed into "not senior" — a bug the first version of this check had
(`value == "Elderly"` silently evaluates to `False` when `value` is
`None`, not `None`).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from config import settings
from foodaccess.common.http_client import download_file
from foodaccess.pipelines.housing.models import LIHTC, HousingProperty
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)

RAW_FILE_PATH = settings.RAW_HOUSING_DIR / "tdhca_htc_inventory.xlsx"
SHEET_NAME = "PropInventory"


def fetch() -> Path:
    logger.info("Fetching TDHCA HTC Property Inventory")
    return download_file(settings.TDHCA_HTC_REPORT_URL, RAW_FILE_PATH)


def _clean(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


SENIOR_POPULATION_SERVED = {"Elderly", "Elderly Limitation", "Elderly Preference"}


def _is_senior_housing(population_served) -> bool | None:
    population_served = _clean(population_served)
    if population_served is None:
        return None
    return population_served.strip() in SENIOR_POPULATION_SERVED


def _to_int(value) -> int | None:
    value = _clean(value)
    return int(value) if value else None


def _to_zip(value) -> str | None:
    value = _clean(value)
    return str(int(value))[:5] if value else None


def transform(raw_path: Path) -> list[HousingProperty]:
    df = pd.read_excel(raw_path, sheet_name=SHEET_NAME)
    df.columns = [str(c).strip() for c in df.columns]

    county_fips_by_name = {name: fips for fips, name in settings.DFW_COUNTY_FIPS.items()}
    df = df[df["Project County"].isin(county_fips_by_name)]

    records = []
    for _, row in df.iterrows():
        tdhca_num = _clean(row.get("TDHCA#"))
        if tdhca_num is None:
            continue  # no stable id to key on

        latitude = _clean(row.get("Latitude"))
        longitude = _clean(row.get("Longitude"))

        records.append(
            HousingProperty(
                source="tdhca_htc",
                source_id=str(tdhca_num),
                name=_clean(row.get("Development Name")),
                property_type=LIHTC,
                address=_clean(row.get("Project Address")),
                city=_clean(row.get("Project City")),
                state="TX",
                zip_code=_to_zip(row.get("Zip Code")),
                county_fips=county_fips_by_name[row["Project County"]],
                latitude=float(latitude) if latitude is not None else None,
                longitude=float(longitude) if longitude is not None else None,
                total_units=_to_int(row.get("Total Units")),
                is_senior_housing=_is_senior_housing(row.get("Population Served")),
                is_subsidized=True,
                raw_json=json.dumps({k: str(v) for k, v in row.items() if _clean(v) is not None}),
            )
        )

    logger.info("Parsed %d DFW TDHCA HTC properties", len(records))
    return records


def store(records: list[HousingProperty]) -> int:
    fetched_at = utcnow_iso()
    rows = [r.to_row(fetched_at) for r in records]
    count = upsert_records("housing_properties", rows, key_fields=["source", "source_id"])
    logger.info("Upserted %d TDHCA rows", count)
    return count


def run() -> int:
    raw_path = fetch()
    records = transform(raw_path)
    return store(records)


if __name__ == "__main__":
    run()
