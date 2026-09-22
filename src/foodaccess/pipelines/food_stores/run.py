"""Orchestrates every food-store source: fetch -> transform -> store, per source."""
from __future__ import annotations

import logging

from foodaccess.pipelines.food_stores import dedupe, osm_stores, snap_retailers
from foodaccess.storage.database import init_db

logger = logging.getLogger(__name__)

SOURCES = {
    "usda_snap": snap_retailers.run,
    "osm": osm_stores.run,
}


def run_all() -> dict[str, int]:
    init_db()
    results: dict[str, int] = {}
    for name, run_source in SOURCES.items():
        try:
            results[name] = run_source()
        except Exception:
            logger.exception("Food-store source '%s' failed", name)
            results[name] = 0

    # Runs last, after both sources are loaded — see dedupe.py for the matching rule.
    try:
        results["dedupe"] = dedupe.run()
    except Exception:
        logger.exception("Food-store deduplication failed")
        results["dedupe"] = 0

    return results


if __name__ == "__main__":
    from foodaccess.common.logging_config import configure_logging

    configure_logging()
    logger.info("Food store pipeline results: %s", run_all())
