"""
Logging structuré pour le scraper Instagram.
Produit des logs en JSON pour faciliter l'analyse en production.
"""

import json
import logging
from typing import Any, Optional


class JSONFormatter(logging.Formatter):
    """Formatter qui produit du JSON pour chaque log."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Ajoute les extras si présents (fields passés via logger.info(..., extra={...}))
        # Les extras sont des attributs du LogRecord que ne sont pas standards
        standard_fields = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "thread",
            "threadName",
            "exc_info",
            "exc_text",
            "stack_info",
            "asctime",
        }
        for key, value in record.__dict__.items():
            if key not in standard_fields and not key.startswith("_"):
                log_data[key] = value

        # Ajoute l'exception si présente
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(name: str, level: int = logging.INFO, json_mode: bool = False) -> logging.Logger:
    """Configure le logging pour le scraper.

    Args:
        name: Nom du logger
        level: Niveau de log (DEBUG, INFO, WARNING, ERROR)
        json_mode: Si True, produit du JSON. Sinon, format lisible.

    Returns:
        Logger configuré
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Évite les doublons si appelé plusieurs fois
    if logger.handlers:
        return logger

    handler = logging.StreamHandler()
    handler.setLevel(level)

    if json_mode:
        formatter = JSONFormatter()
    else:
        # Format lisible pour le développement
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%H:%M:%S",
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


