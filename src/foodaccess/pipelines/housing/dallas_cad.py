"""
Dallas Central Appraisal District (DCAD) parcel roll — multifamily parcels.

This is the intended backbone for *market-rate* multifamily coverage in
Dallas County: HUD/TDHCA/LIHTC only cover subsidized housing, and DCAD's
parcel roll is the only source that includes every apartment complex and
duplex regardless of financing.

Verified against a real download (2026-09) of DCAD's "current ownership"
export — a ZIP of linked CSVs joined by ACCOUNT_NUM:
  - ACCOUNT_APPRL_YEAR.CSV: SPTD_CODE classifies each parcel (B11 =
    apartments, B12 = duplexes — see the bundled SPTD_CD_XREF.pdf) and
    DIVISION_CD says which detail table to join next (COM for B11, RES
    for B12).
  - ACCOUNT_INFO.CSV: owner name and property address.
  - COM_DETAIL.CSV: unit count, property name, year built (for B11/COM
    accounts — apartment complexes are appraised as commercial/income
    property in DCAD's system, not residential).
  - RES_DETAIL.CSV: unit count, year built (for B12/RES accounts).

None of these CSVs include coordinates — DCAD publishes parcel geometry
separately as a GIS shapefile product. Geocoding (or joining to that
shapefile) is a follow-up step; addresses are captured here so that can
happen later without re-parsing these files.

The files are large (roughly 200-350MB each uncompressed), so this reads
each CSV directly out of the ZIP as a stream rather than extracting or
loading it into a DataFrame — memory use stays bounded by the size of the
multifamily subset (a few tens of thousands of accounts), not the ~800k
total accounts in the county.
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from pathlib import Path

from config import settings
from foodaccess.common.http_client import download_file
from foodaccess.pipelines.housing.models import MARKET_RATE, HousingProperty
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)

RAW_FILE_PATH = settings.RAW_HOUSING_DIR / "county_parcels" / "dallas_cad_current.zip"

# SPTD codes for multifamily residential (see SPTD_CD_XREF.pdf inside the
# DCAD download): B11 = apartments, B12 = duplexes.
MULTIFAMILY_SPTD_CODES = {"B11", "B12"}


def fetch() -> Path:
    logger.info("Fetching DCAD current-ownership parcel roll")
    return download_file(settings.DCAD_CURRENT_ROLL_URL, RAW_FILE_PATH)


def _open_csv(zf: zipfile.ZipFile, name: str) -> csv.DictReader:
    return csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="utf-8-sig"))


def _to_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    value = _to_float(value)
    return int(value) if value is not None else None


def _classify_multifamily_accounts(zf: zipfile.ZipFile) -> dict[str, dict]:
    """Pass 1: find accounts classified as apartments/duplexes, keeping the latest appraisal year seen per account."""
    accounts: dict[str, dict] = {}
    for row in _open_csv(zf, "ACCOUNT_APPRL_YEAR.CSV"):
        sptd_code = row.get("SPTD_CODE")
        if sptd_code not in MULTIFAMILY_SPTD_CODES:
            continue

        account_num = row["ACCOUNT_NUM"]
        year = int(row["APPRAISAL_YR"])
        existing = accounts.get(account_num)
        if existing is None or year >= existing["appraisal_yr"]:
            accounts[account_num] = {
                "sptd_code": sptd_code,
                "division_cd": row.get("DIVISION_CD"),
                "appraisal_yr": year,
                "tot_val": _to_float(row.get("TOT_VAL")),
            }

    logger.info("Found %d multifamily-classified accounts (SPTD %s)", len(accounts), MULTIFAMILY_SPTD_CODES)
    return accounts


def _attach_account_info(zf: zipfile.ZipFile, accounts: dict[str, dict]) -> None:
    """Pass 2: attach owner/address fields for the accounts found in pass 1."""
    for row in _open_csv(zf, "ACCOUNT_INFO.CSV"):
        target = accounts.get(row["ACCOUNT_NUM"])
        if target is None or int(row["APPRAISAL_YR"]) != target["appraisal_yr"]:
            continue

        address_parts = [row.get("STREET_NUM"), row.get("STREET_HALF_NUM"), row.get("FULL_STREET_NAME")]
        target["address"] = " ".join(p.strip() for p in address_parts if p and p.strip()) or None
        target["name"] = (row.get("BIZ_NAME") or "").strip() or None
        target["city"] = (row.get("PROPERTY_CITY") or "").strip() or None
        target["zip_code"] = (row.get("PROPERTY_ZIPCODE") or "").strip()[:5] or None


def _attach_detail(zf: zipfile.ZipFile, accounts: dict[str, dict]) -> None:
    """Pass 3 & 4: attach unit count / property name / year built from the matching detail table."""
    for row in _open_csv(zf, "COM_DETAIL.CSV"):
        target = accounts.get(row["ACCOUNT_NUM"])
        if target is None or target["division_cd"] != "COM" or int(row["APPRAISAL_YR"]) != target["appraisal_yr"]:
            continue
        target["total_units"] = _to_int(row.get("NUM_UNITS"))
        target["year_built"] = _to_int(row.get("YEAR_BUILT"))
        property_name = (row.get("PROPERTY_NAME") or "").strip()
        if property_name:
            target["name"] = property_name  # more reliable than ACCOUNT_INFO.BIZ_NAME for apartment complexes

    for row in _open_csv(zf, "RES_DETAIL.CSV"):
        target = accounts.get(row["ACCOUNT_NUM"])
        if target is None or target["division_cd"] != "RES" or int(row["APPRAISAL_YR"]) != target["appraisal_yr"]:
            continue
        target["total_units"] = _to_int(row.get("NUM_UNITS"))
        target["year_built"] = _to_int(row.get("YR_BUILT"))


def transform(raw_path: Path) -> list[HousingProperty]:
    with zipfile.ZipFile(raw_path) as zf:
        accounts = _classify_multifamily_accounts(zf)
        _attach_account_info(zf, accounts)
        _attach_detail(zf, accounts)

    records = [
        HousingProperty(
            source="county_parcel_dallas",
            source_id=account_num,
            name=data.get("name"),
            property_type=MARKET_RATE,
            address=data.get("address"),
            city=data.get("city"),
            state="TX",
            zip_code=data.get("zip_code"),
            county_fips="48113",  # Dallas County
            latitude=None,   # DCAD's bulk CSVs carry no coordinates — see module docstring
            longitude=None,
            total_units=data.get("total_units"),
            is_subsidized=None,  # unknown from parcel data alone; cross-reference with HUD/LIHTC separately
        )
        for account_num, data in accounts.items()
        if data.get("address")  # a handful of accounts won't have a matching-year ACCOUNT_INFO row
    ]

    logger.info("Parsed %d Dallas County multifamily parcels", len(records))
    return records


def store(records: list[HousingProperty]) -> int:
    fetched_at = utcnow_iso()
    rows = [r.to_row(fetched_at) for r in records]
    count = upsert_records("housing_properties", rows, key_fields=["source", "source_id"])
    logger.info("Upserted %d Dallas County parcel rows", count)
    return count


def run() -> int:
    raw_path = fetch()
    records = transform(raw_path)
    return store(records)


if __name__ == "__main__":
    run()
