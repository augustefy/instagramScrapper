"""
Service metier Reddit base sur les endpoints JSON publics.
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import EmptyResponseError, InvalidLimitError, InvalidResponseError
from app.core.models import FetchPostsResult, NormalizedPost, NormalizedProfile
from app.platforms.reddit.api.client import RedditApiClient
from app.platforms.reddit.normalizer import normalize_post, normalize_profile


class RedditApiService:
    def __init__(self, client: RedditApiClient | None = None, *, debug: bool = False):
        self._client = client or RedditApiClient()
        self._debug = debug

    def close(self) -> None:
        self._client.close()

    def fetch_profile(self, username: str) -> NormalizedProfile:
        payload = self._client.fetch_user_about(username)
        data = self._extract_data_object(payload, context="profil")
        return normalize_profile(username, data, include_raw=self._debug)

    def fetch_posts(self, username: str, limit: int) -> list[NormalizedPost]:
        if limit <= 0:
            raise InvalidLimitError("La limite doit etre un entier strictement positif.")

        payload = self._client.fetch_user_submitted(username, min(limit, 100))
        data = self._extract_data_object(payload, context="posts")
        children = data.get("children")

        if children is None:
            raise EmptyResponseError("La liste des posts Reddit est absente.")
        if not isinstance(children, list):
            raise InvalidResponseError("Le champ Reddit children n'est pas une liste.")

        posts: list[NormalizedPost] = []
        for child in children[:limit]:
            if not isinstance(child, dict):
                continue
            child_data = child.get("data")
            if isinstance(child_data, dict):
                posts.append(normalize_post(username, child_data, include_raw=self._debug))

        return posts

    def fetch_profile_posts(self, username: str, limit: int) -> FetchPostsResult:
        profile = self.fetch_profile(username)
        posts = self.fetch_posts(username, limit)
        return FetchPostsResult(
            posts=posts,
            source="api",
            platform="reddit",
            username=username,
            profile=profile,
        )

    @staticmethod
    def _extract_data_object(payload: dict[str, Any], *, context: str) -> dict[str, Any]:
        data = payload.get("data")
        if data is None:
            raise EmptyResponseError(f"La reponse Reddit pour {context} ne contient pas de champ data.")
        if not isinstance(data, dict):
            raise InvalidResponseError(f"Le champ data Reddit pour {context} n'est pas un objet.")
        return data
