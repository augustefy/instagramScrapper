"""
Modeles et helpers pour les rapports de sante des sources de donnees.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


HEALTHY = "healthy"
DEGRADED = "degraded"
UNHEALTHY = "unhealthy"
NOT_CONFIGURED = "not_configured"


@dataclass
# ── Etat de sante unitaire d une source. ──
class DataSourceHealth:
    source: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
# ── Aggregation source par plateforme. ──
class PlatformHealth:
    platform: str
    sources: list[DataSourceHealth]
    status: str = ""

    def __post_init__(self) -> None:
        if not self.status:
            # Deriver le statut plateforme si l appelant ne l impose pas.
            self.status = derive_aggregate_status(source.status for source in self.sources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "status": self.status,
            "sources": [source.to_dict() for source in self.sources],
        }


@dataclass
# ── Vue globale du systeme de collecte. ──
class HealthReport:
    platforms: list[PlatformHealth]
    status: str = ""
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        if not self.status:
            # Deriver le statut global a partir des plateformes enfants.
            self.status = derive_aggregate_status(
                platform.status for platform in self.platforms
            )

    @property
    def summary(self) -> dict[str, dict[str, int]]:
        # Compter separement les plateformes et les sources pour le reporting CLI.
        return {
            "platforms": _count_statuses(platform.status for platform in self.platforms),
            "sources": _count_statuses(
                source.status
                for platform in self.platforms
                for source in platform.sources
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checked_at": self.checked_at,
            "summary": self.summary,
            "platforms": [platform.to_dict() for platform in self.platforms],
        }


# ── Reduction de plusieurs statuts vers un statut unique. ──
def derive_aggregate_status(statuses: Iterable[str]) -> str:
    # Normaliser les statuts vides vers unhealthy pour eviter les faux positifs.
    normalized = [status or UNHEALTHY for status in statuses]

    # Healthy uniquement si tout est strictement disponible.
    if normalized and all(status == HEALTHY for status in normalized):
        return HEALTHY

    # Degraded des qu une voie reste exploitable.
    if any(status in {HEALTHY, DEGRADED} for status in normalized):
        return DEGRADED

    # Unhealthy si aucune source n est exploitable.
    return UNHEALTHY


# ── Comptage technique pour la synthese finale. ──
def _count_statuses(statuses: Iterable[str]) -> dict[str, int]:
    counts = {
        HEALTHY: 0,
        DEGRADED: 0,
        UNHEALTHY: 0,
        NOT_CONFIGURED: 0,
    }
    for status in statuses:
        # Conserver aussi les statuts non prevus pour diagnostic futur.
        counts.setdefault(status, 0)
        counts[status] += 1
    return counts
