"""Orchestrates every housing source."""
from __future__ import annotations

import logging

from foodaccess.pipelines.housing import (
    collin_cad,
    dallas_cad,
    dedupe,
    denton_cad,
    hud_lihtc,
    hud_resource_locator,
    tarrant_cad,
    tdhca_htc,
)
from foodaccess.storage.database import init_db

logger = logging.getLogger(__name__)

SOURCES = {
    "hud_resource_locator": hud_resource_locator.run,
    "hud_lihtc": hud_lihtc.run,
    "tdhca_htc": tdhca_htc.run,
    "dallas_cad": dallas_cad.run,
    "tarrant_cad": tarrant_cad.run,
    "collin_cad": collin_cad.run,
    "denton_cad": denton_cad.run,
}


def run_all() -> dict[str, int]:
    init_db()
    results: dict[str, int] = {}
    for name, run_source in SOURCES.items():
        try:
            results[name] = run_source()
        except Exception:
            logger.exception("Housing source '%s' failed", name)
            results[name] = 0

    # Runs last, after every source is loaded — see dedupe.py for the matching rule.
    try:
        results["dedupe"] = dedupe.run()
    except Exception:
        logger.exception("Housing deduplication failed")
        results["dedupe"] = 0

    return results


if __name__ == "__main__":
    from foodaccess.common.logging_config import configure_logging

    configure_logging()
    logger.info("Housing pipeline results: %s", run_all())
