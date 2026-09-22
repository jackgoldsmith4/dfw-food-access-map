"""
Command-line entry point for running one or more data pipelines.

Usage:
    python -m foodaccess.cli food_stores
    python -m foodaccess.cli population
    python -m foodaccess.cli housing
    python -m foodaccess.cli geocode
    python -m foodaccess.cli export
    python -m foodaccess.cli all
"""
from __future__ import annotations

import argparse
import logging

from foodaccess.common.logging_config import configure_logging
from foodaccess.export import geojson as export_geojson
from foodaccess.geocoding import census_geocoder
from foodaccess.pipelines.food_stores import run as food_stores_run
from foodaccess.pipelines.housing import run as housing_run
from foodaccess.pipelines.population import run as population_run
from foodaccess.storage.database import init_db

logger = logging.getLogger(__name__)

# Order matters for "all": geocode reads addresses that the housing
# pipelines just wrote, so it must run after them; export reads whatever
# coordinates are on hand last, so it runs after geocode.
DOMAINS = {
    "food_stores": food_stores_run.run_all,
    "population": population_run.run_all,
    "housing": housing_run.run_all,
    "geocode": census_geocoder.run,
    "export": export_geojson.run,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DFW food access data pipelines")
    parser.add_argument("domain", choices=[*DOMAINS.keys(), "all"], help="Which pipeline domain to run")
    args = parser.parse_args()

    configure_logging()
    init_db()

    domains_to_run = DOMAINS.keys() if args.domain == "all" else [args.domain]
    for domain in domains_to_run:
        logger.info("=== Running %s pipelines ===", domain)
        results = DOMAINS[domain]()
        logger.info("=== %s results: %s ===", domain, results)


if __name__ == "__main__":
    main()
