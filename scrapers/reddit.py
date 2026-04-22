"""
Facade Reddit dediee pour un usage simple depuis une URL de profil.
"""

from __future__ import annotations

from app.core.exceptions import InvalidLimitError
from app.platforms.reddit.provider import RedditProvider
from app.platforms.reddit.url import extract_username


# ── Facade simple pour usage ponctuel depuis une URL. ──
def scrape_reddit_user(url: str, limit: int, *, debug: bool = False) -> tuple[dict, list[dict]]:
    if limit <= 0:
        raise InvalidLimitError("La limite doit etre un entier strictement positif.")

    username = extract_username(url)
    provider = RedditProvider(debug=debug)

    try:
        result = provider.fetch_posts(username, limit)
        payload = result.to_dict()
        return payload["profile"], payload["posts"]
    finally:
        provider.close()


# ── Wrapper orienté objet autour du provider Reddit. ──
class RedditScraper:
    def __init__(self, *, debug: bool = False):
        self._provider = RedditProvider(debug=debug)

    def scrape_profile(self, url: str, limit: int) -> dict:
        if limit <= 0:
            raise InvalidLimitError("La limite doit etre un entier strictement positif.")

        username = extract_username(url)
        result = self._provider.fetch_posts(username, limit)
        return result.to_dict()

    def close(self) -> None:
        self._provider.close()
