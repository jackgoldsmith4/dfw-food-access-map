"""
Tarrant Appraisal District (TAD) parcel data — multifamily parcels.

Verified against a real download (2026-09) of TAD's pipe-delimited
"Standard Distribution" export — PropertyData(Delimited)_R.txt
(residential) and PropertyData(Delimited)_C.txt (commercial), found via
https://www.tad.org/resources/data-downloads. Each row is one account;
Property_Class classifies it (see Appendix C of TAD's
"PropertyData&PropertyLocationLayouts.pdf"): B = Multi-Family Residential,
BC = Multi-Family Commercial, B2/B3/B4 = duplex/triplex/quadplex. Only "B"
and "BC" actually appear in the real 2026 data (8,726 and 2,289 rows);
B2-B4 are documented but apparently unused in practice.

Two real limitations, confirmed against the actual files (not assumed):
  - TAD's export has NO unit-count field anywhere, for any property class.
    Property_Class tells you a parcel is an apartment complex, but not how
    many units it has. total_units is left None here — a different source
    (rent-roll data, HUD/LIHTC overlap, or manual research) would be
    needed to fill that in for Tarrant County specifically.
  - TAD does not publish a property zip code — confirmed blank even in
    their dedicated address-fields file. Only a numeric city code is
    available, mapped to a name via Appendix B of the same PDF.

Unlike Dallas, Situs_Address here is already a single combined address
string (house number + street), so no address-file join is needed. No
coordinates are included, same as Dallas — see dallas_cad.py's note on
geocoding as a shared follow-up step.
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

RAW_DIR = settings.RAW_HOUSING_DIR / "county_parcels"
RESIDENTIAL_FILE = RAW_DIR / "tarrant_property_data_r.zip"
COMMERCIAL_FILE = RAW_DIR / "tarrant_property_data_c.zip"

MULTIFAMILY_PROPERTY_CLASSES = {"B", "BC", "B2", "B3", "B4"}

# Appendix B city codes (zero-padded 3-digit, matching the real data's
# format) — best-effort transcription from TAD's documentation PDF; an
# unmapped code is kept as its raw string rather than dropped.
CITY_CODES = {
    "000": "Unincorporated Tarrant County",
    "001": "Azle", "002": "Bedford", "003": "Benbrook",
    "004": "Blue Mound", "005": "Colleyville", "006": "Crowley",
    "007": "Dalworthington Gardens", "008": "Edgecliff Village", "009": "Everman",
    "010": "Forest Hill", "011": "Grapevine", "013": "Keller", "014": "Kennedale",
    "015": "Lakeside", "016": "Lake Worth", "017": "Mansfield",
    "018": "North Richland Hills", "019": "Pantego", "020": "Richland Hills",
    "021": "Saginaw", "022": "Southlake", "023": "Westover Hills", "024": "Arlington",
    "025": "Euless", "026": "Fort Worth", "027": "Haltom City", "028": "Hurst",
    "029": "River Oaks", "030": "White Settlement", "031": "Watauga",
    "032": "Westworth Village", "033": "Burleson", "034": "Haslet", "035": "Briar",
    "036": "Pelican Bay", "037": "Westlake", "038": "Grand Prairie",
    "039": "Sansom Park", "040": "Newark", "042": "Flower Mound",
}


def fetch() -> dict[str, Path]:
    return {
        "residential": download_file(settings.TAD_RESIDENTIAL_DATA_URL, RESIDENTIAL_FILE),
        "commercial": download_file(settings.TAD_COMMERCIAL_DATA_URL, COMMERCIAL_FILE),
    }


def _parse_file(zip_path: Path) -> list[HousingProperty]:
    records: list[HousingProperty] = []
    with zipfile.ZipFile(zip_path) as zf:
        inner_name = zf.namelist()[0]  # each of these ZIPs contains exactly one .txt
        with io.TextIOWrapper(zf.open(inner_name), encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter="|")
            for row in reader:
                property_class = (row.get("Property_Class") or "").strip()
                if property_class not in MULTIFAMILY_PROPERTY_CLASSES:
                    continue

                city_code = (row.get("City") or "").strip()

                records.append(
                    HousingProperty(
                        source="county_parcel_tarrant",
                        source_id=row["Account_Num"],
                        name=None,  # TAD's export has no property/complex name field
                        property_type=MARKET_RATE,
                        address=(row.get("Situs_Address") or "").strip() or None,
                        city=CITY_CODES.get(city_code, city_code or None),
                        state="TX",
                        zip_code=None,  # not published by TAD — confirmed against a real pull
                        county_fips="48439",  # Tarrant County
                        latitude=None,
                        longitude=None,
                        total_units=None,  # no unit-count field exists in this source
                        is_subsidized=None,
                    )
                )
    return records


def transform(raw_paths: dict[str, Path]) -> list[HousingProperty]:
    records = _parse_file(raw_paths["residential"])
    records += _parse_file(raw_paths["commercial"])
    logger.info("Parsed %d Tarrant County multifamily parcels", len(records))
    return records


def store(records: list[HousingProperty]) -> int:
    fetched_at = utcnow_iso()
    rows = [r.to_row(fetched_at) for r in records]
    count = upsert_records("housing_properties", rows, key_fields=["source", "source_id"])
    logger.info("Upserted %d Tarrant County parcel rows", count)
    return count


def run() -> int:
    raw_paths = fetch()
    records = transform(raw_paths)
    return store(records)


if __name__ == "__main__":
    run()
