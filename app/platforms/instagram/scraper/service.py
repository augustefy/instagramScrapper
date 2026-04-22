"""
Service scraper Instagram : wrapper autour du scraper Playwright existant.
Convertit les resultats en FetchPostsResult.
"""

from app.core.health import HEALTHY, UNHEALTHY, DataSourceHealth
from app.core.exceptions import ScraperError
from app.core.log import get_logger
from app.core.models import FetchPostsResult
from bench import Bench

logger = get_logger(__name__)

# ── URL de base pour reconstruire les profils a scraper. ──
_BASE_URL = "https://www.instagram.com"


# ── Qualification de l echec scraper pour le healthcheck. ──
def _scraper_failure_details(exc: Exception, *, headless: bool) -> tuple[str, dict]:
    raw_message = str(exc)
    normalized = raw_message.lower()
    details = {
        "headless": headless,
        "target_url": _BASE_URL,
        "raw_error": raw_message,
    }

    if "no module named 'playwright'" in normalized:
        details["remediation"] = [
            "Installe les dependances Python du projet",
            "Puis lance: python3 -m playwright install chromium",
        ]
        return "Scraper Instagram indisponible: module Playwright absent.", details

    if "playwright was just installed or updated" in normalized:
        details["remediation"] = [
            "Telecharge les navigateurs Playwright",
            "Commande: python3 -m playwright install chromium",
        ]
        return "Scraper Instagram indisponible: navigateurs Playwright non installes.", details

    if "executable doesn't exist" in normalized:
        details["remediation"] = [
            "Le binaire du navigateur Playwright est introuvable",
            "Commande: python3 -m playwright install chromium",
        ]
        return "Scraper Instagram indisponible: binaire Chromium manquant.", details

    return f"Scraper Instagram indisponible: {exc}", details


# ── Facade de collecte Instagram via Playwright. ──
class InstagramScraperService:
    """Wrapper autour du scraper Instagram existant (scrapers.instagram)."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._scraper = None

    def _get_scraper(self):
        if self._scraper is None:
            from scrapers.instagram.scraper import InstagramScraper

            # Instanciation differee pour eviter le cout navigateur hors besoin.
            self._scraper = InstagramScraper(headless=self._headless, bench=Bench())
        return self._scraper

    def health_check(self) -> DataSourceHealth:
        try:
            # Probe court: verifier que Playwright peut ouvrir Instagram.
            scraper = self._get_scraper()
            details = scraper.health_check()
            return DataSourceHealth(
                source="scraper",
                status=HEALTHY,
                message="Scraper Instagram pret.",
                details=details,
            )
        except Exception as exc:
            logger.exception("Health check scraper Instagram en echec")
            message, details = _scraper_failure_details(exc, headless=self._headless)
            return DataSourceHealth(
                source="scraper",
                status=UNHEALTHY,
                message=message,
                details=details,
            )

    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        """Scrape les posts d'un profil Instagram.

        Args:
            username: Username Instagram (sans @)
            limit: Nombre de posts a recuperer

        Returns:
            FetchPostsResult avec source="scraper"

        Raises:
            ScraperError: Si le scraping echoue
        """
        # 1) Reconstruire une URL de profil canonique pour le scraper legacy.
        url = f"{_BASE_URL}/{username}/"
        logger.info(f"Scraping Instagram pour @{username} (limit={limit})")

        try:
            # 2) Deleguer la collecte brute au pipeline Playwright.
            scraper = self._get_scraper()
            posts = scraper.scrape(url, limit)
        except Exception as e:
            logger.exception(
                "Scraping Instagram inattendu",
                extra={"username": username, "limit": limit},
            )
            raise ScraperError(f"Echec du scraping Instagram pour @{username}: {e}") from e

        logger.info(f"Scraper Instagram: {len(posts)} post(s) recuperes pour @{username}")

        # 3) Reprojeter la sortie vers le contrat commun des providers.
        return FetchPostsResult(
            posts=posts,
            source="scraper",
            platform="instagram",
            username=username,
        )

    def close(self) -> None:
        if self._scraper is not None:
            # Liberer explicitement les ressources navigateur si elles existent.
            self._scraper.close()
            self._scraper = None
