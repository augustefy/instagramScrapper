"""
Helper HTTP centralise pour les appels reseau JSON.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

import requests

from app.core.exceptions import ApiUnavailableError, InvalidResponseError


DEFAULT_USER_AGENT = (
    "instagramScrapper/1.0 (+https://github.com/openai/codex; "
    "multi-platform social scraper)"
)
DEFAULT_TIMEOUT = (5, 20)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class RequestsHttpClient:
    """Client HTTP minimal avec session partagee et retries simples."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: tuple[int, int] = DEFAULT_TIMEOUT,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
    ) -> None:
        self._session = session or requests.Session()
        self._owns_session = session is None
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds

        self._session.headers.setdefault("User-Agent", user_agent)
        self._session.headers.setdefault("Accept", "application/json, text/plain, */*")
        self._session.headers.setdefault("Accept-Language", "en-US,en;q=0.9")

    @property
    def session(self) -> requests.Session:
        return self._session

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Any = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: tuple[int, int] | None = None,
        allow_redirects: bool = True,
    ) -> requests.Response:
        effective_timeout = timeout or self._timeout

        for attempt in range(self._max_retries + 1):
            try:
                response = self._session.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    json=json,
                    headers=dict(headers or {}),
                    timeout=effective_timeout,
                    allow_redirects=allow_redirects,
                )
            except requests.Timeout as exc:
                if attempt < self._max_retries:
                    time.sleep(self._backoff_seconds * (attempt + 1))
                    continue
                raise ApiUnavailableError(f"Timeout HTTP vers {url}: {exc}") from exc
            except requests.RequestException as exc:
                if attempt < self._max_retries:
                    time.sleep(self._backoff_seconds * (attempt + 1))
                    continue
                raise ApiUnavailableError(f"Erreur reseau vers {url}: {exc}") from exc

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                time.sleep(self._backoff_seconds * (attempt + 1))
                continue

            return response

        raise ApiUnavailableError(f"Echec HTTP apres retries vers {url}.")

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: tuple[int, int] | None = None,
    ) -> Any:
        response = self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
        )

        try:
            return response.json()
        except ValueError as exc:
            raise InvalidResponseError(f"JSON invalide recu depuis {url}.") from exc
