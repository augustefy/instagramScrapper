"""
Tâches RQ exécutées dans le worker séparé.

Le worker est lancé avec :
    rq worker scrapes --url redis://localhost:6379/0

Cette fonction est sérialisée par chemin Python (worker.tasks.run_scrape_job),
elle doit donc rester importable depuis la racine du projet.
"""

from app.services.social_resolver import fetch_profile_posts


def run_health_check_job(limit: int = 10) -> dict:
    """Lance le health check complet + benchmark de toutes les plateformes.

    Équivalent de : python main.py --health <limit>

    Returns:
        dict avec clés "health" (HealthReport) et "bench" (BenchReport)
    """
    from app.services.health import check_data_sources
    from app.services.bench import benchmark_data_sources

    health_report = check_data_sources(headless=True, debug=False)
    bench_report = benchmark_data_sources(limit=limit, headless=True, debug=False)

    return {
        "health": health_report.to_dict(),
        "bench": bench_report.to_dict(),
    }


def run_scrape_job(url: str, limit: int) -> dict:
    """Récupère les posts d'un profil social.

    Exécuté dans le worker RQ — jamais dans le process FastAPI.
    Toutes les exceptions remontent naturellement vers RQ qui les capture et
    marque le job comme failed.

    Returns:
        dict sérialisable JSON issu de FetchPostsResult.to_dict()
    """
    result = fetch_profile_posts(url=url, limit=limit)
    return result.to_dict()
