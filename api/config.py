"""
Configuration de l'API chargée depuis les variables d'environnement.
Distinct de app/core/config.py qui gère les credentials des plateformes.
"""

import hashlib
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth — liste de clés brutes séparées par des virgules ; vide = auth désactivée
    api_keys: str = ""

    # Rate limiting
    rate_limit_per_minute: int = 60

    # Cache Redis (secondes)
    cache_ttl: int = 600

    # Jobs RQ
    job_timeout: int = 300
    job_result_ttl: int = 3600

    # Scraper
    scraper_headless: bool = True

    # Logs
    log_json: bool = True
    debug: bool = False

    @property
    def valid_key_hashes(self) -> set[str]:
        """SHA-256 des clés configurées — les clés brutes ne sont jamais comparées directement."""
        return {
            hashlib.sha256(k.strip().encode()).hexdigest()
            for k in self.api_keys.split(",")
            if k.strip()
        }

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
