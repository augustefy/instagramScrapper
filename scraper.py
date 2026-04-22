from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bench import Bench
from scrapers.base import SocialPost
from scrapers.instagram.scraper import InstagramScraper as _InstagramScraper


@dataclass
class PostData:
    """Compatibilite avec l'ancien import `from scraper import PostData`."""

    url: str
    caption: str = ""
    timestamp: str = ""
    likes_count: int = 0
    comments_count: int = 0
    views_count: int | None = 0
    media_type: str = ""
    user_followers: int = 0

    @classmethod
    def from_social_post(cls, post: SocialPost) -> PostData:
        return cls(
            url=post.url,
            caption=post.caption,
            timestamp=post.timestamp,
            likes_count=post.likes_count,
            comments_count=post.comments_count,
            views_count=post.views_count,
            media_type=post.media_type,
            user_followers=post.user_followers,
        )


class InstagramScraper:
    """Facade legacy autour du scraper Instagram modulaire."""

    def __init__(self, headless: bool = True, bench: Bench | None = None) -> None:
        self._delegate = _InstagramScraper(headless=headless, bench=bench)

    def scrape(self, url: str, n: int) -> list[PostData]:
        posts = self._delegate.scrape(url, n)
        return [PostData.from_social_post(post) for post in posts]

    def health_check(self) -> dict[str, Any]:
        return self._delegate.health_check()

    def close(self) -> None:
        self._delegate.close()
