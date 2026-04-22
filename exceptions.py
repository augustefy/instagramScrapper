"""
Exceptions partagées entre tous les scrapers.
"""


# ── Base commune des erreurs metier du scraper historique. ──
class ScraperError(Exception):
    """Exception de base pour tous les scrapers."""
    pass


# ── Echec de chargement de page cible. ──
class PageLoadError(ScraperError):
    """Erreur lors du chargement d'une page."""
    pass


# ── Donnees de post incompletes ou incoherentes. ──
class PostDataError(ScraperError):
    """Erreur lors de l'extraction des données d'un post."""
    pass


# ── Echec lie aux selecteurs DOM attendus. ──
class SelectorError(ScraperError):
    """Un sélecteur CSS/JS n'a pas trouvé d'élément."""
    pass


# ── Garde-fou quand le DOM a evolue. ──
class SelectorsOutdatedError(SelectorError):
    """Les sélecteurs sont obsolètes (la plateforme a changé son HTML)."""
    pass


# ── Impossible de fermer une surcouche bloquante. ──
class PopupDismissError(ScraperError):
    """Impossible de fermer un popup."""
    pass


# ── Echec de progression dans la grille de posts. ──
class ScrollError(ScraperError):
    """Erreur lors du scroll de la page."""
    pass


# ── Echec d initialisation ou d utilisation du navigateur. ──
class BrowserError(ScraperError):
    """Erreur liée au navigateur (Playwright)."""
    pass


# ── Erreur de validation des entrees utilisateur. ──
class ValidationError(ScraperError):
    """Erreur de validation des entrées."""
    pass


# Compat alias
InstagramScraperError = ScraperError
