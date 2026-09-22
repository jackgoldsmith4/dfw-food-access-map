"""
Denton County parcel data — multifamily parcels.

Denton CAD's own site (dentoncad.com / denton.prodigycad.com) is a
JavaScript-only single-page app with no data exposed via plain HTTP — no
API to call, nothing to download. Verified against a real query (2026-09):
Denton County's GIS hub instead publishes the *same* appraisal data
pre-joined to parcel polygon geometry, in one ArcGIS MapServer layer
(https://data-dentoncounty.hub.arcgis.com/datasets/DentonCounty::parcels).
That's a meaningfully better source than the other three counties: this
is the only one of the four DFW CADs implemented so far where real
coordinates come from the source itself, rather than needing a separate
geocoding pass over an address string.

`stateCodes` holds a comma-separated list of PTAD-style category codes
present on the parcel (a parcel can carry more than one, e.g. "A4,B1").
Verified real values: "B1" = apartments (492 rows), "B2" = duplex (1,361
rows) — Denton doesn't use the "B"/"BC" spelling Dallas and Tarrant do.

No unit-count field exists here either (same gap as Tarrant) — total_units
is left None. Coordinates are a simple average of each parcel polygon's
vertices (requested pre-projected to WGS84 via the ArcGIS GeoJSON export),
not a true area-weighted centroid — close enough to place a marker, not
precise enough for anything that needs the exact geometric center.
"""
from __future__ import annotations

import logging

from config import settings
from foodaccess.common.http_client import fetch_arcgis_features
from foodaccess.pipelines.housing.models import MARKET_RATE, HousingProperty
from foodaccess.storage.database import upsert_records, utcnow_iso

logger = logging.getLogger(__name__)

MULTIFAMILY_CODES = ("B1", "B2")
WHERE_CLAUSE = " OR ".join(f"stateCodes LIKE '%{code}%'" for code in MULTIFAMILY_CODES)

OUT_FIELDS = (
    "pid,name,dba,stateCodes,situs_full_address,situsCity,situsZip,"
    "imprvActualYearBuilt,imprvMainArea,ownerMarketValue"
)


def fetch() -> list[dict]:
    features = fetch_arcgis_features(
        settings.DENTON_PARCELS_QUERY_URL, where=WHERE_CLAUSE, out_fields=OUT_FIELDS
    )
    logger.info("Fetched %d Denton County multi-family parcel features", len(features))
    return features


def _vertex_average_centroid(geometry: dict | None) -> tuple[float | None, float | None]:
    """Average every ring vertex's (lon, lat) as a cheap centroid approximation."""
    if not geometry:
        return None, None

    coords = geometry.get("coordinates")
    if not coords:
        return None, None

    def flatten(node):
        if isinstance(node[0], (int, float)):
            yield node
        else:
            for child in node:
                yield from flatten(child)

    points = list(flatten(coords))
    if not points:
        return None, None

    lon = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lat, lon


def transform(raw_features: list[dict]) -> list[HousingProperty]:
    records = []
    for feature in raw_features:
        props = feature.get("properties", {})
        lat, lon = _vertex_average_centroid(feature.get("geometry"))

        records.append(
            HousingProperty(
                source="county_parcel_denton",
                source_id=str(props["pid"]),
                name=(props.get("dba") or "").strip() or None,
                property_type=MARKET_RATE,
                address=(props.get("situs_full_address") or "").split(",")[0].strip() or None,
                city=(props.get("situsCity") or "").strip().title() or None,
                state="TX",
                zip_code=(props.get("situsZip") or "").strip()[:5] or None,
                county_fips="48121",  # Denton County
                latitude=lat,
                longitude=lon,
                total_units=None,  # no unit-count field exists in this source
                is_subsidized=None,
            )
        )

    logger.info("Parsed %d Denton County multifamily parcels", len(records))
    return records


def store(records: list[HousingProperty]) -> int:
    fetched_at = utcnow_iso()
    rows = [r.to_row(fetched_at) for r in records]
    count = upsert_records("housing_properties", rows, key_fields=["source", "source_id"])
    logger.info("Upserted %d Denton County parcel rows", count)
    return count


def run() -> int:
    raw_features = fetch()
    records = transform(raw_features)
    return store(records)


if __name__ == "__main__":
    run()
