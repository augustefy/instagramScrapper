"""
Usage :
    python main.py <url> <n> [--platform instagram|tiktok]

Exemples :
    python main.py https://www.instagram.com/cristiano/ 10
    python main.py https://www.tiktok.com/@khaby.lame 10 --platform tiktok
"""

import argparse
import json
import logging
import sys
from dataclasses import asdict

from bench import Bench
from logging_setup import setup_logging

logger = setup_logging(__name__, level=logging.INFO)

PLATFORMS = {
    "instagram": "scrapers.instagram.InstagramScraper",
    "tiktok": "scrapers.tiktok.TikTokScraper",
}

URL_PLATFORM_MAP = {
    "instagram.com": "instagram",
    "tiktok.com": "tiktok",
}


def detect_platform(url: str) -> str:
    """Détecte la plateforme depuis l'URL."""
    from urllib.parse import urlparse
    try:
        netloc = urlparse(url).netloc.lower().lstrip("www.")
        for domain, platform in URL_PLATFORM_MAP.items():
            if netloc == domain or netloc.endswith("." + domain):
                return platform
    except Exception:
        pass
    raise ValueError(
        f"Impossible de détecter la plateforme depuis l'URL : {url!r}\n"
        f"Précise-la manuellement avec --platform ({', '.join(PLATFORMS)})"
    )


def load_scraper(platform: str):
    """Importe et retourne la classe scraper pour la plateforme demandée."""
    if platform not in PLATFORMS:
        raise ValueError(f"Plateforme inconnue : {platform!r}. Choix : {list(PLATFORMS)}")

    import importlib
    module_path, class_name = PLATFORMS[platform].rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrape n posts depuis un profil (Instagram, TikTok, ...)"
    )
    parser.add_argument("url", help="URL du profil")
    parser.add_argument("n", type=int, help="Nombre de posts à scraper")
    parser.add_argument(
        "--platform", "-p",
        choices=list(PLATFORMS),
        default=None,
        help="Plateforme cible (auto-détectée depuis l'URL si absent)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Fichier JSON de sortie (optionnel)",
        default=None,
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Affiche la fenêtre Chrome (debug)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Mode DEBUG — affiche les logs détaillés",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    platform = args.platform or detect_platform(args.url)

    if args.debug:
        for handler in logger.handlers:
            handler.setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        logger.info("Mode DEBUG activé", extra={"debug": True})
        if platform == "tiktok" and not args.no_headless:
            args.no_headless = True
            logger.info("Mode headful forcé pour TikTok en debug")

    logger.info("=" * 60)
    logger.info(f"Scraper — {platform.upper()}")
    logger.info("=" * 60)
    logger.info(f"URL : {args.url}")
    logger.info(f"Posts à récupérer : {args.n}")

    if args.n <= 0:
        logger.error("n doit être un entier positif.")
        sys.exit(1)

    ScraperClass = load_scraper(platform)
    bench = Bench()
    scraper = ScraperClass(headless=not args.no_headless, bench=bench)

    try:
        posts = scraper.scrape(args.url, args.n)

        logger.info("")
        logger.info("=" * 60)
        logger.info(f"Résultats : {len(posts)} posts")
        logger.info("=" * 60)
        for i, post in enumerate(posts, 1):
            caption_preview = post.caption[:80] + "…" if len(post.caption) > 80 else post.caption
            logger.info(f"[{i}] {post.url}")
            logger.info(f"     Plateforme : {post.platform}")
            logger.info(f"     Type       : {post.media_type}")
            logger.info(f"     Timestamp  : {post.timestamp}")
            views_str = f" | Views: {post.views_count}" if post.views_count else ""
            logger.info(f"     Likes: {post.likes_count} | Comments: {post.comments_count}{views_str}")
            logger.info(f"     Followers  : {post.user_followers}")
            logger.info(f"     Caption    : {caption_preview}")

        if args.output:
            logger.info("")
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump([asdict(p) for p in posts], f, ensure_ascii=False, indent=2)
            logger.info(f"✓ Sauvegardé dans {args.output}")

    finally:
        scraper.close()
        print(bench.report())


if __name__ == "__main__":
    main()
