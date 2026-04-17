"""
Point d'entree CLI du scraper multi-plateforme.

Usage :
    python main.py <url> <n> [--debug] [--no-headless] [--output fichier.json]

Exemples :
    python main.py https://www.instagram.com/cristiano/ 10 --debug
    python main.py https://www.tiktok.com/@khaby.lame 10
"""

import json
import logging
import sys
from dataclasses import asdict

from app.cli.args import parse_args
from app.services.social_resolver import fetch_profile_posts
from logging_setup import setup_logging


def main():
    args = parse_args()

    # Setup logging
    level = logging.DEBUG if args.debug else logging.INFO
    logger = setup_logging("main", level=level)

    # En mode debug, passe tous les loggers en DEBUG
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        for name in logging.Logger.manager.loggerDict:
            lg = logging.getLogger(name)
            lg.setLevel(logging.DEBUG)
            for handler in lg.handlers:
                handler.setLevel(logging.DEBUG)
        logger.info("Mode DEBUG active")

    if args.n <= 0:
        logger.error("Le nombre de posts doit etre un entier positif.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info(f"URL       : {args.url}")
    logger.info(f"Posts     : {args.n}")
    logger.info(f"Headless  : {not args.no_headless}")
    logger.info("=" * 60)

    try:
        result = fetch_profile_posts(
            url=args.url,
            limit=args.n,
            headless=not args.no_headless,
            debug=args.debug,
        )
    except Exception as e:
        logger.error(f"Erreur fatale : {e}")
        if args.debug:
            logger.exception("Traceback complet :")
        sys.exit(1)

    # Affichage des resultats
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Resultats : {len(result.posts)} post(s) via {result.source.upper()}")
    logger.info(f"Plateforme: {result.platform}")
    logger.info(f"Username  : @{result.username}")
    logger.info("=" * 60)

    for i, post in enumerate(result.posts, 1):
        caption_preview = (post.caption[:80] + "...") if len(post.caption) > 80 else post.caption
        logger.info(f"[{i}] {post.url}")
        logger.info(f"     Type       : {post.media_type}")
        logger.info(f"     Timestamp  : {post.timestamp}")
        views_str = f" | Views: {post.views_count}" if post.views_count else ""
        logger.info(f"     Likes: {post.likes_count} | Comments: {post.comments_count}{views_str}")
        logger.info(f"     Followers  : {post.user_followers}")
        logger.info(f"     Caption    : {caption_preview}")

    # Export JSON optionnel
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump([asdict(p) for p in result.posts], f, ensure_ascii=False, indent=2)
        logger.info(f"Sauvegarde dans {args.output}")

    # Affiche le JSON brut sur stdout
    print("\n" + "=" * 60)
    print(f"OUTPUT JSON ({result.source.upper()}):")
    print("=" * 60)
    print(json.dumps([asdict(p) for p in result.posts], ensure_ascii=False, indent=2))
    print("=" * 60)


if __name__ == "__main__":
    main()
