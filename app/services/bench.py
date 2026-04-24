"""
Benchmark des voies de collecte.

Pour chaque couple (plateforme, source) reel du projet, ce module expose
un runner isole qui execute un fetch_posts (API, scraper ou guest API) et
renvoie duree + nombre de posts + statut. Le resultat structure sert :
    - au CLI `main.py --health [N]` pour afficher un tableau Up? / Type /
      Plateforme / temps d'execution
    - au script `bench_services.py` pour agreger plusieurs iterations
"""

from __future__ import annotations

import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable

from app.core.log import get_logger

logger = get_logger(__name__)


# ── Defauts par plateforme (cibles stables et publiques). ─────────────
DEFAULT_USERNAMES: dict[str, str] = {
    "facebook": "facebook",
    "instagram": "instagram",
    "reddit": "spez",
    "tiktok": "gotaga",
    "twitter": "OpenAI",
}

DEFAULT_BENCH_LIMIT = 10


# ── Specification d un service benchmarke. ────────────────────────────
@dataclass
class ServiceSpec:
    key: str                  # identifiant stable (ex: "instagram_api")
    source: str               # identifiant source (ex: "api", "scraper", "guest_api")
    source_label: str         # libelle affichage (ex: "Api")
    platform: str             # identifiant plateforme (ex: "instagram")
    platform_label: str       # libelle affichage (ex: "Instagram")
    runner: Callable[["ServiceContext"], "RunOutcome"]


# ── Contexte passe au runner pour un run donne. ───────────────────────
@dataclass
class ServiceContext:
    username: str
    limit: int
    headless: bool
    debug: bool


# ── Resultat brut d un runner (avant scoring). ────────────────────────
@dataclass
class RunOutcome:
    posts_count: int
    source: str


# ── Resultat d un benchmark unitaire (service x contexte). ────────────
@dataclass
class ServiceBenchResult:
    key: str
    source: str
    source_label: str
    platform: str
    platform_label: str
    ok: bool
    duration_s: float
    posts_count: int
    expected: int
    username: str
    returned_source: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── Rapport global retourne par le bench. ─────────────────────────────
@dataclass
class BenchReport:
    limit: int
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    services: list[ServiceBenchResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "limit": self.limit,
            "checked_at": self.checked_at,
            "services": [s.to_dict() for s in self.services],
        }


# ── Runners par service. ──────────────────────────────────────────────
def _run_facebook_api(ctx: ServiceContext) -> RunOutcome:
    from app.platforms.facebook.provider import FacebookProvider

    provider = FacebookProvider(headless=ctx.headless, debug=ctx.debug)
    try:
        result = provider.fetch_posts(ctx.username, ctx.limit)
        return RunOutcome(posts_count=len(result.posts), source=result.source)
    finally:
        provider.close()


def _run_instagram_api(ctx: ServiceContext) -> RunOutcome:
    from app.platforms.instagram.api.service import InstagramApiService

    service = InstagramApiService()
    if not service.is_available:
        # Important: signaler clairement la config absente au lieu d un 500.
        raise RuntimeError(
            "API Instagram non configuree (USER_LONG_TOKEN / IG_USER_ID)."
        )
    result = service.fetch_posts(ctx.username, ctx.limit)
    return RunOutcome(posts_count=len(result.posts), source=result.source)


def _run_instagram_scraper(ctx: ServiceContext) -> RunOutcome:
    from app.platforms.instagram.scraper.service import InstagramScraperService

    service = InstagramScraperService(headless=ctx.headless)
    try:
        result = service.fetch_posts(ctx.username, ctx.limit)
        return RunOutcome(posts_count=len(result.posts), source=result.source)
    finally:
        service.close()


def _run_reddit_api(ctx: ServiceContext) -> RunOutcome:
    from app.platforms.reddit.api.service import RedditApiService

    service = RedditApiService(debug=ctx.debug)
    try:
        result = service.fetch_profile_posts(ctx.username, ctx.limit)
        return RunOutcome(posts_count=len(result.posts), source=result.source)
    finally:
        service.close()


def _run_tiktok_scraper(ctx: ServiceContext) -> RunOutcome:
    from app.platforms.tiktok.provider import TikTokProvider

    provider = TikTokProvider(headless=ctx.headless, debug=ctx.debug)
    try:
        result = provider.fetch_posts(ctx.username, ctx.limit)
        return RunOutcome(posts_count=len(result.posts), source=result.source)
    finally:
        provider.close()


def _run_twitter_guest_api(ctx: ServiceContext) -> RunOutcome:
    from app.platforms.twitter.provider import TwitterProvider

    provider = TwitterProvider(debug=ctx.debug)
    try:
        result = provider.fetch_posts(ctx.username, ctx.limit)
        return RunOutcome(posts_count=len(result.posts), source=result.source)
    finally:
        provider.close()


