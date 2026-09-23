"""Orchestrates every population/demographic/health source."""
from __future__ import annotations

import logging

from foodaccess.pipelines.population import census_acs, cdc_places, feeding_america, tract_geometry, usda_food_atlas
from foodaccess.storage.database import init_db

logger = logging.getLogger(__name__)

SOURCES = {
    "census_acs": census_acs.run,
    "tract_geometry": tract_geometry.run,
    "cdc_places": cdc_places.run,
    "usda_food_atlas": usda_food_atlas.run,
    "feeding_america": feeding_america.run,
}


def run_all() -> dict[str, int]:
    init_db()
    results: dict[str, int] = {}
    for name, run_source in SOURCES.items():
        try:
            results[name] = run_source()
        except Exception:
            logger.exception("Population source '%s' failed", name)
            results[name] = 0
    return results


if __name__ == "__main__":
    from foodaccess.common.logging_config import configure_logging

    configure_logging()
    logger.info("Population pipeline results: %s", run_all())
