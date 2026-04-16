"""
Exemple d'utilisation du scraper Instagram.

Ce script montre les différentes façons d'utiliser le scraper
et comment gérer les erreurs.
"""

from scraper import InstagramScraper
from exceptions import SelectorsOutdatedError, ValidationError, PageLoadError
import logging

# Logging avec JSON en production, normal en développement
from logging_setup import setup_logging
logger = setup_logging(__name__, level=logging.INFO, json_mode=False)


def basic_example():
    """Exemple basique : scraper 10 posts d'un profil."""
    scraper = InstagramScraper(headless=True)

    try:
        posts = scraper.scrape(
            url="https://www.instagram.com/instagram",
            n=10,
        )

        for i, post in enumerate(posts, 1):
            print(f"\n[{i}] {post.url}")
            print(f"Caption: {post.caption[:100]}...")
            print(f"Date: {post.timestamp}")

    except SelectorsOutdatedError as e:
        logger.error("Les sélecteurs sont obsolètes. Instagram a changé son HTML.")
        logger.error("Vérifiez config.py et consultez debug_screenshot.png")
    except PageLoadError as e:
        logger.error("Impossible de charger le profil. Vérifiez l'URL.")
    except ValidationError as e:
        logger.error(f"Erreur de validation : {e}")
    except Exception as e:
        logger.error(f"Erreur inattendue : {e}")


def with_headless_false():
    """Exemple avec le navigateur visible (utile pour le débogage)."""
    scraper = InstagramScraper(headless=False)  # On voit le navigateur

    try:
        posts = scraper.scrape(
            url="https://www.instagram.com/nasa",
            n=5,
        )
        print(f"✓ {len(posts)} posts récupérés")
    except Exception as e:
        print(f"✗ Erreur : {e}")


def batch_scraping():
    """Exemple : scraper plusieurs profils."""
    scraper = InstagramScraper(headless=True)

    profiles = [
        "instagram",
        "nasa",
        "natgeo",
    ]

    results = {}

    for profile in profiles:
        try:
            url = f"https://www.instagram.com/{profile}"
            posts = scraper.scrape(url, n=3)
            results[profile] = {
                "success": True,
                "count": len(posts),
            }
            print(f"✓ {profile}: {len(posts)} posts")
        except Exception as e:
            results[profile] = {
                "success": False,
                "error": str(e),
            }
            print(f"✗ {profile}: {e}")

    return results


if __name__ == "__main__":
    print("=" * 50)
    print("Exemple 1 : Scraper basique")
    print("=" * 50)
    basic_example()

    print("\n" + "=" * 50)
    print("Exemple 2 : Scraper visible (pour débogage)")
    print("=" * 50)
    # Commentez cette ligne si vous ne voulez pas voir le navigateur
    # with_headless_false()

    print("\n" + "=" * 50)
    print("Exemple 3 : Scraper plusieurs profils")
    print("=" * 50)
    # results = batch_scraping()
    # print(f"\nRésultats : {results}")
