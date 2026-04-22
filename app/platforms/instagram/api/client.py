"""
Client HTTP pour l'API Instagram Graph (Facebook Graph API).
Utilise l'endpoint business_discovery pour recuperer les posts d'un profil business/creator.
"""

import requests

from app.core.config import InstagramApiConfig
from app.core.exceptions import ApiUnavailableError, ApiPermissionError, ApiRateLimitError
from app.core.log import get_logger

logger = get_logger(__name__)


# ── Client HTTP bas niveau pour Instagram Graph. ──
class InstagramGraphClient:
    """Client bas niveau pour l'API Instagram Graph."""

    def __init__(self, config: InstagramApiConfig):
        self._config = config
        self._base_url = config.graph_api_base

    def get_business_discovery(self, target_username: str, media_limit: int = 25) -> dict:
        """Recupere le profil et les posts d'un compte business/creator via business_discovery.

        Args:
            target_username: Le username Instagram cible (sans @)
            media_limit: Nombre de posts a recuperer

        Returns:
            Dictionnaire brut de la reponse API (cle "business_discovery")

        Raises:
            ApiUnavailableError: API injoignable ou erreur serveur
            ApiPermissionError: Token invalide, permissions insuffisantes, ou compte non-business
            ApiRateLimitError: Rate limit atteint
        """
        media_fields = (
            "id,caption,media_type,media_url,permalink,"
            "timestamp,like_count,comments_count"
        )
        profile_fields = (
            f"username,name,biography,followers_count,follows_count,media_count,"
            f"media.limit({media_limit}){{{media_fields}}}"
        )
        fields_param = f"business_discovery.username({target_username}){{{profile_fields}}}"

        url = f"{self._base_url}/{self._config.ig_user_id}"
        params = {
            "fields": fields_param,
            "access_token": self._config.user_long_token,
        }

        logger.debug(
            f"API Instagram: GET /{self._config.ig_user_id} pour @{target_username}",
            extra={"media_limit": media_limit},
        )

        try:
            # Timeout court pour eviter de bloquer le fallback scraper.
            response = requests.get(url, params=params, timeout=15)
        except requests.ConnectionError as e:
            raise ApiUnavailableError(f"Impossible de joindre l'API Instagram: {e}") from e
        except requests.Timeout as e:
            raise ApiUnavailableError(f"Timeout API Instagram: {e}") from e
        except requests.RequestException as e:
            raise ApiUnavailableError(f"Erreur reseau API Instagram: {e}") from e

        return self._handle_response(response, target_username)

    def probe_account(self) -> dict:
        """Verifie que le token et l'identifiant Instagram sont exploitables."""
        url = f"{self._base_url}/{self._config.ig_user_id}"
        params = {
            "fields": "id,username",
            "access_token": self._config.user_long_token,
        }

        try:
            response = requests.get(url, params=params, timeout=10)
        except requests.ConnectionError as e:
            raise ApiUnavailableError(f"Impossible de joindre l'API Instagram: {e}") from e
        except requests.Timeout as e:
            raise ApiUnavailableError(f"Timeout API Instagram: {e}") from e
        except requests.RequestException as e:
            raise ApiUnavailableError(f"Erreur reseau API Instagram: {e}") from e

        return self._handle_response(response, self._config.ig_user_id)

    def _handle_response(self, response: requests.Response, target_username: str) -> dict:
        """Traite la reponse HTTP et leve les exceptions appropriees."""
        if response.status_code == 200:
            data = response.json()
            logger.debug(f"API Instagram: reponse OK pour @{target_username}")
            return data

        try:
            error_data = response.json()
        except ValueError:
            error_data = {"error": {"message": response.text}}

        error_info = error_data.get("error", {})
        error_msg = error_info.get("message", "Erreur inconnue")
        error_code = error_info.get("code", 0)
        error_subcode = error_info.get("error_subcode", 0)

        logger.debug(
            f"API Instagram erreur {response.status_code}",
            extra={"error_code": error_code, "error_subcode": error_subcode, "error_message": error_msg},
        )

        # 1) Cas token non exploitable.
        if error_code in (190, 102):
            raise ApiPermissionError(f"Token invalide ou expire: {error_msg}")

        # 2) Cas droits insuffisants sur le compte cible.
        if error_code in (10, 200, 803):
            raise ApiPermissionError(
                f"Permissions insuffisantes pour @{target_username}: {error_msg}"
            )

        # 3) Cas throttling cote plateforme.
        if response.status_code == 429 or error_code == 4:
            raise ApiRateLimitError(f"Rate limit atteint: {error_msg}")

        # 4) Cas business_discovery non autorise sur le compte cible.
        if error_code == 100 and error_subcode == 2018001:
            raise ApiPermissionError(
                f"@{target_username} n'est pas un compte Business/Creator "
                f"(requis pour business_discovery)"
            )

        # 5) Cas profil absent ou non resolu.
        if error_code == 100:
            raise ApiPermissionError(
                f"Compte @{target_username} introuvable via l'API: {error_msg}"
            )

        # 6) Cas residuel: remonter une indisponibilite generique.
        raise ApiUnavailableError(
            f"Erreur API Instagram ({response.status_code}): {error_msg}"
        )
