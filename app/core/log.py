"""
Setup logging pour l'application.
Reutilise logging_setup existant, expose un helper simple.
"""

import logging

from logging_setup import setup_logging


def get_logger(name: str, debug: bool = False) -> logging.Logger:
    level = logging.DEBUG if debug else logging.INFO
    return setup_logging(name, level=level)
