"""
Provider TikTok : wrapper autour du scraper TikTok existant.
Pas d'API officielle pour l'instant, donc scraper uniquement.
"""

from app.core.exceptions import ScraperError
from app.core.models import FetchPostsResult
from app.platforms.base.provider import PlatformProvider
from bench import Bench
from logging_setup import setup_logging

logger = setup_logging(__name__)

_BASE_URL = "https://www.tiktok.com"


class TikTokProvider(PlatformProvider):
    """Provider TikTok (scraper uniquement pour l'instant)."""

    def __init__(self, headless: bool = True, debug: bool = False):
        self._headless = headless
        self._debug = debug
        self._scraper = None

    @property
    def platform_name(self) -> str:
        return "tiktok"

    def _get_scraper(self):
        if self._scraper is None:
            from scrapers.tiktok.scraper import TikTokScraper
            self._scraper = TikTokScraper(headless=self._headless, bench=Bench())
        return self._scraper

    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        """Scrape les posts TikTok."""
        url = f"{_BASE_URL}/@{username}"
        logger.info(f"[TikTok] Scraping de @{username} (limit={limit})")

        try:
            scraper = self._get_scraper()
            posts = scraper.scrape(url, limit)
        except Exception as e:
            raise ScraperError(f"Echec du scraping TikTok pour @{username}: {e}") from e

        logger.info(f"[TikTok] {len(posts)} post(s) recuperes")

        return FetchPostsResult(
            posts=posts,
            source="scraper",
            platform="tiktok",
            username=username,
        )

    def close(self):
        if self._scraper is not None:
            self._scraper.close()
            self._scraper = None