SERVICE_SPECS: list[ServiceSpec] = [
    ServiceSpec(
        key="facebook_api",
        source="api",
        source_label="Api",
        platform="facebook",
        platform_label="Facebook",
        runner=_run_facebook_api,
    ),
    ServiceSpec(
        key="instagram_api",
        source="api",
        source_label="Api",
        platform="instagram",
        platform_label="Instagram",
        runner=_run_instagram_api,
    ),
    ServiceSpec(
        key="instagram_scraper",
        source="scraper",
        source_label="Scraper",
        platform="instagram",
        platform_label="Instagram",
        runner=_run_instagram_scraper,
    ),
    ServiceSpec(
        key="reddit_api",
        source="api",
        source_label="Api",
        platform="reddit",
        platform_label="Reddit",
        runner=_run_reddit_api,
    ),
    ServiceSpec(
        key="tiktok_scraper",
        source="scraper",
        source_label="Scraper",
        platform="tiktok",
        platform_label="Tiktok",
        runner=_run_tiktok_scraper,
    ),
    ServiceSpec(
        key="twitter_guest_api",
        source="guest_api",
        source_label="Guest_api",
        platform="twitter",
        platform_label="Twitter",
        runner=_run_twitter_guest_api,
    ),
]


# ── Execution d un run unique + capture d echec. ──────────────────────
def run_service(
    spec: ServiceSpec,
    ctx: ServiceContext,
    expected: int,
) -> ServiceBenchResult:
    t0 = time.perf_counter()
    try:
        outcome = spec.runner(ctx)
        duration = time.perf_counter() - t0
        # Critere de succes : nb de posts retournes >= attendu.
        ok = outcome.posts_count >= expected
        message = (
            ""
            if ok
            else f"posts={outcome.posts_count} (attendu >= {expected})"
        )
        return ServiceBenchResult(
            key=spec.key,
            source=spec.source,
            source_label=spec.source_label,
            platform=spec.platform,
            platform_label=spec.platform_label,
            ok=ok,
            duration_s=round(duration, 2),
            posts_count=outcome.posts_count,
            expected=expected,
            username=ctx.username,
            returned_source=outcome.source,
            message=message,
        )
    except Exception as exc:  # noqa: BLE001 — on veut capturer tout echec
        duration = time.perf_counter() - t0
        tb_tail = traceback.format_exception_only(type(exc), exc)[-1].strip()
        logger.exception(
            "Benchmark service en echec",
            extra={"service": spec.key, "username": ctx.username},
        )
        return ServiceBenchResult(
            key=spec.key,
            source=spec.source,
            source_label=spec.source_label,
            platform=spec.platform,
            platform_label=spec.platform_label,
            ok=False,
            duration_s=round(duration, 2),
            posts_count=0,
            expected=expected,
            username=ctx.username,
            returned_source="",
            message=tb_tail[:200],
        )


# ── Benchmark complet des voies de collecte. ──────────────────────────
def benchmark_data_sources(
    limit: int = DEFAULT_BENCH_LIMIT,
    *,
    headless: bool = True,
    debug: bool = False,
    usernames: dict[str, str] | None = None,
    expect: int | None = None,
    specs: list[ServiceSpec] | None = None,
) -> BenchReport:
    """Lance un fetch_posts chronometre pour chaque voie de collecte.

    Args:
        limit: nombre de posts demandes par appel.
        headless: mode headless pour les scrapers.
        debug: active le mode debug des services.
        usernames: overrides par plateforme (cle = platform id).
        expect: seuil minimum de posts pour considerer un run reussi
            (defaut = limit).
        specs: sous-ensemble de services a benchmarker (defaut: tous).

    Returns:
        BenchReport agrege, 1 entree par service dans l ordre de SERVICE_SPECS.
    """
    effective_specs = list(specs) if specs is not None else list(SERVICE_SPECS)
    expected = expect if expect is not None else limit
    overrides = usernames or {}

    report = BenchReport(limit=limit)

    for spec in effective_specs:
        username = overrides.get(spec.platform) or DEFAULT_USERNAMES.get(
            spec.platform, spec.platform
        )
        ctx = ServiceContext(
            username=username,
            limit=limit,
            headless=headless,
            debug=debug,
        )
        logger.info(
            f"Bench {spec.key} (limit={limit}, @{username})",
            extra={"service": spec.key, "limit": limit, "username": username},
        )
        result = run_service(spec=spec, ctx=ctx, expected=expected)
        report.services.append(result)

    return report


def resolve_specs(
    only: list[str] | None = None,
    skip: list[str] | None = None,
) -> list[ServiceSpec]:
    """Filtre les specs par cle, avec garde-fou sur les cles inconnues."""
    keys = {s.key for s in SERVICE_SPECS}
    if only:
        unknown = set(only) - keys
        if unknown:
            raise ValueError(
                f"Cles inconnues : {sorted(unknown)}. Valides : {sorted(keys)}"
            )
        return [s for s in SERVICE_SPECS if s.key in set(only)]
    if skip:
        unknown = set(skip) - keys
        if unknown:
            raise ValueError(
                f"Cles inconnues : {sorted(unknown)}. Valides : {sorted(keys)}"
            )
        return [s for s in SERVICE_SPECS if s.key not in set(skip)]
    return list(SERVICE_SPECS)
