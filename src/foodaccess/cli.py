"""
Command-line entry point for running one or more data pipelines.

Usage:
    python -m foodaccess.cli food_stores
    python -m foodaccess.cli population
    python -m foodaccess.cli housing
    python -m foodaccess.cli geocode
    python -m foodaccess.cli tract_lookup
    python -m foodaccess.cli export
    python -m foodaccess.cli all
"""
from __future__ import annotations

import argparse
import logging

from foodaccess.common.logging_config import configure_logging
from foodaccess.export import geojson as export_geojson
from foodaccess.geocoding import census_geocoder, tract_lookup
from foodaccess.pipelines.food_stores import run as food_stores_run
from foodaccess.pipelines.housing import run as housing_run
from foodaccess.pipelines.population import run as population_run
from foodaccess.storage.database import init_db

logger = logging.getLogger(__name__)

# Order matters for "all": geocode reads addresses that the housing
# pipelines just wrote, so it must run after them; tract_lookup needs the
# coordinates geocode just filled in, so it runs after that; export reads
# whatever's on hand last, so it runs after both.
#
# tract_lookup is NOT included in "all" — its first run is a real,
# multi-hour backfill (one Census API request per housing row with no
# tract yet, no bulk endpoint exists for coordinate lookups). Run it
# deliberately, e.g. in the background, rather than have it silently
# make every future "all" run take hours. Once the backfill is done,
# reruns are cheap (only new rows lacking a tract get looked up).
DOMAINS = {
    "food_stores": food_stores_run.run_all,
    "population": population_run.run_all,
    "housing": housing_run.run_all,
    "geocode": census_geocoder.run,
    "tract_lookup": tract_lookup.run,
    "export": export_geojson.run,
}

BACKGROUND_ONLY = {"tract_lookup"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DFW food access data pipelines")
    parser.add_argument("domain", choices=[*DOMAINS.keys(), "all"], help="Which pipeline domain to run")
    args = parser.parse_args()

    configure_logging()
    init_db()

    if args.domain == "all":
        domains_to_run = [d for d in DOMAINS if d not in BACKGROUND_ONLY]
    else:
        domains_to_run = [args.domain]
    for domain in domains_to_run:
        logger.info("=== Running %s pipelines ===", domain)
        results = DOMAINS[domain]()
        logger.info("=== %s results: %s ===", domain, results)


if __name__ == "__main__":
    main()
