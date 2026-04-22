"""
Interface abstraite pour un provider de plateforme sociale.
Chaque plateforme (Instagram, TikTok, ...) implemente cette interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.health import PlatformHealth
from app.core.models import FetchPostsResult


@dataclass(frozen=True)
class DegradationStrategy:
    """Decrit la source primaire et l'eventuel fallback d'une plateforme."""

    primary_source: str
    fallback_source: str | None = None
    note: str = ""

    @property
    def has_fallback(self) -> bool:
        return self.fallback_source is not None


# ── Contrat commun impose a chaque plateforme. ──
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

    @abstractmethod
    def health_check(self) -> PlatformHealth:
        """Retourne l'etat de sante des sources de donnees de la plateforme."""
        ...

    @property
    def degradation_strategy(self) -> DegradationStrategy:
        return DegradationStrategy(
            primary_source="provider",
            note="Aucun fallback declare pour ce provider.",
        )

    def close(self) -> None:
        """Libere les ressources (navigateur, etc.)."""
        pass
