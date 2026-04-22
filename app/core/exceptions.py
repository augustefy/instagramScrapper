"""
Exceptions dediees a l'architecture API / scraper / orchestration.
"""


# ── Base commune des erreurs API. ──
class ApiError(Exception):
    """Erreur de base pour les appels API."""
    pass


# ── API joignable impossible ou reponse indisponible. ──
class ApiUnavailableError(ApiError):
    """L'API est indisponible (timeout, erreur reseau, etc.)."""
    pass


# ── Permissions ou jeton insuffisants. ──
class ApiPermissionError(ApiError):
    """Permissions insuffisantes ou token invalide."""
    pass


class ProtectedProfileError(ApiPermissionError):
    """Le profil cible existe mais n'est pas publiquement accessible."""
    pass


# ── Protection contre le throttling externe. ──
class ApiRateLimitError(ApiError):
    """Rate limit atteint sur l'API."""
    pass


# ── URL non compatible avec la plateforme cible. ──
class InvalidUrlError(Exception):
    """URL invalide ou incompatible avec la plateforme cible."""
    pass


# ── Limite de posts invalide. ──
class InvalidLimitError(ValueError):
    """Le nombre de posts demande est invalide."""
    pass


# ── Profil absent cote plateforme. ──
class UserNotFoundError(ApiError):
    """Le profil cible n'existe pas."""
    pass


# ── Reponse vide ou trop pauvre pour etre exploitee. ──
class EmptyResponseError(ApiError):
    """La reponse de l'API est vide ou incomplete."""
    pass


# ── Reponse recue mais structure inattendue. ──
class InvalidResponseError(ApiError):
    """La reponse de l'API n'est pas exploitable."""
    pass


# ── Erreur de scraping non recuperable. ──
class ScraperError(Exception):
    """Erreur lors du scraping."""
    pass


# ── Plateforme non prise en charge par le registre. ──
class UnsupportedPlatformError(Exception):
    """Plateforme non supportee."""
    pass
