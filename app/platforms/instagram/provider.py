"""
Provider Instagram : orchestrateur qui tente l'API officielle d'abord,
puis bascule automatiquement sur le scraper en fallback.
"""

from app.core.health import PlatformHealth
from app.core.exceptions import ApiError, ApiUnavailableError, ApiPermissionError, ScraperError
from app.core.log import get_logger
from app.core.models import FetchPostsResult
from app.platforms.base.provider import DegradationStrategy, PlatformProvider
from app.platforms.instagram.api.service import InstagramApiService
from app.platforms.instagram.scraper.service import InstagramScraperService

logger = get_logger(__name__)


# ── Provider hybride: API d abord, scraper en secours. ──
class InstagramProvider(PlatformProvider):
    """Provider Instagram avec fallback automatique API -> scraper."""

    def __init__(self, headless: bool = True, debug: bool = False) -> None:
        self._headless = headless
        self._debug = debug
        self._api_service = InstagramApiService()
        self._scraper_service = InstagramScraperService(headless=headless)

    @property
    def platform_name(self) -> str:
        return "instagram"

    @property
    def degradation_strategy(self) -> DegradationStrategy:
        return DegradationStrategy(
            primary_source="api",
            fallback_source="scraper",
            note="API Graph officielle puis fallback Playwright si l'API est absente ou refusee.",
        )

    def health_check(self) -> PlatformHealth:
        # Confronter la voie officielle et le fallback dans le meme rapport.
        return PlatformHealth(
            platform=self.platform_name,
            sources=[
                self._api_service.health_check(),
                self._scraper_service.health_check(),
            ],
        )

    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        """Recupere les posts : API d'abord, scraper en fallback.

        Le fallback est declenche si :
        - L'API n'est pas configuree
        - Le token est invalide ou expire
        - Le compte cible n'est pas business/creator
        - L'API est indisponible (timeout, erreur reseau)
        - Le rate limit est atteint
        """
        # 1) Tenter la voie officielle tant qu elle est disponible.
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
                # Important: compte non compatible Graph ou token invalide.
                logger.warning(
                    f"[Instagram] API permission refusee pour @{username}: {e}",
                    extra={"error_type": "permission", "reason": str(e)},
                )
                logger.info("[Instagram] Bascule sur le scraper (fallback)")

            except ApiUnavailableError as e:
                # Important: indisponibilite reseau ou serveur, fallback autorise.
                logger.warning(
                    f"[Instagram] API indisponible: {e}",
                    extra={"error_type": "unavailable", "reason": str(e)},
                )
                logger.info("[Instagram] Bascule sur le scraper (fallback)")

            except ApiError as e:
                # Garde-fou sur les autres erreurs API non classees.
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

        # 2) Basculer sur le scraper si l API ne suffit pas.
        try:
            logger.info(f"[Instagram] Scraping de @{username}")
            result = self._scraper_service.fetch_posts(username, limit)
            logger.info(
                f"[Instagram] Scraper OK : {len(result.posts)} post(s) recuperes",
                extra={"source": "scraper", "count": len(result.posts)},
            )
            return result

        except ScraperError as e:
            # Ne pas masquer une erreur deja qualifiee par la couche scraper.
            logger.error(f"[Instagram] Echec du scraper: {e}")
            raise
        except Exception as e:
            # Requalifier toute erreur brute pour homogeniser les appels amont.
            logger.exception(f"[Instagram] Erreur inattendue du scraper: {e}")
            raise ScraperError(f"Echec complet pour @{username}: {e}") from e

    def close(self) -> None:
        # Seule la branche scraper maintient des ressources a fermer.
        self._scraper_service.close()
