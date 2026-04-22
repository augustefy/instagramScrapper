"""
Facade Twitter / X dediee.
"""

from __future__ import annotations

from typing import Any

from app.core.models import FetchPostsResult, NormalizedPost, NormalizedProfile
from app.platforms.twitter.provider import TwitterProvider
from app.platforms.twitter.url import extract_username, parse_twitter_profile_url


class TwitterScraper:
    """API interne simple pour le scraping d'un profil Twitter/X."""

    def __init__(self, *, debug: bool = False):
        self._provider = TwitterProvider(debug=debug)

    def fetch(self, url: str, limit: int) -> FetchPostsResult:
        parsed = parse_twitter_profile_url(url)
        return self._provider.fetch_posts(parsed.username, limit)

    def scrape_profile(self, url: str, limit: int) -> dict[str, Any]:
        return self.fetch(url, limit).to_dict()

    def close(self) -> None:
        self._provider.close()

    def __enter__(self) -> "TwitterScraper":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def scrape_twitter_user(
    url: str,
    limit: int,
    *,
    debug: bool = False,
) -> tuple[NormalizedProfile, list[NormalizedPost]]:
    with TwitterScraper(debug=debug) as scraper:
        result = scraper.fetch(url, limit)
        return result.profile, result.posts


__all__ = ["TwitterScraper", "scrape_twitter_user", "extract_username"]
