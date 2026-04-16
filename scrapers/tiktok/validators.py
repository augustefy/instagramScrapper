from urllib.parse import urlparse

from exceptions import ValidationError


def validate_tiktok_url(url: str) -> str:
    if not isinstance(url, str):
        raise ValidationError(f"URL doit être une string, pas {type(url).__name__}")

    url = url.strip()
    if not url:
        raise ValidationError("URL vide")

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValidationError(f"URL invalide : {e}")

    if parsed.netloc not in ("tiktok.com", "www.tiktok.com"):
        raise ValidationError(f"URL doit être sur tiktok.com, pas {parsed.netloc}")

    if not parsed.path or parsed.path == "/":
        raise ValidationError("URL TikTok doit inclure un nom d'utilisateur (ex: tiktok.com/@username)")

    if parsed.netloc == "tiktok.com":
        url = f"https://www.tiktok.com{parsed.path}"

    return url


def validate_post_count(n: int) -> int:
    if not isinstance(n, int):
        raise ValidationError(f"Nombre de posts doit être un int, pas {type(n).__name__}")
    if n < 1:
        raise ValidationError(f"Nombre de posts doit être >= 1, pas {n}")
    if n > 10000:
        raise ValidationError(f"Nombre de posts trop grand ({n}).")
    return n
