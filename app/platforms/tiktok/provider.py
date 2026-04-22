"""
Provider TikTok : wrapper autour du scraper TikTok existant.
Pas d'API officielle pour l'instant, donc scraper uniquement.
"""

from app.core.health import HEALTHY, UNHEALTHY, DataSourceHealth, PlatformHealth
from app.core.exceptions import ScraperError
from app.core.log import get_logger
from app.core.models import FetchPostsResult
from app.platforms.base.provider import DegradationStrategy, PlatformProvider
from bench import Bench

logger = get_logger(__name__)

_BASE_URL = "https://www.tiktok.com"


# ── Qualification de l echec scraper pour TikTok. ──
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
            "Puis lance: python3 -m playwright install chromium firefox",
        ]
        return "Scraper TikTok indisponible: module Playwright absent.", details

    if "playwright was just installed or updated" in normalized:
        details["remediation"] = [
            "Telecharge les navigateurs Playwright",
            "Commande: python3 -m playwright install chromium firefox",
        ]
        return "Scraper TikTok indisponible: navigateurs Playwright non installes.", details

    if "executable doesn't exist" in normalized:
        details["remediation"] = [
            "Le binaire d'un navigateur Playwright est introuvable",
            "Commande: python3 -m playwright install chromium firefox",
        ]
        return "Scraper TikTok indisponible: navigateur Playwright manquant.", details

    return f"Scraper TikTok indisponible: {exc}", details


# ── Provider TikTok base sur le scraper navigateur. ──
class TikTokProvider(PlatformProvider):
    """Provider TikTok (scraper uniquement pour l'instant)."""

    def __init__(self, headless: bool = True, debug: bool = False) -> None:
        self._headless = headless
        self._debug = debug
        self._scraper = None

    @property
    def platform_name(self) -> str:
        return "tiktok"

    @property
    def degradation_strategy(self) -> DegradationStrategy:
        return DegradationStrategy(
            primary_source="scraper",
            note="Scraper navigateur uniquement; aucune API de secours n'est configuree.",
        )

    def health_check(self) -> PlatformHealth:
        # TikTok n expose qu une seule source: le scraper navigateur.
        return PlatformHealth(
            platform=self.platform_name,
            sources=[self._scraper_health_check()],
        )

    def _get_scraper(self):
        if self._scraper is None:
            from scrapers.tiktok.botasaurus_scraper import BotasaurusTikTokScraper
            self._scraper = BotasaurusTikTokScraper(headless=self._headless, bench=Bench())
        return self._scraper

    def _scraper_health_check(self) -> DataSourceHealth:
        try:
            # Reutiliser le vrai scraper pour sonder Playwright et la page d accueil.
            scraper = self._get_scraper()
            details = scraper.health_check()
            return DataSourceHealth(
                source="scraper",
                status=HEALTHY,
                message="Scraper TikTok pret.",
                details=details,
            )
        except Exception as exc:
            logger.exception("Health check scraper TikTok en echec")
            message, details = _scraper_failure_details(exc, headless=self._headless)
            return DataSourceHealth(
                source="scraper",
                status=UNHEALTHY,
                message=message,
                details=details,
            )

    def fetch_posts(self, username: str, limit: int) -> FetchPostsResult:
        """Scrape les posts TikTok."""
        # 1) Recomposer l URL publique attendue par le scraper.
        url = f"{_BASE_URL}/@{username}"
        logger.info(f"[TikTok] Scraping de @{username} (limit={limit})")

        try:
            # 2) Deleguer la collecte brute au navigateur.
            scraper = self._get_scraper()
            posts = scraper.scrape(url, limit)
        except Exception as e:
            logger.exception(
                "Scraping TikTok inattendu",
                extra={"username": username, "limit": limit},
            )
            raise ScraperError(f"Echec du scraping TikTok pour @{username}: {e}") from e

        logger.info(f"[TikTok] {len(posts)} post(s) recuperes")

        # 3) Encapsuler la sortie dans le format commun des providers.
        return FetchPostsResult(
            posts=posts,
            source="scraper",
            platform="tiktok",
            username=username,
        )

    def close(self) -> None:
        if self._scraper is not None:
            # Fermer le navigateur uniquement s il a ete instancie.
            self._scraper.close()
            self._scraper = None
