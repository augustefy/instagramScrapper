"""
Re-export des erreurs partagees par le projet.
"""

from app.core.exceptions import (
    ApiError,
    ApiPermissionError,
    ApiRateLimitError,
    ApiUnavailableError,
    EmptyResponseError,
    InvalidLimitError,
    InvalidResponseError,
    InvalidUrlError,
    ProtectedProfileError,
    ScraperError,
    UnsupportedPlatformError,
    UserNotFoundError,
)

__all__ = [
    "ApiError",
    "ApiPermissionError",
    "ApiRateLimitError",
    "ApiUnavailableError",
    "EmptyResponseError",
    "InvalidLimitError",
    "InvalidResponseError",
    "InvalidUrlError",
    "ProtectedProfileError",
    "ScraperError",
    "UnsupportedPlatformError",
    "UserNotFoundError",
]
