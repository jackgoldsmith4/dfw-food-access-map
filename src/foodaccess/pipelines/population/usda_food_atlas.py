"""
USDA SNAP-authorized Retailer Access Map (SRAM) — tract-level food access.

Verified against a real download (2026-09): USDA renamed the classic "Food
Access Research Atlas" to the "Large Retailer Access Map" (LRAM) in July
2026 and introduced SRAM alongside it. LRAM's data is stale (last real
vintage: 2019) and won't refresh until winter 2026-27; SRAM is the current
one (2025 vintage) and is what this pipeline uses — found via
https://www.ers.usda.gov/data-products/food-access-research-atlas/download-the-data.

The download is a single ~110MB Excel workbook with several sheets. This
pipeline reads two of them, joined on CensusTract20:
  - "GeneralTractCharacteristic Data": population, urban flag, poverty
    rate, income, SNAP/demographic counts.
  - "Driving Distance Data": DD_SRAM_-prefixed low-income-low-access
    flags and access shares, computed using actual road-network driving
    distance (not straight-line) — a real improvement over the classic
    Atlas, which only had straight-line distance. A parallel
    "Straight-Line Distance Data" sheet also exists but isn't used here;
    driving distance is the more realistic signal for "can someone
    actually get to a store."

Read directly via openpyxl in read-only/streaming mode rather than
pandas.read_excel, since loading an ~85,000-row-per-sheet workbook fully
into memory is unnecessary when only ~1,500 DFW-metro tracts are kept.
"""
from __future__ import annotations

import logging
from pathlib import Path

import openpyxl

from config import settings
from foodaccess.common.http_client import download_file
from foodaccess.pipelines.population.models import FoodAccessAtlasRecord
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)

RAW_FILE_PATH = settings.RAW_POPULATION_DIR / "usda_sram.xlsx"

CHARACTERISTICS_SHEET = "GeneralTractCharacteristic Data"
DRIVING_DISTANCE_SHEET = "Driving Distance Data"

# The low-income-low-access definition most commonly cited as "food
# desert": low income, and beyond 1 mile (urban) / 10 miles (rural) from
# the nearest SNAP-authorized retailer, via driving distance.
LILA_FLAG_COLUMN = "DD_SRAM_LILATracts_1And10"
LOW_ACCESS_SHARE_COLUMN = "DD_SRAM_lapophalfshare"


def fetch() -> Path:
    logger.info("Fetching USDA SRAM data")
    return download_file(settings.USDA_FOOD_ACCESS_ATLAS_URL, RAW_FILE_PATH)


def _sheet_rows_by_header(ws) -> tuple[list[str], "openpyxl.worksheet._read_only.ReadOnlyWorksheet"]:
    """SRAM sheets have a title in row 1 and real headers in row 2."""
    rows = ws.iter_rows(values_only=True)
    next(rows)  # title row
    header = next(rows)
    return list(header), rows


def transform(raw_path: Path) -> list[FoodAccessAtlasRecord]:
    dfw_codes = set(settings.DFW_COUNTY_FIPS)
    wb = openpyxl.load_workbook(raw_path, read_only=True, data_only=True)

    # Pass 1: tract characteristics, scoped to DFW tracts.
    ws = wb[CHARACTERISTICS_SHEET]
    header, rows = _sheet_rows_by_header(ws)
    col = {name: i for i, name in enumerate(header) if name}

    missing = [c for c in ("CensusTract20", "Urban", "POP2020") if c not in col]
    if missing:
        raise NotImplementedError(
            f"USDA SRAM '{CHARACTERISTICS_SHEET}' sheet is missing expected columns {missing}. "
            f"Actual columns: {header}. USDA may have changed the SRAM layout again — update this module."
        )

    tracts: dict[str, dict] = {}
    for row in rows:
        tract_geoid = str(row[col["CensusTract20"]])
        if tract_geoid[:5] not in dfw_codes:
            continue
        tracts[tract_geoid] = {
            "urban": row[col["Urban"]],
            "population": row[col["POP2020"]],
        }

    # Pass 2: driving-distance access flags, for the same tracts.
    ws = wb[DRIVING_DISTANCE_SHEET]
    header, rows = _sheet_rows_by_header(ws)
    col = {name: i for i, name in enumerate(header) if name}

    missing = [c for c in ("CensusTract20", LILA_FLAG_COLUMN, LOW_ACCESS_SHARE_COLUMN) if c not in col]
    if missing:
        raise NotImplementedError(
            f"USDA SRAM '{DRIVING_DISTANCE_SHEET}' sheet is missing expected columns {missing}. "
            f"Actual columns: {header}. USDA may have changed the SRAM layout again — update this module."
        )

    for row in rows:
        tract_geoid = str(row[col["CensusTract20"]])
        target = tracts.get(tract_geoid)
        if target is None:
            continue
        target["low_income_low_access"] = row[col[LILA_FLAG_COLUMN]]
        target["pct_low_access_half_mile"] = row[col[LOW_ACCESS_SHARE_COLUMN]]

    wb.close()

    records = [
        FoodAccessAtlasRecord(
            tract_geoid=geoid,
            year=2025,
            urban=data.get("urban"),
            population=data.get("population"),
            low_income_low_access=data.get("low_income_low_access"),
            pct_low_access_half_mile=data.get("pct_low_access_half_mile"),
        )
        for geoid, data in tracts.items()
    ]

    logger.info("Parsed %d DFW tract rows from USDA SRAM", len(records))
    return records


def store(records: list[FoodAccessAtlasRecord]) -> int:
    fetched_at = utcnow_iso()
    rows = [r.to_row(fetched_at) for r in records]
    count = upsert_records("food_access_atlas", rows, key_fields=["tract_geoid", "year", "source"])
    logger.info("Upserted %d USDA SRAM rows", count)
    return count


def run() -> int:
    raw_path = fetch()
    records = transform(raw_path)
    return store(records)


if __name__ == "__main__":
    run()
