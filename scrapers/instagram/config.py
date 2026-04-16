"""
Configuration centralisée pour le scraper Instagram.
Permet de modifier rapidement les paramètres sans toucher au code.
"""

from dataclasses import dataclass

# URLs
BASE_URL = "https://www.instagram.com"

# Ressources à bloquer (pour réduire la bande passante)
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}

# Performance
WORKERS = 10  # Nombre de tabs parallèles
MAX_RETRY_ATTEMPTS = 3

# Timeouts (en millisecondes)
TIMEOUT_PAGE_LOAD = 15000
TIMEOUT_POST_LOAD = 10000
TIMEOUT_POPUP_DISMISS = 2000
TIMEOUT_SCROLL = 4000

# Browser
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1280, "height": 900}

# Attentes et délais
POPUP_DISMISS_WAIT = 0.8  # secondes
SCROLL_POLL_INTERVAL = 0.2  # secondes
RESPONSE_HANDLER_WAIT = 0.5  # secondes - laisse le temps aux réponses XHR d'arriver (views, etc.)


@dataclass
class SelectorConfig:
    """Configuration des sélecteurs CSS et patterns.

    IMPORTANT: Ces sélecteurs changent quand Instagram modifie son HTML.
    Si le scraper échoue, vérifier ici en premier.
    """

    # Popup de cookies
    COOKIE_BUTTON = (
        "button:has-text('Allow all cookies'), "
        "button:has-text('Tout accepter'), "
        "button:has-text('Allow'), "
        "button:has-text('Autoriser'), "
        "button:has-text('Accept'), "
        "button:has-text('Decline optional cookies'), "
        "button:has-text('Refuser les cookies optionnels')"
    )

    # Popup de login
    LOGIN_BUTTON = "button:has-text('Not Now'), button:has-text('Plus tard')"

    # Timestamp du post
    POST_TIME = "time[datetime]"

    # Caption du post (FRAGILE - classes CSS Instagram changent souvent)
    # Fallback via API API fortement recommandé
    POST_CAPTION_SPAN = "span.x126k92a"

    # Meta description (fallback)
    POST_META_DESCRIPTION = "meta[property='og:description']"

    # Pattern regex pour identifier les posts (très robuste)
    POST_HREF_PATTERN = r"^\/(.+)\/(p|reel)\/[A-Za-z0-9_-]+"

    # SVG pin pour posts épinglés
    PINNED_SVG = "svg[aria-label*='pin'], svg[aria-label*='Pin']"


SELECTORS = SelectorConfig()
