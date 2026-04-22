"""
Provider Facebook : API Graph uniquement (pas de scraper fallback).
"""

from app.core.health import PlatformHealth
from app.core.config import load_facebook_api_config
from app.core.exceptions import ApiError, ScraperError
from app.core.log import get_logger
from app.core.models import FetchPostsResult
from app.platforms.base.provider import DegradationStrategy, PlatformProvider
from app.platforms.facebook.api.service import FacebookApiService

logger = get_logger(__name__)


# ── Provider Facebook base uniquement sur l API. ──
class FacebookProvider(PlatformProvider):
    """Provider Facebook (API Graph)."""

    def __init__(self, headless: bool = True, debug: bool = False) -> None:
        self._debug = debug
        config = load_facebook_api_config()
        self._api_service = FacebookApiService(config)
        self._page_id = config.page_id

    @property
    def platform_name(self) -> str:
        return "facebook"

    @property
    def degradation_strategy(self) -> DegradationStrategy:
        return DegradationStrategy(
            primary_source="api",
            note="API Graph uniquement; aucun scraper fallback n'est disponible.",
        )

    def health_check(self) -> PlatformHealth:
        # Facebook n expose qu une source: l API Graph.
        return PlatformHealth(
            platform=self.platform_name,
            sources=[self._api_service.health_check()],
        )

    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        """Recupere les posts d'une page Facebook via l'API.

        Le page_id utilise est celui configure dans .env (FB_PAGE_ID).
        Le username extrait de l'URL sert de fallback si FB_PAGE_ID est vide.
        """
        # 1) Preferer le page_id configure pour eviter les ambiguities de slug.
        page_id = self._page_id or username

        if not self._api_service.is_available:
            logger.error(
                "[Facebook] API non configuree. "
                "Definir FB_PAGE_ID et FB_ACCESS_TOKEN dans .env"
            )
            raise ScraperError(
                "Facebook necessite l'API Graph (pas de scraper disponible). "
                "Configurez FB_PAGE_ID et FB_ACCESS_TOKEN dans .env"
            )

        try:
            # 2) Deleguer la collecte a la couche API metier.
            logger.info(f"[Facebook] Tentative via API Graph pour page {page_id}")
            result = self._api_service.fetch_posts(page_id, limit)
            logger.info(
                f"[Facebook] API OK : {len(result.posts)} post(s) recuperes",
                extra={"source": "api", "count": len(result.posts)},
            )
            return result

        except ApiError as e:
            # Important: aucun fallback navigateur disponible pour Facebook.
            logger.error(f"[Facebook] Echec API : {e}")
            logger.error("[Facebook] Pas de scraper fallback disponible pour Facebook")
            raise ScraperError(f"Echec API Facebook pour {page_id}: {e}") from e
