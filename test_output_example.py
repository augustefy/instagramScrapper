#!/usr/bin/env python3
"""
Script de test pour visualiser la structure de sortie du scraper.
Ne fait pas de scraping réel - affiche juste un exemple formaté.
"""

import json
from dataclasses import asdict
from scraper import PostData

# Exemple de données que le scraper retournerait
example_posts = [
    PostData(
        url="https://www.instagram.com/cristiano/p/ABC123/",
        caption="Amazing goal! 🔥",
        timestamp="2024-04-15T14:30:00+00:00",
        likes_count=1500000,
        comments_count=45000,
        views_count=3200000,
        media_type="video",
        user_followers=600000000,
    ),
    PostData(
        url="https://www.instagram.com/cristiano/p/XYZ789/",
        caption="Team training session",
        timestamp="2024-04-14T10:15:00+00:00",
        likes_count=800000,
        comments_count=23000,
        views_count=1900000,
        media_type="carousel",
        user_followers=600000000,
    ),
    PostData(
        url="https://www.instagram.com/cristiano/p/DEF456/",
        caption="Family time",
        timestamp="2024-04-13T18:45:00+00:00",
        likes_count=2100000,
        comments_count=67000,
        views_count=None,
        media_type="image",
        user_followers=600000000,
    ),
]

print("\n" + "="*80)
print("EXEMPLE DE SORTIE JSON DU SCRAPER")
print("="*80)
print(json.dumps([asdict(p) for p in example_posts], ensure_ascii=False, indent=2))
print("="*80 + "\n")

print("\nStructure de chaque post:")
print("  - url: URL complète du post")
print("  - caption: Légende du post")
print("  - timestamp: Date/heure en ISO 8601")
print("  - likes_count: Nombre de likes")
print("  - comments_count: Nombre de commentaires")
print("  - views_count: Nombre de vues (0 si indisponible)")
print("  - media_type: Type - image, video, carousel, reel")
print("  - user_followers: Nombre de followers du profil")
