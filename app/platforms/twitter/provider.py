"""
Provider Twitter / X base sur une source brute web/guest.
"""

from app.core.health import PlatformHealth
from app.core.exceptions import ApiError, ScraperError
from app.core.log import get_logger
from app.core.models import FetchPostsResult
from app.platforms.base.provider import DegradationStrategy, PlatformProvider
from app.platforms.twitter.api.service import TwitterApiService
from normalizers.twitter import normalize_post, normalize_profile

logger = get_logger(__name__)


class TwitterProvider(PlatformProvider):
    def __init__(self, headless: bool = True, debug: bool = False) -> None:
        self._debug = debug
        self._service = TwitterApiService(debug=debug)

    @property
    def platform_name(self) -> str:
        return "twitter"

    @property
    def degradation_strategy(self) -> DegradationStrategy:
        return DegradationStrategy(
            primary_source="guest_api",
            note="Source web/guest uniquement; aucun fallback navigateur n'est disponible.",
        )

    def health_check(self) -> PlatformHealth:
        return PlatformHealth(
            platform=self.platform_name,
            sources=[self._service.health_check()],
        )

    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        logger.info(f"[Twitter/X] Recuperation du profil @{username} via source web (limit={limit})")

        try:
            payload = self._service.fetch_profile_posts_payload(username, limit)
        except ApiError as exc:
            raise ScraperError(f"Echec Twitter/X pour @{username}: {exc}") from exc

        profile = normalize_profile(username, payload["profile"], include_raw=self._debug)
        posts = [
            normalize_post(profile.username, tweet, include_raw=self._debug)
            for tweet in payload["posts"]
        ]

        logger.info(f"[Twitter/X] {len(posts)} post(s) recuperes")
        return FetchPostsResult(
            posts=posts,
            source=str(payload.get("source") or "guest_api"),
            platform="twitter",
            username=profile.username,
            profile=profile,
        )

    def close(self) -> None:
        self._service.close()
