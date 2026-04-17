"""
Modeles de donnees communs a toutes les plateformes.
Reutilise SocialPost de scrapers.base pour la compatibilite.
"""

from dataclasses import dataclass, field
from scrapers.base import SocialPost


@dataclass
class SocialProfile:
    username: str
    platform: str
    followers_count: int = 0
    following_count: int = 0
    posts_count: int = 0
    biography: str = ""
    full_name: str = ""


@dataclass
class FetchPostsResult:
    posts: list[SocialPost]
    source: str  # "api", "scraper"
    platform: str
    username: str
    profile: SocialProfile | None = None
