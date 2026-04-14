"""
Usage :
    python main.py <url> <n>

Exemples :
    python main.py https://www.instagram.com/cristiano/ 10
    python main.py https://www.instagram.com/explore/tags/python/ 5
"""

import argparse
import json
import logging
import sys
from dataclasses import asdict

from bench import Bench
from scraper import InstagramScraper

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrape n posts depuis une page Instagram (posts épinglés exclus)"
    )
    parser.add_argument("url", help="URL de la page Instagram")
    parser.add_argument("n", type=int, help="Nombre de posts à scraper")
    parser.add_argument(
        "--output", "-o", help="Fichier JSON de sortie (optionnel)", default=None
    )
    parser.add_argument(
        "--no-headless", action="store_true", help="Affiche la fenêtre Chrome (debug)"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    logger.info("=" * 60)
    logger.info("Instagram Scraper")
    logger.info("=" * 60)

    if args.n <= 0:
        logger.error("n doit être un entier positif.")
        sys.exit(1)

    logger.info(f"URL : {args.url}")
    logger.info(f"Posts à récupérer : {args.n}")

    bench = Bench()
    scraper = InstagramScraper(headless=not args.no_headless, bench=bench)
    try:
        posts = scraper.scrape(args.url, args.n)

        logger.info("")
        logger.info("=" * 60)
        logger.info(f"Résultats : {len(posts)} posts")
        logger.info("=" * 60)
        for i, post in enumerate(posts, 1):
            caption_preview = post.caption[:80] + "…" if len(post.caption) > 80 else post.caption
            logger.info(f"[{i}] {post.url}")
            logger.info(f"     {post.timestamp}")
            logger.info(f"     {caption_preview}")

        logger.info("")
        logger.info("JSON output :")
        logger.info(json.dumps([asdict(p) for p in posts], ensure_ascii=False, indent=2))

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
