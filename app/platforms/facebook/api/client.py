"""
Client HTTP pour l'API Facebook Graph (Page posts).
"""

import requests

from app.core.config import FacebookApiConfig
from app.core.exceptions import ApiUnavailableError, ApiPermissionError, ApiRateLimitError
from app.core.log import get_logger

logger = get_logger(__name__)


# ── Client HTTP bas niveau pour Facebook Graph. ──
class FacebookGraphClient:
    """Client bas niveau pour l'API Facebook Graph."""

    def __init__(self, config: FacebookApiConfig):
        self._config = config
        self._base_url = config.graph_api_base

    def get_page_posts(self, page_id: str, limit: int = 10) -> dict:
        """Recupere les posts d'une Page Facebook.

        Args:
            page_id: ID numerique ou vanity name de la page
            limit: Nombre de posts a recuperer

        Returns:
            Dictionnaire brut de la reponse API

        Raises:
            ApiUnavailableError, ApiPermissionError, ApiRateLimitError
        """
        url = f"{self._base_url}/{page_id}/posts"
        params = {
            "fields": (
                "message,created_time,permalink_url,full_picture,"
                "type,shares,"
                "likes.summary(true).limit(0),"
                "comments.summary(true).limit(0)"
            ),
            "limit": limit,
            "access_token": self._config.access_token,
        }

        logger.debug(f"API Facebook: GET /{page_id}/posts (limit={limit})")

        try:
            response = requests.get(url, params=params, timeout=15)
        except requests.ConnectionError as e:
            raise ApiUnavailableError(f"Impossible de joindre l'API Facebook: {e}") from e
        except requests.Timeout as e:
            raise ApiUnavailableError(f"Timeout API Facebook: {e}") from e
        except requests.RequestException as e:
            raise ApiUnavailableError(f"Erreur reseau API Facebook: {e}") from e

        return self._handle_response(response, page_id)

    def get_page_info(self, page_id: str) -> dict:
        """Recupere les infos d'une Page Facebook.

        Returns:
            Dictionnaire avec name, fan_count, about, etc.
        """
        url = f"{self._base_url}/{page_id}"
        params = {
            "fields": "id,name,username,fan_count,about,followers_count",
            "access_token": self._config.access_token,
        }

        logger.debug(f"API Facebook: GET /{page_id} (info)")

        try:
            response = requests.get(url, params=params, timeout=15)
        except requests.RequestException as e:
            raise ApiUnavailableError(f"Erreur reseau API Facebook: {e}") from e

        return self._handle_response(response, page_id)

    def _handle_response(self, response: requests.Response, page_id: str) -> dict:
        if response.status_code == 200:
            logger.debug(f"API Facebook: reponse OK pour {page_id}")
            return response.json()

        try:
            error_data = response.json()
        except ValueError:
            error_data = {"error": {"message": response.text}}

        error_info = error_data.get("error", {})
        error_msg = error_info.get("message", "Erreur inconnue")
        error_code = error_info.get("code", 0)

        logger.debug(
            f"API Facebook erreur {response.status_code}",
            extra={"error_code": error_code, "error_message": error_msg},
        )

        if error_code in (190, 102):
            raise ApiPermissionError(f"Token invalide ou expire: {error_msg}")

        if error_code in (10, 200, 803):
            raise ApiPermissionError(f"Permissions insuffisantes pour {page_id}: {error_msg}")

        if response.status_code == 429 or error_code == 4:
            raise ApiRateLimitError(f"Rate limit atteint: {error_msg}")

        if error_code == 100:
            raise ApiPermissionError(f"Page {page_id} introuvable via l'API: {error_msg}")

        raise ApiUnavailableError(f"Erreur API Facebook ({response.status_code}): {error_msg}")
