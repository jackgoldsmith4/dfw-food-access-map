"""Shared logging setup so every pipeline logs consistently."""
import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging once per process. Safe to call multiple times."""
    root = logging.getLogger()
    if root.handlers:
        return  # already configured (e.g. by a test runner or re-import)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level)
