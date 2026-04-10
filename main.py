"""
Usage :
    python main.py <url> <n>

Exemples :
    python main.py https://www.instagram.com/cristiano/ 10
    python main.py https://www.instagram.com/explore/tags/python/ 5
"""

import argparse
import json
import sys
from dataclasses import asdict

from scraper import InstagramScraper


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
        "--headless", action="store_true", help="Chrome sans fenêtre graphique"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.n <= 0:
        print("n doit être un entier positif.")
        sys.exit(1)

    scraper = InstagramScraper(headless=args.headless)
    try:
        scraper.login()
        posts = scraper.scrape(args.url, args.n)

        print(f"\n{'─' * 50}")
        print(f"{len(posts)} posts récupérés\n")
        for i, post in enumerate(posts, 1):
            caption_preview = post.caption[:80] + "…" if len(post.caption) > 80 else post.caption
            print(f"[{i}] {post.url}")
            print(f"     {post.timestamp}")
            print(f"     {caption_preview}\n")

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump([asdict(p) for p in posts], f, ensure_ascii=False, indent=2)
            print(f"Sauvegardé dans {args.output}")

    finally:
        scraper.close()


if __name__ == "__main__":
    main()
