"""
Modele normalise d'un post social.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class NormalizedPost:
    """
    Representation commune d'un post, quelle que soit la plateforme source.

    Les champs generiques sont utilises par l'affichage CLI, l'export JSON et les
    couches qui ne veulent pas connaitre les details propres a Instagram,
    Twitter/X, Reddit, etc. Les champs plus specifiques restent optionnels pour
    conserver les informations utiles quand une plateforme les expose.
    """

    # Identifiant natif du post sur la plateforme source.
    # Cas d'utilisation: dedoublonnage, logs, stockage, construction d'URL.
    id: str

    # Nom canonique de la plateforme source: "instagram", "twitter", "reddit", etc.
    # Cas d'utilisation: router le post vers le bon traitement ou le bon affichage.
    platform: str

    # Username de l'auteur du post, sans imposer un format strict avec ou sans @.
    # Cas d'utilisation: affichage, regroupement par auteur, reconstruction de liens.
    author_username: str

    # URL publique la plus directe vers le post.
    # Cas d'utilisation: ouvrir, exporter ou citer le post dans les resultats.
    post_url: str

    # Texte principal du post: caption Instagram, tweet, selftext Reddit, etc.
    # Cas d'utilisation: preview CLI, analyse texte, recherche, export lisible.
    text: str | None = None

    # Description lisible du post, souvent identique a text quand la plateforme ne
    # distingue pas les deux notions.
    # Cas d'utilisation: compatibilite avec les anciens scrapers ou APIs.
    description: str | None = None

    # Type de contenu normalise: "image", "video", "text", "link", "repost", etc.
    # Cas d'utilisation: choisir l'affichage, filtrer les posts, traiter les medias.
    type: str = "unknown"

    # Date de creation normalisee en chaine lisible, idealement au format ISO 8601.
    # Cas d'utilisation: tri, affichage, export et comparaison entre plateformes.
    created_at: str | None = None

    # Nombre de likes/favoris/upvotes selon le vocabulaire de la plateforme.
    # Cas d'utilisation: mesurer l'engagement dans un champ commun.
    like_count: int | None = None

    # Nombre de reponses/commentaires quand la plateforme expose cette metrique.
    # Cas d'utilisation: mesurer la conversation autour du post.
    reply_count: int | None = None

    # Nombre de repartages: retweets, reposts, shares, etc.
    # Cas d'utilisation: mesurer la diffusion du post.
    repost_count: int | None = None

    # Nombre de citations/quote-posts quand la plateforme les distingue.
    # Cas d'utilisation: mesurer les reprises avec commentaire, surtout Twitter/X.
    quote_count: int | None = None

    # Nombre de vues/impressions quand disponible.
    # Cas d'utilisation: mesurer la portee brute du post.
    view_count: int | None = None

    # URLs directes vers les medias attaches au post: images, videos, galleries.
    # Cas d'utilisation: telechargement, preview, analyse visuelle, archivage.
    media_urls: list[str] = field(default_factory=list)

    # Liens externes contenus dans le post, hors medias natifs.
    # Cas d'utilisation: extraction de sources, audit de liens, enrichissement.
    external_links: list[str] = field(default_factory=list)

    # Indique si la plateforme signale le post comme sensible.
    # Cas d'utilisation: filtrage, avertissement utilisateur, moderation.
    is_sensitive: bool | None = None

    # Titre natif du post quand la plateforme en fournit un, notamment Reddit.
    # Cas d'utilisation: affichage plus riche que le texte seul pour les posts titres.
    title: str | None = None

    # URL cible principale associee au post: media principal, lien externe ou URL native.
    # Cas d'utilisation: garder le lien "utile" du contenu en plus de post_url.
    url: str | None = None

    # Timestamp Unix UTC natif quand la plateforme l'expose, notamment Reddit.
    # Cas d'utilisation: tri precis, conversions de date, conservation du champ brut.
    created_utc: float | None = None

    # Score natif Reddit, generalement upvotes moins downvotes.
    # Cas d'utilisation: conserver la metrique Reddit sans la confondre avec un like.
    score: int | None = None

    # Nombre natif de commentaires Reddit.
    # Cas d'utilisation: conserver le champ source en plus du champ generique reply_count.
    num_comments: int | None = None

    # Nom du subreddit d'origine pour un post Reddit.
    # Cas d'utilisation: filtrage par communaute et affichage du contexte Reddit.
    subreddit: str | None = None

    # Permalink Reddit relatif, par exemple "/r/.../comments/...".
    # Cas d'utilisation: reconstruire une URL reddit.com ou conserver le chemin source.
    permalink: str | None = None

    # Indique si Reddit marque le post comme NSFW ("not safe for work").
    # Cas d'utilisation: filtrage specifique Reddit et preservation du signal natif.
    is_nsfw: bool | None = None

    # Payload source complet quand include_raw=True.
    # Cas d'utilisation: debug, tests, analyse d'un champ non encore normalise.
    raw: dict[str, Any] | None = None

    # Zone d'extension pour des champs utiles mais pas assez communs pour la dataclass.
    # Cas d'utilisation: ajouter une metadonnee ponctuelle sans changer le schema public.
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Retourne un dictionnaire pret pour l'export JSON."""
        data = asdict(self)

        # Evite de polluer les exports standards avec le payload brut absent.
        if self.raw is None:
            data.pop("raw", None)

        # Garde l'export compact quand aucune metadonnee supplementaire n'est fournie.
        if not self.extra:
            data.pop("extra", None)

        return data
