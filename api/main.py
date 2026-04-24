"""
Factory de l'application FastAPI.

Usage :
    uvicorn api.main:app --reload
    gunicorn api.main:app -k uvicorn.workers.UvicornWorker -w 4
"""

import logging
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.config import get_settings
from api.deps import limiter
from api.errors import register_handlers
from api.routes import health, scrapes
from app.core.log import setup_logging

settings = get_settings()

setup_logging(
    "api",
    level=logging.DEBUG if settings.debug else logging.INFO,
    json_mode=settings.log_json,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)
    app.state.redis = redis.Redis(connection_pool=pool)
    yield
    pool.disconnect()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Social Scraper API",
        version="1.0.0",
        description=(
            "API de scraping multi-plateforme (Instagram, TikTok, Twitter/X, Reddit, Facebook). "
            "Les jobs de scraping sont exécutés de manière asynchrone via RQ."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    register_handlers(app)

    app.include_router(health.router)
    app.include_router(scrapes.router)

    return app


app = create_app()
