"""
Parsing des arguments CLI.
"""

import argparse


# ── Construction des arguments CLI et garde-fous d usage. ──
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    # 1) Declarer les arguments communs aux modes collecte et health.
    parser = argparse.ArgumentParser(
        description=(
            "Recupere les posts d'un profil social "
            "(Instagram, TikTok, Twitter/X, Reddit, ...) ou verifie l'etat des sources."
        )
    )
    parser.add_argument(
        "url",
        nargs="?",
        help=(
            "URL du profil "
            "(ex: https://x.com/elonmusk ou https://www.reddit.com/user/Terracid/)"
        ),
    )
    parser.add_argument(
        "n",
        nargs="?",
        type=int,
        help="Nombre de posts a recuperer",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Verifie l'etat de toutes les sources de donnees du projet",
    )
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
    parser.add_argument(
        "--setup-tiktok-session",
        action="store_true",
        help=(
            "Lance Chrome visible, navigue sur TikTok et sauvegarde la session "
            "pour les executions headless suivantes. "
            "A lancer une fois avant le scraping TikTok."
        ),
    )
    args = parser.parse_args(argv)

    # 2) Interdire le mode collecte incomplet hors healthcheck / setup-session.
    if not args.health and not args.setup_tiktok_session and (args.url is None or args.n is None):
        parser.error("url et n sont obligatoires sauf avec --health ou --setup-tiktok-session")

    return args
