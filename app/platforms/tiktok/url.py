"""
Parsing et normalisation des URLs TikTok.
"""

from urllib.parse import urlparse


def extract_username(url: str) -> str:
    """Extrait le username depuis une URL TikTok.

    Exemples:
        https://www.tiktok.com/@khaby.lame   -> khaby.lame
        https://tiktok.com/@khaby.lame/      -> khaby.lame
    """
    path = urlparse(url).path.strip("/")
    username = path.split("/")[0].lstrip("@")
    return username
