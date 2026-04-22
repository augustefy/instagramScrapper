"""
Parsing et normalisation des URLs Facebook.
"""

from urllib.parse import urlparse, parse_qs


# ── Extraction du slug ou de l identifiant Facebook. ──
def extract_username(url: str) -> str:
    """Extrait le nom de page / username depuis une URL Facebook.

    Exemples:
        https://www.facebook.com/cocacola       -> cocacola
        https://www.facebook.com/cocacola/       -> cocacola
        https://facebook.com/profile.php?id=123  -> 123
        https://www.facebook.com/p/PageName/     -> PageName
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    # /profile.php?id=123
    if path == "profile.php":
        qs = parse_qs(parsed.query)
        return qs.get("id", [""])[0]

    # /p/PageName ou /pages/category/PageName/ID
    segments = path.split("/")
    if segments[0] == "p" and len(segments) > 1:
        return segments[1]
    if segments[0] == "pages" and len(segments) >= 3:
        return segments[-1]

    # /cocacola
    return segments[0]
