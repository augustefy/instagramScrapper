"""
Service API Facebook : recupere les posts via Graph API et les convertit en SocialPost.
"""

from app.core.health import (
    HEALTHY,
    NOT_CONFIGURED,
    UNHEALTHY,
    DataSourceHealth,
)
from app.core.config import FacebookApiConfig, load_facebook_api_config
from app.core.exceptions import ApiError, ApiUnavailableError
from app.core.log import get_logger
from app.core.models import SocialPost, SocialProfile, FetchPostsResult

logger = get_logger(__name__)


# ── Service de collecte Facebook via Graph API. ──
class FacebookApiService:
    """Recuperation des posts Facebook via l'API Graph."""

    def __init__(self, config: FacebookApiConfig | None = None):
        self._config = config or load_facebook_api_config()
        self._client = None

    @property
    def is_available(self) -> bool:
        return self._config.is_configured

    def _get_client(self):
        if self._client is None:
            from app.platforms.facebook.api.client import FacebookGraphClient

            self._client = FacebookGraphClient(self._config)
        return self._client

    def health_check(self) -> DataSourceHealth:
        # Verifier d abord la presence des secrets avant tout appel externe.
        env_flags = {
            "FB_PAGE_ID": bool(self._config.page_id),
            "FB_ACCESS_TOKEN": bool(self._config.access_token),
        }
        missing_env = [name for name, configured in env_flags.items() if not configured]

        if missing_env:
            return DataSourceHealth(
                source="api",
                status=NOT_CONFIGURED,
                message="API Facebook non configuree.",
                details={
                    "missing_env": missing_env,
                    "configured_env": env_flags,
                    "graph_api_base": self._config.graph_api_base,
                },
            )

        try:
            payload = self._get_client().get_page_info(self._config.page_id)
            return DataSourceHealth(
                source="api",
                status=HEALTHY,
                message="API Facebook joignable et authentifiee.",
                details={
                    "configured_env": env_flags,
                    "graph_api_base": self._config.graph_api_base,
                    "page_id": self._config.page_id,
                    "page_name": payload.get("name", ""),
                },
            )
        except (ApiError, TypeError, ValueError) as exc:
            return DataSourceHealth(
                source="api",
                status=UNHEALTHY,
                message=f"API Facebook indisponible: {exc}",
                details={
                    "configured_env": env_flags,
                    "graph_api_base": self._config.graph_api_base,
                    "page_id": self._config.page_id,
                },
            )

    def fetch_posts(self, page_id: str, limit: int) -> FetchPostsResult:
        """Recupere les posts d'une page Facebook.

        Args:
            page_id: ID ou vanity name de la page
            limit: Nombre de posts souhaites

        Returns:
            FetchPostsResult avec source="api"
        """
        if not self.is_available:
            raise ApiUnavailableError(
                "API Facebook non configuree (FB_PAGE_ID / FB_ACCESS_TOKEN manquants)"
            )

        logger.info(f"Tentative API Facebook pour page {page_id} (limit={limit})")

        # 1) Recuperer les metadonnees de page avant les posts.
        profile = self._fetch_profile(page_id)

        # 2) Recuperer puis convertir les posts bruts.
        raw = self._get_client().get_page_posts(page_id, limit=limit)
        posts = self._parse_posts(raw, profile.followers_count)

        logger.info(
            f"API Facebook: {len(posts)} post(s) recuperes pour {page_id}",
            extra={"followers": profile.followers_count},
        )

        return FetchPostsResult(
            posts=posts[:limit],
            source="api",
            platform="facebook",
            username=profile.username or page_id,
            profile=profile,
        )

    def _fetch_profile(self, page_id: str) -> SocialProfile:
        try:
            info = self._get_client().get_page_info(page_id)
            return SocialProfile(
                username=info.get("username", info.get("name", page_id)),
                platform="facebook",
                followers_count=info.get("followers_count", info.get("fan_count", 0)),
                biography=info.get("about", ""),
                full_name=info.get("name", ""),
            )
        except (ApiError, AttributeError, TypeError, ValueError) as e:
            logger.debug(f"Impossible de recuperer le profil de la page: {e}")
            return SocialProfile(username=page_id, platform="facebook")

    def _parse_posts(self, raw: dict, followers_count: int) -> list[SocialPost]:
        posts = []
        for item in raw.get("data", []):
            post = self._item_to_post(item, followers_count)
            if post:
                posts.append(post)
        return posts

    def _item_to_post(self, item: dict, followers_count: int) -> SocialPost | None:
        try:
            likes_data = item.get("likes", {}).get("summary", {})
            comments_data = item.get("comments", {}).get("summary", {})
            shares_data = item.get("shares", {})

            # Mapper le type Graph vers le vocabulaire commun du projet.
            post_type = item.get("type", "status")
            media_type_map = {
                "photo": "image",
                "video": "video",
                "link": "link",
                "status": "status",
            }
            media_type = media_type_map.get(post_type, post_type)

            return SocialPost(
                platform="facebook",
                url=item.get("permalink_url", ""),
                caption=item.get("message", ""),
                timestamp=item.get("created_time", ""),
                likes_count=likes_data.get("total_count", 0),
                comments_count=comments_data.get("total_count", 0),
                # Fusionner plutot que perdre l information de diffusion.
                views_count=shares_data.get("count", 0),
                media_type=media_type,
                user_followers=followers_count,
            )
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(f"Erreur conversion post Facebook", extra={"error": str(e)})
            return None
