"""
Service API Instagram : recupere les posts via l'API Graph et les convertit en SocialPost.
"""

from app.core.health import (
    HEALTHY,
    NOT_CONFIGURED,
    UNHEALTHY,
    DataSourceHealth,
)
from app.core.config import InstagramApiConfig, load_instagram_api_config
from app.core.exceptions import ApiError, ApiUnavailableError
from app.core.log import get_logger
from app.core.models import SocialPost, SocialProfile, FetchPostsResult

logger = get_logger(__name__)


# ── Service de collecte Instagram via Graph API. ──
class InstagramApiService:
    """Recuperation des posts Instagram via l'API officielle Graph."""

    def __init__(self, config: InstagramApiConfig | None = None):
        self._config = config or load_instagram_api_config()
        self._client = None

    @property
    def is_available(self) -> bool:
        return self._config.is_configured

    def _get_client(self):
        if self._client is None:
            from app.platforms.instagram.api.client import InstagramGraphClient

            self._client = InstagramGraphClient(self._config)
        return self._client

    def health_check(self) -> DataSourceHealth:
        env_flags = {
            "USER_LONG_TOKEN": bool(self._config.user_long_token),
            "IG_USER_ID": bool(self._config.ig_user_id),
            "APP_ID": bool(self._config.app_id),
            "ID_PAGE": bool(self._config.id_page),
        }
        missing_env = [
            name for name in ("USER_LONG_TOKEN", "IG_USER_ID") if not env_flags[name]
        ]

        if missing_env:
            return DataSourceHealth(
                source="api",
                status=NOT_CONFIGURED,
                message="API Instagram non configuree.",
                details={
                    "missing_env": missing_env,
                    "configured_env": env_flags,
                    "graph_api_base": self._config.graph_api_base,
                },
            )

        try:
            payload = self._get_client().probe_account()
            return DataSourceHealth(
                source="api",
                status=HEALTHY,
                message="API Instagram joignable et authentifiee.",
                details={
                    "configured_env": env_flags,
                    "graph_api_base": self._config.graph_api_base,
                    "ig_user_id": self._config.ig_user_id,
                    "username": payload.get("username", ""),
                },
            )
        except (ApiError, TypeError, ValueError) as exc:
            return DataSourceHealth(
                source="api",
                status=UNHEALTHY,
                message=f"API Instagram indisponible: {exc}",
                details={
                    "configured_env": env_flags,
                    "graph_api_base": self._config.graph_api_base,
                    "ig_user_id": self._config.ig_user_id,
                },
            )

    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        """Recupere les posts via business_discovery.

        Args:
            username: Username Instagram cible (sans @)
            limit: Nombre de posts souhaites

        Returns:
            FetchPostsResult avec source="api"

        Raises:
            ApiUnavailableError, ApiPermissionError, ApiRateLimitError
        """
        if not self.is_available:
            raise ApiUnavailableError(
                "API Instagram non configuree (variables USER_LONG_TOKEN / IG_USER_ID manquantes)"
            )

        logger.info(f"Tentative API Instagram pour @{username} (limit={limit})")
        raw = self._get_client().get_business_discovery(username, media_limit=limit)

        discovery = raw.get("business_discovery", {})
        if not discovery:
            raise ApiUnavailableError("Reponse API vide (pas de business_discovery)")

        profile = self._parse_profile(discovery, username)
        posts = self._parse_posts(discovery, profile.followers_count)

        logger.info(
            f"API Instagram: {len(posts)} post(s) recuperes pour @{username}",
            extra={"followers": profile.followers_count},
        )

        return FetchPostsResult(
            posts=posts[:limit],
            source="api",
            platform="instagram",
            username=username,
            profile=profile,
        )

    def _parse_profile(self, discovery: dict, username: str) -> SocialProfile:
        return SocialProfile(
            username=discovery.get("username", username),
            platform="instagram",
            followers_count=discovery.get("followers_count", 0),
            following_count=discovery.get("follows_count", 0),
            posts_count=discovery.get("media_count", 0),
            biography=discovery.get("biography", ""),
            full_name=discovery.get("name", ""),
        )

    def _parse_posts(self, discovery: dict, followers_count: int) -> list[SocialPost]:
        media_data = discovery.get("media", {}).get("data", [])
        posts = []
        for item in media_data:
            post = self._item_to_post(item, followers_count)
            if post:
                posts.append(post)
        return posts

    def _item_to_post(self, item: dict, followers_count: int) -> SocialPost | None:
        try:
            media_type_raw = (item.get("media_type") or "").upper()
            media_type_map = {
                "IMAGE": "image",
                "VIDEO": "video",
                "CAROUSEL_ALBUM": "carousel",
            }
            media_type = media_type_map.get(media_type_raw, media_type_raw.lower())

            # L'API retourne le permalink directement
            url = item.get("permalink", "")

            # Timestamp ISO 8601
            timestamp = item.get("timestamp", "")

            return SocialPost(
                platform="instagram",
                url=url,
                caption=item.get("caption", ""),
                timestamp=timestamp,
                likes_count=item.get("like_count", 0),
                comments_count=item.get("comments_count", 0),
                views_count=0,
                media_type=media_type,
                user_followers=followers_count,
            )
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(f"Erreur conversion post API", extra={"error": str(e)})
            return None
