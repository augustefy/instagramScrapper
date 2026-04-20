"""
Parsing et normalisation des URLs Reddit.
"""

from urllib.parse import urlparse

from app.core.exceptions import InvalidUrlError

_VALID_HOSTS = {"reddit.com", "www.reddit.com"}
_VALID_PREFIXES = {"user", "u"}


def extract_username(url: str) -> str:
    """Extrait le username depuis une URL Reddit de profil."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    segments = [segment for segment in parsed.path.split("/") if segment]

    if host not in _VALID_HOSTS:
        raise InvalidUrlError(f"URL Reddit invalide : domaine non supporte ({host or 'vide'}).")

    if len(segments) < 2 or segments[0].lower() not in _VALID_PREFIXES:
        raise InvalidUrlError(
            "URL Reddit invalide : format attendu https://www.reddit.com/user/<username>/ "
            "ou https://www.reddit.com/u/<username>/"
        )

    username = segments[1].strip()
    if not username:
        raise InvalidUrlError("URL Reddit invalide : username manquant.")

    return username


def build_profile_url(username: str) -> str:
    return f"https://www.reddit.com/user/{username}/"
