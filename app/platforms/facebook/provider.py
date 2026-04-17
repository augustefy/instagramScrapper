"""
Provider Facebook : API Graph uniquement (pas de scraper fallback).
"""

from app.core.config import load_facebook_api_config
from app.core.exceptions import ApiError, ScraperError
from app.core.models import FetchPostsResult
from app.platforms.base.provider import PlatformProvider
from app.platforms.facebook.api.service import FacebookApiService
from logging_setup import setup_logging

logger = setup_logging(__name__)


class FacebookProvider(PlatformProvider):
    """Provider Facebook (API Graph)."""

    def __init__(self, headless: bool = True, debug: bool = False):
        self._debug = debug
        config = load_facebook_api_config()
        self._api_service = FacebookApiService(config)
        self._page_id = config.page_id

    @property
    def platform_name(self) -> str:
        return "facebook"

    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        """Recupere les posts d'une page Facebook via l'API.

        Le page_id utilise est celui configure dans .env (FB_PAGE_ID).
        Le username extrait de l'URL sert de fallback si FB_PAGE_ID est vide.
        """
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
            logger.info(f"[Facebook] Tentative via API Graph pour page {page_id}")
            result = self._api_service.fetch_posts(page_id, limit)
            logger.info(
                f"[Facebook] API OK : {len(result.posts)} post(s) recuperes",
                extra={"source": "api", "count": len(result.posts)},
            )
            return result

        except ApiError as e:
            logger.error(f"[Facebook] Echec API : {e}")
            logger.error("[Facebook] Pas de scraper fallback disponible pour Facebook")
            raise ScraperError(f"Echec API Facebook pour {page_id}: {e}") from e
