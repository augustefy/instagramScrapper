from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
# ── Modele legacy partage par les scrapers historiques. ──
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


# ── Contrat minimal pour tous les scrapers concrets. ──
class BaseScraper(ABC):
    @abstractmethod
    def scrape(self, url: str, n: int) -> list[SocialPost]:
        """Scrape n posts depuis un profil."""
        ...

    def close(self) -> None:
        pass
