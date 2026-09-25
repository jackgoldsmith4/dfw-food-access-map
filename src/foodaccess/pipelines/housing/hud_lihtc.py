"""
HUD LIHTC (Low-Income Housing Tax Credit) database.

The authoritative national source for LIHTC-financed multifamily
properties, including ones placed in service too recently to have
propagated into the HUD eGIS Resource Locator.

MANUAL DOWNLOAD REQUIRED — see config.settings.HUD_LIHTC_FILE_PATH.
huduser.gov's entire domain sits behind an AWS WAF JavaScript challenge
that blocks any non-browser client (confirmed for both `curl` and
`requests`), so there is no automated fetch() for this source. Download
LIHTCPUB.ZIP yourself and extract it into place; fetch() just checks the
file is there.

Schema verified against the real file (2026-09, "1987-2024 Data
Dictionary (April 2026)" bundled in the ZIP). Two things worth knowing:
  - `openpyxl` cannot read this file — HUD's export writes an invalid
    OOXML attribute (`synchVertical` instead of the standard
    `syncVertical`) that trips openpyxl's schema parser. `python-calamine`
    (a Rust-based reader) tolerates it fine, so we use that engine here.
  - `fips2020` (2-digit state + 3-digit county + 6-digit tract) is 'X'-
    padded when HUD couldn't geocode a property (e.g. "48XXXXXXXXX") —
    those rows are excluded here even if they're genuinely in DFW, since
    there's no county to key on. Of the rows that DO resolve to a DFW
    county, all had coordinates directly in a real pull, so this mostly
    just drops legitimately unresolved records, not usable ones.
  - `trgt_eld` ("targets a specific population - elderly") is a clean,
    elderly-specific field per HUD's own data dictionary (1=Yes, 2=No, 0
    or blank=Not indicated) — unlike the eGIS Resource Locator's combined
    202/811 indicator (see hud_resource_locator.py), there's no
    conflation with disability-only housing here. The real bug was
    treating missing/0 as "No" instead of "unknown": nearly half of all
    national records have no value at all, and those were being asserted
    as confidently not-senior.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from config import settings
from foodaccess.pipelines.housing.models import LIHTC, HousingProperty
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)

RAW_FILE_PATH = settings.RAW_HOUSING_DIR / settings.HUD_LIHTC_FILE_PATH


def fetch() -> Path:
    if not RAW_FILE_PATH.exists():
        raise FileNotFoundError(
            f"{RAW_FILE_PATH} not found. This source requires a one-time manual download — "
            "see the module docstring and config.settings.HUD_LIHTC_FILE_PATH for exact steps."
        )
    return RAW_FILE_PATH


def _clean(value):
    return None if value is None or pd.isna(value) else value


def _is_senior_housing(trgt_eld) -> bool | None:
    """TRGT_ELD per HUD's own data dictionary: 1=Yes, 2=No, 0 or blank=Not
    indicated. Missing/0 must stay unknown, not collapse to "No" — nearly
    half of all national records have no value here at all."""
    trgt_eld = _clean(trgt_eld)
    if trgt_eld is None or trgt_eld == 0:
        return None
    return trgt_eld == 1


def transform(raw_path: Path) -> list[HousingProperty]:
    df = pd.read_excel(raw_path, engine="calamine")

    dfw_codes = set(settings.DFW_COUNTY_FIPS)
    df["_county_fips"] = df["fips2020"].astype(str).str[:5]
    df = df[df["_county_fips"].isin(dfw_codes)]

    records = []
    for _, row in df.iterrows():
        hud_id = _clean(row.get("hud_id"))
        if hud_id is None:
            continue

        latitude = _clean(row.get("latitude"))
        longitude = _clean(row.get("longitude"))
        total_units = _clean(row.get("n_unitsr"))

        records.append(
            HousingProperty(
                source="hud_lihtc",
                source_id=str(hud_id),
                name=_clean(row.get("project")),
                property_type=LIHTC,
                address=_clean(row.get("proj_add")),
                city=_clean(row.get("proj_cty")),
                state=_clean(row.get("proj_st")),
                zip_code=_clean(row.get("proj_zip")),
                county_fips=row["_county_fips"],
                latitude=float(latitude) if latitude is not None else None,
                longitude=float(longitude) if longitude is not None else None,
                total_units=int(total_units) if total_units is not None else None,
                is_senior_housing=_is_senior_housing(row.get("trgt_eld")),
                is_subsidized=True,
            )
        )

    logger.info("Parsed %d DFW LIHTC properties", len(records))
    return records


def store(records: list[HousingProperty]) -> int:
    fetched_at = utcnow_iso()
    rows = [r.to_row(fetched_at) for r in records]
    count = upsert_records("housing_properties", rows, key_fields=["source", "source_id"])
    logger.info("Upserted %d HUD LIHTC rows", count)
    return count


def run() -> int:
    raw_path = fetch()
    records = transform(raw_path)
    return store(records)


if __name__ == "__main__":
    run()
