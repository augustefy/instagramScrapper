"""
Service source provider Twitter / X.

Cette couche ne fait que recuperer et valider les donnees brutes.
La normalisation vers le modele commun est volontairement separee.
"""

from __future__ import annotations

from typing import Any

from app.core.health import HEALTHY, UNHEALTHY, DataSourceHealth
from app.core.exceptions import ApiError, EmptyResponseError, InvalidLimitError, InvalidResponseError


class TwitterApiService:
    def __init__(self, client: TwitterApiClient | None = None, *, debug: bool = False):
        self._client = client
        self._debug = debug

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def _get_client(self):
        if self._client is None:
            from app.platforms.twitter.api.client import TwitterApiClient

            self._client = TwitterApiClient()
        return self._client

    def health_check(self) -> DataSourceHealth:
        probe_username = "OpenAI"
        try:
            payload = self.fetch_profile_payload(probe_username)
            return DataSourceHealth(
                source="guest_api",
                status=HEALTHY,
                message="Endpoints web Twitter/X joignables.",
                details={
                    "probe_username": payload.get("screen_name", probe_username),
                    "base_url": "https://api.twitter.com/1.1",
                },
            )
        except ApiError as exc:
            return DataSourceHealth(
                source="guest_api",
                status=UNHEALTHY,
                message=f"Twitter/X indisponible: {exc}",
                details={
                    "probe_username": probe_username,
                    "base_url": "https://api.twitter.com/1.1",
                },
            )

    def fetch_profile_payload(self, username: str) -> dict[str, Any]:
        payload = self._get_client().fetch_user(username)
        if not isinstance(payload, dict):
            raise InvalidResponseError("Le profil Twitter/X n'est pas un objet JSON.")
        if not payload:
            raise EmptyResponseError("Le profil Twitter/X est vide.")
        return payload

    def fetch_posts_payload(
        self,
        username: str,
        *,
        limit: int,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            raise InvalidLimitError("La limite doit etre un entier strictement positif.")

        payload = self._get_client().fetch_user_timeline(
            username=username,
            user_id=user_id,
            limit=min(limit, 200),
        )

        if not isinstance(payload, list):
            raise InvalidResponseError("La timeline Twitter/X n'est pas une liste.")

        return [item for item in payload if isinstance(item, dict)][:limit]

    def fetch_profile_posts_payload(self, username: str, limit: int) -> dict[str, Any]:
        profile = self.fetch_profile_payload(username)

        if profile.get("protected") is True:
            from app.core.exceptions import ProtectedProfileError

            raise ProtectedProfileError("Le profil Twitter/X est protege et inaccessible.")

        user_id = str(profile.get("id_str") or profile.get("id") or "").strip() or None
        posts = self.fetch_posts_payload(username, limit=limit, user_id=user_id)

        return {
            "source": "guest_api",
            "profile": profile,
            "posts": posts,
        }
