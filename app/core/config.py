"""
Configuration centralisee chargee depuis les variables d'environnement / .env.
"""

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

# ── Charger le .env du projet sans imposer python-dotenv. ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


@dataclass(frozen=True)
# ── Parametres minimaux pour l API Instagram Graph. ──
class InstagramApiConfig:
    user_long_token: str
    app_id: str
    ig_user_id: str
    id_page: str
    graph_api_base: str = "https://graph.facebook.com/v25.0"

    @property
    def is_configured(self) -> bool:
        return all([self.user_long_token, self.ig_user_id])


# ── Chargement tolerant de la configuration Instagram. ──
def load_instagram_api_config() -> InstagramApiConfig:
    return InstagramApiConfig(
        user_long_token=os.getenv("USER_LONG_TOKEN", ""),
        app_id=os.getenv("APP_ID", ""),
        ig_user_id=os.getenv("IG_USER_ID", ""),
        id_page=os.getenv("ID_PAGE", ""),
    )


@dataclass(frozen=True)
# ── Parametres minimaux pour l API Facebook Graph. ──
class FacebookApiConfig:
    page_id: str
    access_token: str
    graph_api_base: str = "https://graph.facebook.com/v25.0"

    @property
    def is_configured(self) -> bool:
        return all([self.page_id, self.access_token])


# ── Chargement tolerant de la configuration Facebook. ──
def load_facebook_api_config() -> FacebookApiConfig:
    return FacebookApiConfig(
        page_id=os.getenv("FB_PAGE_ID", ""),
        access_token=os.getenv("FB_ACCESS_TOKEN", ""),
    )
