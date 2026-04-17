"""
Configuration centralisee chargee depuis les variables d'environnement / .env.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Charge le .env a la racine du projet
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class InstagramApiConfig:
    user_long_token: str
    app_id: str
    ig_user_id: str
    id_page: str
    graph_api_base: str = "https://graph.facebook.com/v25.0"

    @property
    def is_configured(self) -> bool:
        return all([self.user_long_token, self.ig_user_id])


def load_instagram_api_config() -> InstagramApiConfig:
    return InstagramApiConfig(
        user_long_token=os.getenv("USER_LONG_TOKEN", ""),
        app_id=os.getenv("APP_ID", ""),
        ig_user_id=os.getenv("IG_USER_ID", ""),
        id_page=os.getenv("ID_PAGE", ""),
    )
