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
HOUSING_COLUMNS = [
    "source", "source_id", "name", "property_type", "address", "city",
    "total_units", "is_senior_housing", "is_subsidized", "latitude", "longitude",
]


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


def _export(table: str, columns: list[str], filename: str) -> int:
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE latitude IS NOT NULL AND is_deleted = 0"
        ).fetchall()

    feature_collection = _to_feature_collection(rows)
    out_path = settings.WEB_DATA_DIR / filename
    out_path.write_text(json.dumps(feature_collection))
    logger.info("Wrote %d features to %s", len(feature_collection["features"]), out_path)
    return len(feature_collection["features"])


def export_food_stores() -> int:
    return _export("food_stores", FOOD_STORE_COLUMNS, "food_stores.geojson")


def export_housing_properties() -> int:
    return _export("housing_properties", HOUSING_COLUMNS, "housing_properties.geojson")


def run() -> dict[str, int]:
    return {
        "food_stores": export_food_stores(),
        "housing_properties": export_housing_properties(),
    }


if __name__ == "__main__":
    run()
