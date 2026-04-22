"""
Provider Reddit base sur l'API JSON publique.
"""

from app.core.health import PlatformHealth
from app.core.exceptions import ApiError, ScraperError
from app.core.log import get_logger
from app.core.models import FetchPostsResult
from app.platforms.base.provider import DegradationStrategy, PlatformProvider
from app.platforms.reddit.api.service import RedditApiService

logger = get_logger(__name__)


# ── Provider Reddit sans fallback navigateur. ──
class RedditProvider(PlatformProvider):
    def __init__(self, headless: bool = True, debug: bool = False) -> None:
        self._debug = debug
        self._service = RedditApiService(debug=debug)

    @property
    def platform_name(self) -> str:
        return "reddit"

    @property
    def degradation_strategy(self) -> DegradationStrategy:
        return DegradationStrategy(
            primary_source="api",
            note="API JSON publique uniquement; aucun fallback navigateur n'est disponible.",
        )

    def health_check(self) -> PlatformHealth:
        # Reddit repose uniquement sur l endpoint JSON public.
        return PlatformHealth(
            platform=self.platform_name,
            sources=[self._service.health_check()],
        )

    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        # Important: aucun fallback navigateur prevu pour Reddit.
        logger.info(f"[Reddit] Recuperation du profil @{username} via API JSON (limit={limit})")

        try:
            result = self._service.fetch_profile_posts(username, limit)
        except ApiError as exc:
            # Requalifier les erreurs API pour conserver un contrat provider unique.
            raise ScraperError(f"Echec API Reddit pour @{username}: {exc}") from exc

        logger.info(f"[Reddit] {len(result.posts)} post(s) recuperes")
        return result

    def close(self) -> None:
        # Fermer la session HTTP partagee par le service.
        self._service.close()
