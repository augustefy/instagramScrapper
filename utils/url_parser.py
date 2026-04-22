"""
Parsing centralise des URLs de profils sociaux.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from app.core.exceptions import InvalidUrlError


TWITTER_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
_TWITTER_RESERVED_SEGMENTS = {
    "compose",
    "explore",
    "hashtag",
    "home",
    "i",
    "intent",
    "login",
    "messages",
    "notifications",
    "search",
    "settings",
    "share",
    "signup",
    "tos",
    "privacy",
}
_TWITTER_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


@dataclass(frozen=True)
class ParsedTwitterProfileUrl:
    original_url: str
    host: str
    username: str
    canonical_url: str


def build_twitter_profile_url(username: str) -> str:
    normalized = username.strip().lstrip("@")
    if not _TWITTER_USERNAME_RE.fullmatch(normalized):
        raise InvalidUrlError(
            "Username Twitter/X invalide : seuls les caracteres alphanumeriques "
            "et '_' sont autorises (1 a 15 caracteres)."
        )
    return f"https://x.com/{normalized}"


def parse_twitter_profile_url(url: str) -> ParsedTwitterProfileUrl:
    if not isinstance(url, str) or not url.strip():
        raise InvalidUrlError("URL Twitter/X invalide : valeur vide.")

    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()

    if host not in TWITTER_HOSTS:
        raise InvalidUrlError(
            f"URL Twitter/X invalide : domaine non supporte ({host or 'vide'})."
        )

    segments = [unquote(segment).strip() for segment in parsed.path.split("/") if segment.strip()]
    if not segments:
        raise InvalidUrlError("URL Twitter/X invalide : username manquant.")

    if len(segments) > 1:
        if len(segments) >= 2 and segments[1].lower() == "status":
            raise InvalidUrlError(
                "URL Twitter/X invalide : une URL de post a ete fournie au lieu d'un profil."
            )
        raise InvalidUrlError(
            "URL Twitter/X invalide : seul le format /<username> est accepte."
        )

    username = segments[0].lstrip("@")
    if not username:
        raise InvalidUrlError("URL Twitter/X invalide : username vide.")
    if username.lower() in _TWITTER_RESERVED_SEGMENTS:
        raise InvalidUrlError(
            f"URL Twitter/X invalide : '{username}' n'est pas un username de profil."
        )
    if not _TWITTER_USERNAME_RE.fullmatch(username):
        raise InvalidUrlError(
            "Username Twitter/X invalide : seuls les caracteres alphanumeriques "
            "et '_' sont autorises (1 a 15 caracteres)."
        )

    return ParsedTwitterProfileUrl(
        original_url=url,
        host=host,
        username=username,
        canonical_url=build_twitter_profile_url(username),
    )


def extract_twitter_username(url: str) -> str:
    return parse_twitter_profile_url(url).username
