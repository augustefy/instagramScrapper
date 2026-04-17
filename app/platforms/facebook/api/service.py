"""
Service API Facebook : recupere les posts via Graph API et les convertit en SocialPost.
"""

from app.core.config import FacebookApiConfig, load_facebook_api_config
from app.core.exceptions import ApiUnavailableError
from app.core.models import SocialPost, SocialProfile, FetchPostsResult
from app.platforms.facebook.api.client import FacebookGraphClient
from logging_setup import setup_logging

logger = setup_logging(__name__)


class FacebookApiService:
    """Recuperation des posts Facebook via l'API Graph."""

    def __init__(self, config: FacebookApiConfig | None = None):
        self._config = config or load_facebook_api_config()
        self._client = FacebookGraphClient(self._config)

    @property
    def is_available(self) -> bool:
        return self._config.is_configured

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

        # Recupere les infos de la page
        profile = self._fetch_profile(page_id)

        # Recupere les posts
        raw = self._client.get_page_posts(page_id, limit=limit)
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
            info = self._client.get_page_info(page_id)
            return SocialProfile(
                username=info.get("username", info.get("name", page_id)),
                platform="facebook",
                followers_count=info.get("followers_count", info.get("fan_count", 0)),
                biography=info.get("about", ""),
                full_name=info.get("name", ""),
            )
        except Exception as e:
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

            # Type de media
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
                views_count=shares_data.get("count", 0),  # shares dans views_count
                media_type=media_type,
                user_followers=followers_count,
            )
        except Exception as e:
            logger.debug(f"Erreur conversion post Facebook", extra={"error": str(e)})
            return None
