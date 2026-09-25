"""
HUD eGIS Resource Locator: public housing buildings and project-based
assisted multifamily properties (Section 8, 202, 811, etc.).

Covers subsidized housing only — combine with hud_lihtc.py and the county
CAD parcel pipelines for market-rate multifamily coverage.

Verified against real queries (2026-09) of both FeatureServer layers (URLs
confirmed via the DCAT feed at https://hudgis-hud.opendata.arcgis.com/ —
see config.settings.HUD_RESOURCE_LOCATOR_FEATURE_SERVERS). Both layers
already include coordinates (LAT/LON) directly, no geocoding needed.
Text fields (STD_ADDR, STD_CITY, CNTY_NM2KX) come back fixed-width,
padded with trailing spaces — stripped here.

"Public Housing Buildings" is building-level, not development-level: a
single housing authority development can appear as many building rows,
and unit counts (TOTAL_DWELLING_UNITS) are per building, not per project —
a real Dallas example ("Barbara Jordan Square") is a scattered-site
project with many 1-unit building rows. That's the right granularity for
mapping individual structures, just not for "how big is this development."

`is_senior_housing` is derived from PCT_AGE62PLUS (the real, measured
share of residents 62+), never from IS_202_811_IND/IS_ASSISTED_LIVING_IND
— confirmed against a real pull that those program-eligibility flags are
actively unreliable as a senior-housing signal: Section 811 is
specifically for people *under* 62 with disabilities, but HUD reports it
through the same combined "202_811" indicator as Section 202 (elderly),
so a disability group home with 0% elderly residents (e.g. "ACCESSIBLE
RESIDENCES," 100% PCT_DISABLED_ALL, 31.6% PCT_AGE62PLUS) was getting
flagged senior by that flag alone. The real PCT_AGE62PLUS distribution
across a real pull is cleanly bimodal (25 properties under 20% elderly,
47 over 95%, only 8 in 50-80%), so 80% is used as the cutoff — it also
matches the Housing for Older Persons Act's legal threshold (80%+
occupancy by a 55+ resident) for an age-restricted community, not an
arbitrary number. When PCT_AGE62PLUS itself isn't on file (-4, HUD's
"not available" sentinel — not a real 0%), this is left `None` rather
than falling back to the program flag: real named examples on file with
no percentage data at all (e.g. "Community Options Carrollton," a known
IDD group-home operator, not a senior provider) confirm the flag is
wrong there too, so guessing via it is worse than admitting "unknown."
"""
from __future__ import annotations

import json
import logging

from config import settings
from foodaccess.common.http_client import fetch_arcgis_features
from foodaccess.pipelines.housing.models import PUBLIC_HOUSING, SUBSIDIZED_MULTIFAMILY, HousingProperty
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)

PUBLIC_HOUSING_FIELDS = (
    "OBJECTID,PROJECT_NAME,STD_ADDR,STD_CITY,STD_ST,STD_ZIP5,TOTAL_DWELLING_UNITS,"
    "CURCNTY,CNTY_NM2KX,LAT,LON,PCT_AGE62PLUS"
)
MULTIFAMILY_ASSISTED_FIELDS = (
    "OBJECTID,PROPERTY_NAME_TEXT,STD_ADDR,STD_CITY,STD_ST,STD_ZIP5,TOTAL_ASSISTED_UNIT_COUNT,"
    "TOTAL_UNIT_COUNT,CURCNTY,CNTY_NM2KX,IS_202_811_IND,IS_NURSING_HOME_IND,IS_ASSISTED_LIVING_IND,LAT,LON,"
    "PCT_AGE62PLUS"
)

SENIOR_PCT_THRESHOLD = 80  # matches HOPA's 80%-occupancy bar for a legally age-restricted community
NOT_AVAILABLE_SENTINEL = -4  # HUD's "not available" marker on PCT_* fields — not a real 0%


