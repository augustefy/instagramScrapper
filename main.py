"""
Point d'entree CLI du scraper multi-plateforme.

Usage :
    python main.py <url> <n> [--debug] [--no-headless] [--output fichier.json]
    python main.py --health [--debug] [--no-headless] [--output fichier.json]

Exemples :
    python main.py https://www.instagram.com/cristiano/ 10 --debug
    python main.py https://www.tiktok.com/@khaby.lame 10
    python main.py https://x.com/elonmusk 10
    python main.py https://www.reddit.com/user/Terracid/ 10
"""

import json
import logging
import sys

from app.cli.args import parse_args
from app.core.exceptions import InvalidLimitError
from app.core.health import HEALTHY
from app.services.health import check_data_sources
from app.services.social_resolver import fetch_profile_posts
from app.core.log import setup_logging


_ANSI_RESET = "\033[0m"
_ANSI_GREEN = "\033[32m"
_ANSI_RED = "\033[31m"
_ANSI_YELLOW = "\033[33m"


# ── Serialisation finale et sortie console. ──
def _dump_payload(payload: dict, output: str | None, label: str, logger: logging.Logger) -> None:
    if output:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(f"Sauvegarde dans {output}")

    print("\n" + "=" * 60)
    print(f"OUTPUT JSON ({label}):")
    print("=" * 60)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("=" * 60)


# ── Journalisation detaillee du rapport de sante. ──
def _log_health_report(report, logger: logging.Logger) -> None:
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Health     : {report.status.upper()}")
    logger.info(f"Checked at : {report.checked_at}")
    logger.info("=" * 60)

    for platform in report.platforms:
        logger.info(f"[{platform.platform}] {platform.status.upper()}")
        for source in platform.sources:
            logger.info(
                f"  - {source.source:<8} {source.status.upper():<14} {source.message}"
            )


# ── Construction des lignes de synthese compactes. ──
def _format_health_summary_lines(report) -> list[str]:
    use_color = sys.stdout.isatty()
    lines = []

    for platform in report.platforms:
        for source in platform.sources:
            status_label = _display_source_status(source.status)
            padded_status_label = f"{status_label:<2}"
            status_text = _colorize_status(padded_status_label, source.status, use_color)
            source_label = source.source.capitalize()
            platform_label = platform.platform.capitalize()
            lines.append(
                f"|| {status_text} || {source_label:<9} || {platform_label:<10} ||"
            )

    return lines


# ── Normalisation du statut pour affichage court. ──
def _display_source_status(status: str) -> str:
    return "OK" if status == HEALTHY else "KO"


# ── Coloration conditionnelle reservee au terminal interactif. ──
def _colorize_status(label: str, status: str, use_color: bool) -> str:
    if not use_color:
        return label

    if status == HEALTHY:
        color = _ANSI_GREEN
    elif status == "not_configured":
        color = _ANSI_YELLOW
    else:
        color = _ANSI_RED

    return f"{color}{label}{_ANSI_RESET}"


# ── Emission de la synthese lisible en fin de controle. ──
def _print_health_summary(report) -> None:
    print("\nSynthese :")
    for line in _format_health_summary_lines(report):
        print(line)


# ── Orchestration CLI: mode health ou collecte des posts. ──
def main() -> None:
    args = parse_args()

    # 1) Initialiser le niveau de logs CLI.
    level = logging.DEBUG if args.debug else logging.INFO
    logger = setup_logging("main", level=level)

    # 2) Aligner tous les loggers en DEBUG pour garder une trace complete.
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        for name in logging.Logger.manager.loggerDict:
            lg = logging.getLogger(name)
            lg.setLevel(logging.DEBUG)
            for handler in lg.handlers:
                handler.setLevel(logging.DEBUG)
        logger.info("Mode DEBUG active")

    try:
        if args.setup_tiktok_session:
            from scrapers.tiktok import TikTokScraper
            scraper = TikTokScraper(headless=False)
            session_path = scraper.setup_session(wait_seconds=60)
            logger.info(f"Session TikTok prête : {session_path}")
            logger.info("Vous pouvez maintenant lancer le scraper normalement.")
            return

        if args.health:
            report = check_data_sources(
                headless=not args.no_headless,
                debug=args.debug,
            )
            payload = report.to_dict()
            _log_health_report(report, logger)
            _dump_payload(payload, args.output, "HEALTH", logger)
            _print_health_summary(report)
            if report.status == "unhealthy":
                sys.exit(1)
            return

        if not args.url or args.n is None:
            raise InvalidLimitError(
                "L'URL et le nombre de posts sont obligatoires sauf avec --health."
            )

        if args.n <= 0:
            raise InvalidLimitError("Le nombre de posts doit etre un entier positif.")

        logger.info("=" * 60)
        logger.info(f"URL       : {args.url}")
        logger.info(f"Posts     : {args.n}")
        logger.info(f"Headless  : {not args.no_headless}")
        logger.info("=" * 60)

        result = fetch_profile_posts(
            url=args.url,
            limit=args.n,
            headless=not args.no_headless,
            debug=args.debug,
        )
        payload = result.to_dict()
    except Exception as e:
        if args.debug:
            logger.exception(f"Erreur fatale : {e}")
        else:
            logger.error(f"Erreur fatale : {e}")
        sys.exit(1)

    # 3) Journaliser un resume lisible avant export JSON.
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Resultats : {len(result.posts)} post(s) via {result.source.upper()}")
    logger.info(f"Plateforme: {result.platform}")
    logger.info(f"Username  : @{result.username}")
    logger.info("=" * 60)

    for i, post in enumerate(payload["posts"], 1):
        preview = post.get("text") or post.get("description") or post.get("title") or ""
        preview = (preview[:80] + "...") if len(preview) > 80 else preview

        logger.info(f"[{i}] {post.get('post_url') or post.get('url')}")
        logger.info(f"     Type       : {post.get('type')}")
        logger.info(f"     Created at : {post.get('created_at') or post.get('created_utc')}")
        logger.info(
            "     Likes: %s | Replies: %s | Reposts: %s | Views: %s",
            post.get("like_count", post.get("score")),
            post.get("reply_count", post.get("num_comments")),
            post.get("repost_count"),
            post.get("view_count"),
        )
        if post.get("subreddit"):
            logger.info(f"     Subreddit  : {post.get('subreddit')}")
        logger.info(f"     Preview    : {preview}")

    # 4) Exporter puis afficher la charge utile finale.
    _dump_payload(payload, args.output, result.source.upper(), logger)


if __name__ == "__main__":
    main()
