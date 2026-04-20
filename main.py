"""
Point d'entree CLI du scraper multi-plateforme.

Usage :
    python main.py <url> <n> [--debug] [--no-headless] [--output fichier.json]

Exemples :
    python main.py https://www.instagram.com/cristiano/ 10 --debug
    python main.py https://www.tiktok.com/@khaby.lame 10
    python main.py https://www.reddit.com/user/Terracid/ 10
"""

import json
import logging
import sys

from app.cli.args import parse_args
from app.core.exceptions import InvalidLimitError
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

    try:
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

    for i, post in enumerate(payload["posts"], 1):
        title = post.get("title") or ""
        description = post.get("description") or ""
        preview = title or description
        preview = (preview[:80] + "...") if len(preview) > 80 else preview

        logger.info(f"[{i}] {post.get('post_url') or post.get('url')}")
        logger.info(f"     Type       : {post.get('type')}")
        logger.info(f"     Created UTC: {post.get('created_utc')}")
        logger.info(
            f"     Score: {post.get('score')} | Comments: {post.get('num_comments')}"
        )
        logger.info(f"     Subreddit  : {post.get('subreddit')}")
        logger.info(f"     Preview    : {preview}")

    # Export JSON optionnel
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(f"Sauvegarde dans {args.output}")

    # Affiche le JSON brut sur stdout
    print("\n" + "=" * 60)
    print(f"OUTPUT JSON ({result.source.upper()}):")
    print("=" * 60)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("=" * 60)


if __name__ == "__main__":
    main()
