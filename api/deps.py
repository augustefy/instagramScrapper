"""
Dépendances FastAPI : connexion Redis, authentification, rate limiting.
"""

import hashlib

import redis
from fastapi import Header, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from api.config import get_settings

settings = get_settings()


# ── Redis pool partagé, initialisé dans le lifespan de l'app. ──
def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis


# ── Clé de rate limit : API key si présente, IP sinon. ──
def _rate_limit_key(request: Request) -> str:
    key = request.headers.get("X-API-Key")
    return key or get_remote_address(request)


# Instance unique du limiteur (storage Redis pour cohérence multi-workers).
limiter = Limiter(
    key_func=_rate_limit_key,
    storage_uri=settings.redis_url,
)


# ── Auth via X-API-Key. Si aucune clé configurée, l'auth est désactivée. ──
async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    if not settings.auth_enabled:
        return "anonymous"

    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")

    hashed = hashlib.sha256(x_api_key.encode()).hexdigest()
    if hashed not in settings.valid_key_hashes:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return x_api_key
