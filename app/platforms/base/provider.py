"""
Interface abstraite pour un provider de plateforme sociale.
Chaque plateforme (Instagram, TikTok, ...) implemente cette interface.
"""

from abc import ABC, abstractmethod

from app.core.models import FetchPostsResult


class PlatformProvider(ABC):
    """Interface commune a tous les providers de plateforme."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        ...

    @abstractmethod
    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        """Recupere les posts d'un profil.

        Args:
            username: Nom d'utilisateur (sans @, sans URL)
            limit: Nombre de posts a recuperer

        Returns:
            FetchPostsResult avec les posts et la source utilisee
        """
        ...

    def close(self):
        """Libere les ressources (navigateur, etc.)."""
        pass
