"""
Client HTTP minimal pour l'API JSON publique Reddit.
"""

from __future__ import annotations

from typing import Any

import requests

from app.core.exceptions import (
    ApiError,
    ApiRateLimitError,
    ApiUnavailableError,
    EmptyResponseError,
    InvalidResponseError,
    UserNotFoundError,
)

_BASE_URL = "https://www.reddit.com"
_DEFAULT_TIMEOUT = (5, 20)
_USER_AGENT = "instagramScrapper/1.0 (+https://github.com/openai/codex)"


class RedditApiClient:
    def __init__(self, user_agent: str = _USER_AGENT, timeout: tuple[int, int] = _DEFAULT_TIMEOUT):
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
            }
        )

    def close(self) -> None:
        self._session.close()

    def fetch_user_about(self, username: str) -> dict[str, Any]:
        return self._get_json(f"/user/{username}/about.json")

    def fetch_user_submitted(self, username: str, limit: int) -> dict[str, Any]:
        return self._get_json(f"/user/{username}/submitted.json", params={"limit": limit})

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{_BASE_URL}{path}"

        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ApiUnavailableError(f"Erreur reseau vers Reddit: {exc}") from exc

        if response.status_code == 404:
            raise UserNotFoundError("Utilisateur Reddit introuvable.")
        if response.status_code == 429:
            raise ApiRateLimitError("Rate limit Reddit atteint.")
        if response.status_code >= 400:
            raise ApiError(f"Erreur HTTP Reddit {response.status_code}: {response.text[:200]}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise InvalidResponseError("La reponse Reddit n'est pas un JSON valide.") from exc

        if not isinstance(payload, dict):
            raise InvalidResponseError("La reponse Reddit JSON a un format inattendu.")

        if not payload:
            raise EmptyResponseError("La reponse Reddit est vide.")

        return payload
