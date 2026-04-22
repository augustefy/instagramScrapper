"""
Service metier Reddit base sur les endpoints JSON publics.
"""

from __future__ import annotations

from typing import Any

from app.core.health import HEALTHY, UNHEALTHY, DataSourceHealth
from app.core.exceptions import ApiError, EmptyResponseError, InvalidLimitError, InvalidResponseError
from app.core.models import FetchPostsResult, NormalizedPost, NormalizedProfile
from app.platforms.reddit.normalizer import normalize_post, normalize_profile


# ── Service de collecte Reddit base sur l API publique JSON. ──
class RedditApiService:
    def __init__(self, client: RedditApiClient | None = None, *, debug: bool = False):
        self._client = client
        self._debug = debug

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def _get_client(self):
        if self._client is None:
            from app.platforms.reddit.api.client import RedditApiClient

            self._client = RedditApiClient()
        return self._client

    def health_check(self) -> DataSourceHealth:
        # Probe stable et public pour verifier la disponibilite JSON.
        probe_username = "spez"
        try:
            payload = self._get_client().fetch_user_about(probe_username)
            data = self._extract_data_object(payload, context="health")
            return DataSourceHealth(
                source="api",
                status=HEALTHY,
                message="Json Reddit joignable.",
                details={
                    "probe_username": data.get("name", probe_username),
                    "base_url": "https://www.reddit.com",
                },
            )
        except ApiError as exc:
            return DataSourceHealth(
                source="api",
                status=UNHEALTHY,
                message=f"API Reddit indisponible: {exc}",
                details={
                    "probe_username": probe_username,
                    "base_url": "https://www.reddit.com",
                },
            )

    def fetch_profile(self, username: str) -> NormalizedProfile:
        payload = self._get_client().fetch_user_about(username)
        data = self._extract_data_object(payload, context="profil")
        return normalize_profile(username, data, include_raw=self._debug)

    def fetch_posts(self, username: str, limit: int) -> list[NormalizedPost]:
        if limit <= 0:
            raise InvalidLimitError("La limite doit etre un entier strictement positif.")

        payload = self._get_client().fetch_user_submitted(username, min(limit, 100))
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
                # Ne normaliser que les entrees completement exploitables.
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
