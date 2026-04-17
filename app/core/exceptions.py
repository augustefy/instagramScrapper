"""
Exceptions dediees a l'architecture API / scraper / orchestration.
"""


class ApiError(Exception):
    """Erreur de base pour les appels API."""
    pass


class ApiUnavailableError(ApiError):
    """L'API est indisponible (timeout, erreur reseau, etc.)."""
    pass


class ApiPermissionError(ApiError):
    """Permissions insuffisantes ou token invalide."""
    pass


class ApiRateLimitError(ApiError):
    """Rate limit atteint sur l'API."""
    pass


class ScraperError(Exception):
    """Erreur lors du scraping."""
    pass


class UnsupportedPlatformError(Exception):
    """Plateforme non supportee."""
    pass
