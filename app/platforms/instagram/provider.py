"""
Provider Instagram : orchestrateur qui tente l'API officielle d'abord,
puis bascule automatiquement sur le scraper en fallback.
"""

from app.core.exceptions import ApiError, ApiUnavailableError, ApiPermissionError, ScraperError
from app.core.models import FetchPostsResult
from app.platforms.base.provider import PlatformProvider
from app.platforms.instagram.api.service import InstagramApiService
from app.platforms.instagram.scraper.service import InstagramScraperService
from logging_setup import setup_logging

logger = setup_logging(__name__)


class InstagramProvider(PlatformProvider):
    """Provider Instagram avec fallback automatique API -> scraper."""

    def __init__(self, headless: bool = True, debug: bool = False):
        self._headless = headless
        self._debug = debug
        self._api_service = InstagramApiService()
        self._scraper_service = InstagramScraperService(headless=headless)

    @property
    def platform_name(self) -> str:
        return "instagram"

    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        """Recupere les posts : API d'abord, scraper en fallback.

        Le fallback est declenche si :
        - L'API n'est pas configuree
        - Le token est invalide ou expire
        - Le compte cible n'est pas business/creator
        - L'API est indisponible (timeout, erreur reseau)
        - Le rate limit est atteint
        """
        # --- Tentative API ---
        if self._api_service.is_available:
            try:
                logger.info(f"[Instagram] Tentative via API officielle pour @{username}")
                result = self._api_service.fetch_posts(username, limit)
                logger.info(
                    f"[Instagram] API OK : {len(result.posts)} post(s) recuperes",
                    extra={"source": "api", "count": len(result.posts)},
                )
                return result

            except ApiPermissionError as e:
                logger.warning(
                    f"[Instagram] API permission refusee pour @{username}: {e}",
                    extra={"error_type": "permission", "reason": str(e)},
                )
                logger.info("[Instagram] Bascule sur le scraper (fallback)")

            except ApiUnavailableError as e:
                logger.warning(
                    f"[Instagram] API indisponible: {e}",
                    extra={"error_type": "unavailable", "reason": str(e)},
                )
                logger.info("[Instagram] Bascule sur le scraper (fallback)")

            except ApiError as e:
                logger.warning(
                    f"[Instagram] Erreur API inattendue: {e}",
                    extra={"error_type": "api_error", "reason": str(e)},
                )
                logger.info("[Instagram] Bascule sur le scraper (fallback)")
        else:
            logger.info(
                "[Instagram] API non configuree (USER_LONG_TOKEN / IG_USER_ID manquants), "
                "utilisation directe du scraper"
            )

        # --- Fallback scraper ---
        try:
            logger.info(f"[Instagram] Scraping de @{username}")
            result = self._scraper_service.fetch_posts(username, limit)
            logger.info(
                f"[Instagram] Scraper OK : {len(result.posts)} post(s) recuperes",
                extra={"source": "scraper", "count": len(result.posts)},
            )
            return result

        except ScraperError as e:
            logger.error(f"[Instagram] Echec du scraper: {e}")
            raise
        except Exception as e:
            logger.error(f"[Instagram] Erreur inattendue du scraper: {e}")
            raise ScraperError(f"Echec complet pour @{username}: {e}") from e

    def close(self):
        self._scraper_service.close()
