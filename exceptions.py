"""
Exceptions partagées entre tous les scrapers.
"""


class ScraperError(Exception):
    """Exception de base pour tous les scrapers."""
    pass


class PageLoadError(ScraperError):
    """Erreur lors du chargement d'une page."""
    pass


class PostDataError(ScraperError):
    """Erreur lors de l'extraction des données d'un post."""
    pass


class SelectorError(ScraperError):
    """Un sélecteur CSS/JS n'a pas trouvé d'élément."""
    pass


class SelectorsOutdatedError(SelectorError):
    """Les sélecteurs sont obsolètes (la plateforme a changé son HTML)."""
    pass


class PopupDismissError(ScraperError):
    """Impossible de fermer un popup."""
    pass


class ScrollError(ScraperError):
    """Erreur lors du scroll de la page."""
    pass


class BrowserError(ScraperError):
    """Erreur liée au navigateur (Playwright)."""
    pass


class ValidationError(ScraperError):
    """Erreur de validation des entrées."""
    pass


# Compat alias
InstagramScraperError = ScraperError
