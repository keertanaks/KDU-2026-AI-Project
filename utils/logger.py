"""Centralised logging setup. Import get_logger in every module."""
from __future__ import annotations

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """Return a named logger wired to stdout with a consistent format."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger
