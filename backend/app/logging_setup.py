"""Centralised logging configuration writing to logs/application.log."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import LOG_FILE

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure root logging once (console + rotating file)."""
    global _CONFIGURED
    logger = logging.getLogger("uzkad")
    if _CONFIGURED:
        return logger

    logger.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    logger.propagate = False
    _CONFIGURED = True
    return logger


def get_logger(name: str = "uzkad") -> logging.Logger:
    setup_logging()
    return logging.getLogger(name if name.startswith("uzkad") else f"uzkad.{name}")
