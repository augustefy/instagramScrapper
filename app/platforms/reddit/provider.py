"""
Provider Reddit base sur l'API JSON publique.
"""

from app.core.exceptions import ApiError, ScraperError
from app.core.models import FetchPostsResult
from app.platforms.base.provider import PlatformProvider
from app.platforms.reddit.api.service import RedditApiService
from logging_setup import setup_logging

logger = setup_logging(__name__)


class RedditProvider(PlatformProvider):
    def __init__(self, headless: bool = True, debug: bool = False):
        self._debug = debug
        self._service = RedditApiService(debug=debug)

    @property
    def platform_name(self) -> str:
        return "reddit"

    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        logger.info(f"[Reddit] Recuperation du profil @{username} via API JSON (limit={limit})")

        try:
            result = self._service.fetch_profile_posts(username, limit)
        except ApiError as exc:
            raise ScraperError(f"Echec API Reddit pour @{username}: {exc}") from exc
        except Exception as exc:
            raise ScraperError(f"Echec Reddit inattendu pour @{username}: {exc}") from exc

        logger.info(f"[Reddit] {len(result.posts)} post(s) recuperes")
        return result

    def close(self):
        self._service.close()
