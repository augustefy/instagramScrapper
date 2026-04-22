"""
Service d'agregation des checks de sante des sources de donnees.
"""

from app.core.health import DataSourceHealth, HealthReport, PlatformHealth, UNHEALTHY
from app.platforms.registry import get_provider, list_supported_platforms
from app.core.log import get_logger

logger = get_logger(__name__)


# ── Aggregation de l etat de sante sur toutes les plateformes. ──
def check_data_sources(headless: bool = True, debug: bool = False) -> HealthReport:
    platforms: list[PlatformHealth] = []

    # 1) Evaluer chaque provider dans des conditions homogenes.
    for platform_name in list_supported_platforms():
        provider = None
        try:
            provider = get_provider(platform_name, headless=headless, debug=debug)
            platforms.append(provider.health_check())
        except Exception as exc:
            # Important: un provider en echec ne doit pas masquer l'etat global.
            logger.exception(
                "Echec du health check provider",
                extra={"platform": platform_name},
            )
            platforms.append(
                PlatformHealth(
                    platform=platform_name,
                    status=UNHEALTHY,
                    sources=[
                        DataSourceHealth(
                            source="provider",
                            status=UNHEALTHY,
                            message=f"Initialisation provider impossible: {exc}",
                        )
                    ],
                )
            )
        finally:
            if provider is not None:
                provider.close()

    # 2) Consolider la vue systeme a partir des resultats plateforme.
    return HealthReport(platforms=platforms)
