"""
Parsing des arguments CLI.
"""

import argparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recupere les posts d'un profil social (Instagram, TikTok, Reddit, ...)"
    )
    parser.add_argument(
        "url",
        help="URL du profil (ex: https://www.instagram.com/cristiano/ ou https://www.reddit.com/user/Terracid/)",
    )
    parser.add_argument("n", type=int, help="Nombre de posts a recuperer")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Mode DEBUG — affiche les logs detailles",
    )
    parser.add_argument(
        "--output", "-o",
        help="Fichier JSON de sortie (optionnel)",
        default=None,
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Affiche la fenetre du navigateur (debug)",
    )
    return parser.parse_args()
