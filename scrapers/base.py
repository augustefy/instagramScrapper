from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SocialPost:
    url: str
    platform: str               # "instagram", "tiktok", ...
    caption: str = ""
    timestamp: str = ""
    likes_count: int = 0
    comments_count: int = 0
    views_count: int = 0
    media_type: str = ""        # image, video, carousel, reel, ...
    user_followers: int = 0


class BaseScraper(ABC):
    @abstractmethod
    def scrape(self, url: str, n: int) -> list[SocialPost]:
        """Scrape n posts depuis un profil."""
        ...

    def close(self):
        pass
