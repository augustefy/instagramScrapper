"""
Parsing et normalisation des URLs Instagram.
"""

from urllib.parse import urlparse


# ── Extraction defensive du username Instagram. ──
def extract_username(url: str) -> str:
    """Extrait le username depuis une URL Instagram.

    Exemples:
        https://www.instagram.com/cristiano/ -> cristiano
        https://instagram.com/cristiano      -> cristiano
        https://www.instagram.com/cristiano/p/xxx -> cristiano

    Returns:
        Username normalise (sans @, sans slash)
    """
    path = urlparse(url).path.strip("/")
    # Le premier segment est toujours le username
    username = path.split("/")[0].lstrip("@")
    return username


# ── Reconstruction d une URL de profil canonique. ──
def build_profile_url(username: str) -> str:
    """Construit l'URL du profil a partir du username."""
    return f"https://www.instagram.com/{username}/"
