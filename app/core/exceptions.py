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


class InvalidUrlError(Exception):
    """URL invalide ou incompatible avec la plateforme cible."""
    pass


class InvalidLimitError(ValueError):
    """Le nombre de posts demande est invalide."""
    pass


class UserNotFoundError(ApiError):
    """Le profil cible n'existe pas."""
    pass


class EmptyResponseError(ApiError):
    """La reponse de l'API est vide ou incomplete."""
    pass


class InvalidResponseError(ApiError):
    """La reponse de l'API n'est pas exploitable."""
    pass


class ScraperError(Exception):
    """Erreur lors du scraping."""
    pass


class UnsupportedPlatformError(Exception):
    """Plateforme non supportee."""
    pass
