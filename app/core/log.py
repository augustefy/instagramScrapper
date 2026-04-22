from __future__ import annotations

import json
import logging


class JSONFormatter(logging.Formatter):
    """Formatter qui produit du JSON pour chaque log."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

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

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(
    name: str,
    level: int = logging.INFO,
    json_mode: bool = False,
) -> logging.Logger:
    """Configure et retourne un logger applicatif."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        for handler in logger.handlers:
            handler.setLevel(level)
        return logger

    handler = logging.StreamHandler()
    handler.setLevel(level)

    if json_mode:
        formatter: logging.Formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%H:%M:%S",
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def get_logger(name: str, debug: bool = False, json_mode: bool = False) -> logging.Logger:
    level = logging.DEBUG if debug else logging.INFO
    return setup_logging(name, level=level, json_mode=json_mode)
