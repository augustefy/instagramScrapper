"""
Compatibilite legacy pour les anciens imports.

Le point d'entree canonique est maintenant `app.core.log`.
"""

from app.core.log import JSONFormatter, get_logger, setup_logging

__all__ = ["JSONFormatter", "get_logger", "setup_logging"]
