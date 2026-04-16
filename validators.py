"""
Validators pour l'entrée utilisateur.
Évite les erreurs stupides en amont.
"""

from urllib.parse import urlparse

from exceptions import ValidationError


def validate_instagram_url(url: str) -> str:
    """Valide et normalise une URL Instagram.

    Args:
        url: URL à valider

    Returns:
        URL normalisée

    Raises:
        ValidationError: Si l'URL n'est pas une URL Instagram valide
    """
    if not isinstance(url, str):
        raise ValidationError(f"URL doit être une string, pas {type(url).__name__}")

    url = url.strip()
    if not url:
        raise ValidationError("URL vide")

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValidationError(f"URL invalide : {e}")

    # Accepte https://instagram.com/username ou https://www.instagram.com/username
    if parsed.netloc not in ("instagram.com", "www.instagram.com"):
        raise ValidationError(
            f"URL doit être sur instagram.com, pas {parsed.netloc}"
        )

    if not parsed.path or parsed.path == "/":
        raise ValidationError(
            "URL Instagram doit inclure un nom d'utilisateur (ex: instagram.com/username)"
        )

    # Normalise https://instagram.com/foo → https://www.instagram.com/foo
    if parsed.netloc == "instagram.com":
        url = f"https://www.instagram.com{parsed.path}"

    return url


def validate_post_count(n: int) -> int:
    """Valide le nombre de posts à scraper.

    Args:
        n: Nombre de posts

    Returns:
        Nombre validé

    Raises:
        ValidationError: Si le nombre est invalide
    """
    if not isinstance(n, int):
        raise ValidationError(f"Nombre de posts doit être un int, pas {type(n).__name__}")

    if n < 1:
        raise ValidationError(f"Nombre de posts doit être >= 1, pas {n}")

    if n > 10000:
        raise ValidationError(
            f"Nombre de posts trop grand ({n}). "
            "Les profils Instagram n'ont généralement pas 10k+ posts accessibles."
        )

    return n