def _is_senior_housing(props: dict) -> bool | None:
    pct = props.get("PCT_AGE62PLUS")
    if pct is None or pct == NOT_AVAILABLE_SENTINEL:
        return None
    return pct >= SENIOR_PCT_THRESHOLD


def _where_clause() -> str:
    county_codes = ", ".join(f"'{fips[2:]}'" for fips in settings.DFW_COUNTY_FIPS)
    return f"STD_ST='TX' AND CURCNTY IN ({county_codes})"


def fetch() -> dict[str, list[dict]]:
    where = _where_clause()
    servers = settings.HUD_RESOURCE_LOCATOR_FEATURE_SERVERS

    public_housing = fetch_arcgis_features(servers["public_housing"], where=where, out_fields=PUBLIC_HOUSING_FIELDS)
    logger.info("Fetched %d public housing buildings", len(public_housing))

    multifamily_assisted = fetch_arcgis_features(
        servers["multifamily_assisted"], where=where, out_fields=MULTIFAMILY_ASSISTED_FIELDS
    )
    logger.info("Fetched %d assisted multifamily properties", len(multifamily_assisted))

    return {"public_housing": public_housing, "multifamily_assisted": multifamily_assisted}


def _strip(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _county_fips(props: dict) -> str | None:
    curcnty = _strip(props.get("CURCNTY"))
    return f"{settings.STATE_FIPS}{curcnty}" if curcnty else None


def transform(raw_by_layer: dict[str, list[dict]]) -> list[HousingProperty]:
    records: list[HousingProperty] = []

    for feature in raw_by_layer.get("public_housing", []):
        props = feature.get("properties", {})
        records.append(
            HousingProperty(
                source="hud_public_housing",
                source_id=str(props["OBJECTID"]),
                name=_strip(props.get("PROJECT_NAME")),
                property_type=PUBLIC_HOUSING,
                address=_strip(props.get("STD_ADDR")),
                city=_strip(props.get("STD_CITY")),
                state=_strip(props.get("STD_ST")),
                zip_code=_strip(props.get("STD_ZIP5")),
                county_fips=_county_fips(props),
                latitude=props.get("LAT"),
                longitude=props.get("LON"),
                total_units=props.get("TOTAL_DWELLING_UNITS"),
                is_senior_housing=_is_senior_housing(props),
                is_subsidized=True,
                raw_json=json.dumps(props),
            )
        )

    for feature in raw_by_layer.get("multifamily_assisted", []):
        props = feature.get("properties", {})
        is_senior_housing = _is_senior_housing(props)
        records.append(
            HousingProperty(
                source="hud_multifamily_assisted",
                source_id=str(props["OBJECTID"]),
                name=_strip(props.get("PROPERTY_NAME_TEXT")),
                property_type=SUBSIDIZED_MULTIFAMILY,
                address=_strip(props.get("STD_ADDR")),
                city=_strip(props.get("STD_CITY")),
                state=_strip(props.get("STD_ST")),
                zip_code=_strip(props.get("STD_ZIP5")),
                county_fips=_county_fips(props),
                latitude=props.get("LAT"),
                longitude=props.get("LON"),
                total_units=props.get("TOTAL_ASSISTED_UNIT_COUNT") or props.get("TOTAL_UNIT_COUNT"),
                is_senior_housing=is_senior_housing,
                is_subsidized=True,
                raw_json=json.dumps(props),
            )
        )

    logger.info("Parsed %d HUD housing records", len(records))
    return records


def store(records: list[HousingProperty]) -> int:
    fetched_at = utcnow_iso()
    rows = [r.to_row(fetched_at) for r in records]
    count = upsert_records("housing_properties", rows, key_fields=["source", "source_id"])
    logger.info("Upserted %d HUD Resource Locator rows", count)
    return count


def run() -> int:
    raw = fetch()
    records = transform(raw)
    return store(records)


if __name__ == "__main__":
    run()
