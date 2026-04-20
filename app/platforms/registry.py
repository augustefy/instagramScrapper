"""
Registre des plateformes : detection depuis une URL et instanciation du provider.
"""

from urllib.parse import urlparse

from app.core.exceptions import UnsupportedPlatformError


# Mapping domaine -> nom de plateforme
_DOMAIN_MAP: dict[str, str] = {
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "www.tiktok.com": "tiktok",
    "reddit.com": "reddit",
    "www.reddit.com": "reddit",
    "facebook.com": "facebook",
    "www.facebook.com": "facebook",
    "fb.com": "facebook",
    "www.fb.com": "facebook",
}


def detect_platform(url: str) -> str:
    """Detecte la plateforme depuis une URL.

    Returns:
        Nom de la plateforme ("instagram", "tiktok", ...)

    Raises:
        UnsupportedPlatformError: Si la plateforme n'est pas reconnue
    """
    try:
        netloc = urlparse(url).netloc.lower()
        platform = _DOMAIN_MAP.get(netloc)
        if platform:
            return platform
    except Exception:
        pass
    raise UnsupportedPlatformError(
        f"Plateforme non reconnue depuis l'URL : {url!r}. "
        f"Plateformes supportees : {sorted(set(_DOMAIN_MAP.values()))}"
    )


def extract_username(url: str, platform: str) -> str:
    """Extrait le username depuis une URL de profil.

    Args:
        url: URL du profil
        platform: Nom de la plateforme

    Returns:
        Username normalise (sans @, sans trailing slash)
    """
    if platform == "instagram":
        from app.platforms.instagram.url import extract_username as extract_instagram_username
        return extract_instagram_username(url)
    elif platform == "tiktok":
        from app.platforms.tiktok.url import extract_username as extract_tiktok_username
        return extract_tiktok_username(url)
    elif platform == "reddit":
        from app.platforms.reddit.url import extract_username as extract_reddit_username
        return extract_reddit_username(url)

    path = urlparse(url).path.strip("/")
    return path.split("/")[0].lstrip("@")


def get_provider(platform: str, headless: bool = True, debug: bool = False):
    """Instancie le provider pour une plateforme donnee.

    Returns:
        Instance de PlatformProvider

    Raises:
        UnsupportedPlatformError: Si la plateforme n'a pas de provider
    """
    if platform == "instagram":
        from app.platforms.instagram.provider import InstagramProvider
        return InstagramProvider(headless=headless, debug=debug)
    elif platform == "tiktok":
        from app.platforms.tiktok.provider import TikTokProvider
        return TikTokProvider(headless=headless, debug=debug)
    elif platform == "reddit":
        from app.platforms.reddit.provider import RedditProvider
        return RedditProvider(debug=debug)
    elif platform == "facebook":
        from app.platforms.facebook.provider import FacebookProvider
        return FacebookProvider(headless=headless, debug=debug)
    else:
        raise UnsupportedPlatformError(f"Pas de provider pour la plateforme : {platform!r}")
