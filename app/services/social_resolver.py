"""
Service haut niveau : resout une URL de profil social en posts.
Detecte la plateforme, extrait le username, instancie le provider, et recupere les posts.
"""

from app.core.models import FetchPostsResult
from app.platforms.registry import detect_platform, extract_username, get_provider
from logging_setup import setup_logging

logger = setup_logging(__name__)


def fetch_profile_posts(
    url: str,
    limit: int,
    headless: bool = True,
    debug: bool = False,
) -> FetchPostsResult:
    """Point d'entree principal : recupere les posts d'un profil social.

    Args:
        url: URL du profil (Instagram, TikTok, ...)
        limit: Nombre de posts a recuperer
        headless: Mode headless pour le navigateur
        debug: Active les logs debug

    Returns:
        FetchPostsResult avec les posts, la source, et les metadonnees
    """
    # 1. Detection de la plateforme
    platform = detect_platform(url)
    logger.info(f"Plateforme detectee : {platform}")

    # 2. Extraction du username
    username = extract_username(url, platform)
    logger.info(f"Username extrait : @{username}")

    # 3. Instanciation du provider
    provider = get_provider(platform, headless=headless, debug=debug)

    try:
        # 4. Recuperation des posts
        result = provider.fetch_posts(username, limit)

        logger.info(
            f"Resultat : {len(result.posts)} post(s) via {result.source}",
            extra={"platform": platform, "username": username, "source": result.source},
        )

        return result

    finally:
        provider.close()
