from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any, TextIO


_MAX_LOG_VALUE_LENGTH = 500
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "bearer",
    "cookie",
    "password",
    "secret",
    "session",
    "token",
)
_REDACTION_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)((?:access|refresh|id)[_-]?token=)[^&\s]+"),
    re.compile(r"(?i)((?:api[_-]?key|client[_-]?secret|password)=)[^&\s]+"),
)


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _REDACTION_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    if len(redacted) > _MAX_LOG_VALUE_LENGTH:
        return f"{redacted[:_MAX_LOG_VALUE_LENGTH]}...[truncated]"
    return redacted


def _sanitize_log_value(value: Any, key: str | None = None, depth: int = 0) -> Any:
    if key and any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"

    if isinstance(value, str):
        return _redact_text(value)

    if depth >= 3:
        return repr(value)

    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_log_value(item_value, str(item_key), depth + 1)
            for item_key, item_value in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        sanitized = [_sanitize_log_value(item, depth=depth + 1) for item in value]
        return sanitized[:20] + ["...[truncated]"] if len(sanitized) > 20 else sanitized

    return value


class SensitiveDataFilter(logging.Filter):
    """Reduit le risque de laisser fuiter tokens, cookies ou payloads volumineux."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _sanitize_log_value(record.msg)
        if isinstance(record.args, dict):
            record.args = _sanitize_log_value(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(_sanitize_log_value(arg) for arg in record.args)
        return True


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
                log_data[key] = _sanitize_log_value(value, key)

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


def _build_formatter(json_mode: bool) -> logging.Formatter:
    if json_mode:
        return JSONFormatter()

    return logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )


def setup_logging(
    name: str,
    level: int = logging.INFO,
    json_mode: bool = False,
) -> logging.Logger:
    """Configure et retourne un logger applicatif."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    formatter = _build_formatter(json_mode)

    if logger.handlers:
        for handler in logger.handlers:
            handler.setLevel(level)
            handler.setFormatter(formatter)
            if not any(isinstance(f, SensitiveDataFilter) for f in handler.filters):
                handler.addFilter(SensitiveDataFilter())
        return logger

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(formatter)
    handler.addFilter(SensitiveDataFilter())
    logger.addHandler(handler)
    return logger


def get_logger(name: str, debug: bool = False, json_mode: bool = False) -> logging.Logger:
    level = logging.DEBUG if debug else logging.INFO
    return setup_logging(name, level=level, json_mode=json_mode)


def emit_console(
    message: str = "",
    *,
    end: str = "\n",
    stream: TextIO | None = None,
    flush: bool = False,
) -> None:
    """Ecrit une sortie utilisateur volontaire sans passer par print()."""
    target = stream or sys.stdout
    target.write(f"{message}{end}")
    if flush:
        target.flush()
