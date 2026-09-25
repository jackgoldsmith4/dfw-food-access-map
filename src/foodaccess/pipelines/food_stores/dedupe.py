"""
Cross-source deduplication for food_stores.

The same physical store can legitimately appear in both usda_snap and osm
— e.g. a named chain like Whole Foods, geocoded slightly differently by
each source. This runs as the last step of pipelines/food_stores/run.py,
after both sources have loaded.

A match is an OSM row within some distance of a USDA SNAP row whose
normalized names overlap. Every OSM row that reaches this pipeline
already carries a real shop= tag (see osm_stores.py's Overpass query), so
its store_type is never the "other" catch-all — on a match, OSM's
name/store_type/raw_category are treated as the more precise
classification (real case found in production: USDA's own data classifies
"Whole Foods Market 10505" as "Super Store" -> mass_merchandiser, while
OSM correctly tags it shop=supermarket -> grocery). The USDA row is
updated in place with OSM's classification, keeping USDA's
snap_authorized flag and county_fips (fields OSM rows don't have). The
OSM row is then deleted as the duplicate.

The match distance is per store format, not one global constant — verified
against real data that a single threshold is unsafe either way. Grocery/
mass-merchandiser stores are geographically sparse (each serves a large
trade area), so a generous radius is safe and necessary: a real Kroger at
a shopping-center address was geocoded 257m apart between the two
sources, well past a tight threshold. Convenience stores are the opposite
— dense enough (many per square mile) that the same generous radius would
risk merging two genuinely different nearby 7-Elevens into one; confirmed
in a real pull that opening up the convenience radius surfaces exactly
that pattern (a "7-Eleven" 900m from another distinct "7-Eleven"), so it
stays tight.
"""
from __future__ import annotations

import logging

from foodaccess.common.geo import grid_key, haversine_meters, neighboring_keys, normalize_name
from foodaccess.storage.database import get_connection

logger = logging.getLogger(__name__)

MATCH_DISTANCE_METERS = {
    "convenience": 150,  # dense format — a wide radius risks merging two distinct nearby stores
    "grocery": 500,      # sparse format — shopping-center address geocoding can drift a few hundred meters
}
DEFAULT_MATCH_DISTANCE_METERS = 250


def _find_matches(usda_rows: list, osm_rows: list) -> tuple[list[tuple[str, dict]], set[str]]:
    usda_by_cell: dict[tuple, list] = {}
    for row in usda_rows:
        usda_by_cell.setdefault(grid_key(row["latitude"], row["longitude"]), []).append(row)

    merges: list[tuple[str, dict]] = []
    matched_osm_ids: set[str] = set()

    for osm_row in osm_rows:
        osm_name = normalize_name(osm_row["name"])
        if not osm_name:
            continue

        candidates = [
            u for key in neighboring_keys(osm_row["latitude"], osm_row["longitude"]) for u in usda_by_cell.get(key, [])
        ]
        for usda_row in candidates:
            usda_name = normalize_name(usda_row["name"])
            if not usda_name or (osm_name not in usda_name and usda_name not in osm_name):
                continue
            distance = haversine_meters(
                osm_row["latitude"], osm_row["longitude"], usda_row["latitude"], usda_row["longitude"]
            )
            threshold = MATCH_DISTANCE_METERS.get(osm_row["store_type"], DEFAULT_MATCH_DISTANCE_METERS)
            if distance <= threshold:
                merges.append((usda_row["source_id"], dict(osm_row)))
                matched_osm_ids.add(osm_row["source_id"])
                break  # one match is enough — don't merge the same OSM row twice

    return merges, matched_osm_ids


def run() -> int:
    with get_connection() as conn:
        usda_rows = conn.execute(
            "SELECT source_id, name, latitude, longitude FROM food_stores "
            "WHERE source='usda_snap' AND is_manually_edited = 0"
        ).fetchall()
        osm_rows = conn.execute(
            "SELECT source_id, name, store_type, raw_category, latitude, longitude FROM food_stores "
            "WHERE source='osm' AND is_manually_edited = 0"
        ).fetchall()

    merges, matched_osm_ids = _find_matches(usda_rows, osm_rows)
    if not merges:
        logger.info("Deduplication: no cross-source duplicates found")
        return 0

    with get_connection() as conn:
        conn.executemany(
            """
            UPDATE food_stores SET name = :name, store_type = :store_type, raw_category = :raw_category
            WHERE source = 'usda_snap' AND source_id = :usda_id
            """,
            [
                {
                    "usda_id": usda_id,
                    "name": osm_row["name"],
                    "store_type": osm_row["store_type"],
                    "raw_category": osm_row["raw_category"],
                }
                for usda_id, osm_row in merges
            ],
        )
        conn.executemany(
            "DELETE FROM food_stores WHERE source='osm' AND source_id = :osm_id",
            [{"osm_id": osm_id} for osm_id in matched_osm_ids],
        )

    logger.info(
        "Deduplication: merged %d cross-source duplicate stores (kept the USDA row, applied OSM's classification)",
        len(merges),
    )
    return len(merges)


if __name__ == "__main__":
    from foodaccess.common.logging_config import configure_logging

    configure_logging()
    run()
