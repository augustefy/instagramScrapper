"""
Handlers d'exceptions : mapping exceptions domaine → codes HTTP.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.core.exceptions import (
    ApiError,
    InvalidLimitError,
    InvalidUrlError,
    ProtectedProfileError,
    ScraperError,
    UnsupportedPlatformError,
    UserNotFoundError,
)


def _json(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return _json(429, "Rate limit exceeded")

    @app.exception_handler(UnsupportedPlatformError)
    async def _unsupported_platform(request: Request, exc: UnsupportedPlatformError) -> JSONResponse:
        return _json(422, str(exc))

    @app.exception_handler(InvalidUrlError)
    async def _invalid_url(request: Request, exc: InvalidUrlError) -> JSONResponse:
        return _json(422, str(exc))

    @app.exception_handler(InvalidLimitError)
    async def _invalid_limit(request: Request, exc: InvalidLimitError) -> JSONResponse:
        return _json(422, str(exc))

    @app.exception_handler(UserNotFoundError)
    async def _not_found(request: Request, exc: UserNotFoundError) -> JSONResponse:
        return _json(404, str(exc))

    @app.exception_handler(ProtectedProfileError)
    async def _protected(request: Request, exc: ProtectedProfileError) -> JSONResponse:
        return _json(403, str(exc))

    @app.exception_handler(ScraperError)
    async def _scraper_error(request: Request, exc: ScraperError) -> JSONResponse:
        return _json(502, str(exc))

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _json(502, str(exc))
