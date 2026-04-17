"""
Service scraper Instagram : wrapper autour du scraper Playwright existant.
Convertit les resultats en FetchPostsResult.
"""

from app.core.exceptions import ScraperError
from app.core.models import FetchPostsResult
from bench import Bench
from logging_setup import setup_logging

logger = setup_logging(__name__)

# URL de base Instagram
_BASE_URL = "https://www.instagram.com"


class InstagramScraperService:
    """Wrapper autour du scraper Instagram existant (scrapers.instagram)."""

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._scraper = None

    def _get_scraper(self):
        if self._scraper is None:
            from scrapers.instagram.scraper import InstagramScraper
            self._scraper = InstagramScraper(headless=self._headless, bench=Bench())
        return self._scraper

    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        """Scrape les posts d'un profil Instagram.

        Args:
            username: Username Instagram (sans @)
            limit: Nombre de posts a recuperer

        Returns:
            FetchPostsResult avec source="scraper"

        Raises:
            ScraperError: Si le scraping echoue
        """
        url = f"{_BASE_URL}/{username}/"
        logger.info(f"Scraping Instagram pour @{username} (limit={limit})")

        try:
            scraper = self._get_scraper()
            posts = scraper.scrape(url, limit)
        except Exception as e:
            raise ScraperError(f"Echec du scraping Instagram pour @{username}: {e}") from e

        logger.info(f"Scraper Instagram: {len(posts)} post(s) recuperes pour @{username}")

        return FetchPostsResult(
            posts=posts,
            source="scraper",
            platform="instagram",
            username=username,
        )

    def close(self):
        if self._scraper is not None:
            self._scraper.close()
            self._scraper = None
