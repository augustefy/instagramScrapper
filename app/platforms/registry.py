"""
Registre des plateformes : detection depuis une URL et instanciation du provider.
"""

from urllib.parse import urlparse

from app.core.exceptions import UnsupportedPlatformError


# ── Mapping domaine racine -> nom de plateforme. ──
# Seul le domaine racine (ex: "instagram.com") est stocke ; les sous-domaines
# (www., m., mobile., i., ...) sont strips a la detection, ce qui couvre
# automatiquement toutes leurs variantes.
_ROOT_DOMAIN_MAP: dict[str, str] = {
    "instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "x.com": "twitter",
    "twitter.com": "twitter",
    "reddit.com": "reddit",
    "redd.it": "reddit",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "fb.me": "facebook",
}

# Prefixes de sous-domaines a ignorer lors de la normalisation.
_IGNORED_SUBDOMAINS = {"www", "m", "mobile", "i", "l"}


def _root_domain(netloc: str) -> str:
    """Extrait le domaine racine (domaine + TLD) depuis un netloc.

    Exemples :
        "mobile.twitter.com" -> "twitter.com"
        "www.instagram.com"  -> "instagram.com"
        "reddit.com"         -> "reddit.com"
    """
    parts = netloc.split(".")
    # Retire les sous-domaines connus en tete jusqu'a tomber sur la partie enregistree.
    while len(parts) > 2 and parts[0] in _IGNORED_SUBDOMAINS:
        parts = parts[1:]
    return ".".join(parts)


# ── Exposition de la liste deduite du mapping domaine. ──
def list_supported_platforms() -> list[str]:
    """Retourne les plateformes pour lesquelles un provider existe."""
    return sorted(set(_ROOT_DOMAIN_MAP.values()))


# ── Detection robuste de la plateforme depuis le domaine. ──
def detect_platform(url: str) -> str:
    """Detecte la plateforme depuis une URL.

    Returns:
        Nom de la plateforme ("instagram", "tiktok", ...)

    Raises:
        UnsupportedPlatformError: Si la plateforme n'est pas reconnue
    """
    if not isinstance(url, str) or not url.strip():
        raise UnsupportedPlatformError(
            f"URL invalide pour la detection de plateforme : {url!r}. "
            f"Plateformes supportees : {list_supported_platforms()}"
        )

    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError as exc:
        raise UnsupportedPlatformError(
            f"URL invalide pour la detection de plateforme : {url!r}. "
            f"Plateformes supportees : {list_supported_platforms()}"
        ) from exc

    platform = _ROOT_DOMAIN_MAP.get(_root_domain(netloc))
    if platform:
        return platform

    raise UnsupportedPlatformError(
        f"Plateforme non reconnue depuis l'URL : {url!r}. "
        f"Plateformes supportees : {list_supported_platforms()}"
    )


# ── Delegation vers l extracteur adapte a la plateforme. ──
def extract_username(url: str, platform: str) -> str:
    """Extrait le username depuis une URL de profil.

    Args:
        url: URL du profil
        platform: Nom de la plateforme

    Returns:
        Username normalise (sans @, sans trailing slash)
    """
    match platform:
        case "instagram":
            from app.platforms.instagram.url import extract_username as _fn
            return _fn(url)
        case "tiktok":
            from app.platforms.tiktok.url import extract_username as _fn
            return _fn(url)
        case "twitter":
            from app.platforms.twitter.url import extract_username as _fn
            return _fn(url)
        case "reddit":
            from app.platforms.reddit.url import extract_username as _fn
            return _fn(url)
        case _:
            # Fallback generique : premier segment du path.
            path = urlparse(url).path.strip("/")
            return path.split("/")[0].lstrip("@")


# ── Instanciation paresseuse du provider cible. ──
def get_provider(platform: str, headless: bool = True, debug: bool = False):
    """Instancie le provider pour une plateforme donnee.

    Returns:
        Instance de PlatformProvider

    Raises:
        UnsupportedPlatformError: Si la plateforme n'a pas de provider
    """
    match platform:
        case "instagram":
            from app.platforms.instagram.provider import InstagramProvider
            return InstagramProvider(headless=headless, debug=debug)
        case "tiktok":
            from app.platforms.tiktok.provider import TikTokProvider
            return TikTokProvider(headless=headless, debug=debug)
        case "twitter":
            from app.platforms.twitter.provider import TwitterProvider
            return TwitterProvider(headless=headless, debug=debug)
        case "reddit":
            from app.platforms.reddit.provider import RedditProvider
            return RedditProvider(debug=debug)
        case "facebook":
            from app.platforms.facebook.provider import FacebookProvider
            return FacebookProvider(headless=headless, debug=debug)
        case _:
            raise UnsupportedPlatformError(f"Pas de provider pour la plateforme : {platform!r}")
