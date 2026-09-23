"""
Exports SQLite data to static GeoJSON files the map frontend reads
directly (web/data/*.geojson) — no vector tiles, just enough to see the
collected data on a map. Only rows with coordinates are included, and
soft-deleted rows (is_deleted, set by a manual edit — see
foodaccess.webapp) are excluded so a deletion made through the map
disappears from the exported data too. Each source's known coordinate
gaps are documented in the pipeline that produced it, not re-derived here.

webapp.py calls export_food_stores()/export_housing_properties() right
after an edit or delete so the static files stay in sync without a
separate manual export step.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from config import settings
from foodaccess.storage.database import get_connection

logger = logging.getLogger(__name__)

FOOD_STORE_COLUMNS = ["source", "source_id", "name", "store_type", "address", "city", "latitude", "longitude"]
FOOD_STORE_QUERY = (
    f"SELECT {', '.join(FOOD_STORE_COLUMNS)} FROM food_stores WHERE latitude IS NOT NULL AND is_deleted = 0"
)

# housing_properties gets its own query (below) rather than this simple
# column list, since it also joins in tract-level context for the
# opportunity score — kept here only as the reference list of its own
# columns for that query to select.
HOUSING_COLUMNS = [
    "h.source", "h.source_id", "h.name", "h.property_type", "h.address", "h.city",
    "h.total_units", "h.is_senior_housing", "h.is_subsidized", "h.latitude", "h.longitude",
]

# One row per tract exists in each table today (2023 census_acs5;
# 2025 usda_food_access_atlas — see their fetch pipelines), so this join
# can't fan out and duplicate housing rows. If a second vintage of either
# is ever pulled alongside the first, this needs a "pick the latest year"
# subquery instead of a bare join to keep that guarantee.
HOUSING_QUERY = f"""
    SELECT {', '.join(HOUSING_COLUMNS)},
           td.median_household_income AS tract_median_household_income,
           td.poverty_count AS tract_poverty_count,
           td.poverty_universe AS tract_poverty_universe,
           td.snap_households AS tract_snap_households,
           td.snap_universe AS tract_snap_universe,
           fa.pct_low_access_half_mile AS tract_pct_low_access_half_mile
    FROM housing_properties h
    LEFT JOIN tract_demographics td ON td.tract_geoid = h.tract_geoid
    LEFT JOIN food_access_atlas fa ON fa.tract_geoid = h.tract_geoid
    WHERE h.latitude IS NOT NULL AND h.is_deleted = 0
"""

# Each DFW tract as a single point at its centroid (tract_geometry —
# see pipelines/population/tract_geometry.py), joined with its
# population/income/poverty/SNAP and USDA low-access data. Same
# one-row-per-tract assumption as HOUSING_QUERY above. Feeds
# opportunity_tracts.html — a sibling to the housing ranking, scored the
# same way but for a whole tract regardless of what housing (if any)
# sits in it.
TRACT_QUERY = """
    SELECT tg.tract_geoid,
           tg.centroid_lat AS latitude, tg.centroid_lon AS longitude,
           tg.land_sqmi,
           td.total_population AS population,
           td.median_household_income,
           td.poverty_count, td.poverty_universe,
           td.snap_households, td.snap_universe,
           fa.pct_low_access_half_mile
    FROM tract_geometry tg
    LEFT JOIN tract_demographics td ON td.tract_geoid = tg.tract_geoid
    LEFT JOIN food_access_atlas fa ON fa.tract_geoid = tg.tract_geoid
    WHERE tg.centroid_lat IS NOT NULL
"""


def _to_feature_collection(rows: list) -> dict:
    features = []
    for row in rows:
        properties = dict(row)
        latitude = properties.pop("latitude")
        longitude = properties.pop("longitude")
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _export(query: str, filename: str) -> int:
    with get_connection() as conn:
        rows = conn.execute(query).fetchall()

    feature_collection = _to_feature_collection(rows)
    out_path = settings.WEB_DATA_DIR / filename
    out_path.write_text(json.dumps(feature_collection))
    logger.info("Wrote %d features to %s", len(feature_collection["features"]), out_path)
    return len(feature_collection["features"])


def export_food_stores() -> int:
    return _export(FOOD_STORE_QUERY, "food_stores.geojson")


def export_housing_properties() -> int:
    return _export(HOUSING_QUERY, "housing_properties.geojson")


def export_tracts() -> int:
    return _export(TRACT_QUERY, "tracts.geojson")


def run() -> dict[str, int]:
    return {
        "food_stores": export_food_stores(),
        "housing_properties": export_housing_properties(),
        "tracts": export_tracts(),
    }


if __name__ == "__main__":
    run()
