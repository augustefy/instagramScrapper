# Guide de Maintenance du Scraper Instagram

Ce document explique comment maintenir et faire évoluer le scraper Instagram au fil du temps.

## Architecture

Le scraper est organisé en modules pour faciliter la maintenance :

```
scraper.py           # Code principal (async scraping)
config.py            # Configuration centralisée (sélecteurs, timeouts, etc)
exceptions.py        # Exceptions custom
validators.py        # Validation des entrées
logging_setup.py     # Logging structuré
bench.py             # Benchmarking
```

## Quand Instagram casse le scraper

**La cause la plus fréquente** : Instagram modifie son HTML et les sélecteurs CSS/patterns deviennent obsolètes.

### Comment détecter le problème

1. Le scraper s'arrête avec une erreur `SelectorsOutdatedError`
2. Vérifiez `debug_screenshot.png` généré automatiquement
3. Les logs contiennent des détails

### Comment réparer

**Étape 1** : Ouvrez `config.py` et trouvez la classe `SelectorConfig`

```python
@dataclass
class SelectorConfig:
    """Les sélecteurs à mettre à jour."""
    POST_CAPTION_SPAN = "span.x126k92a"  # ← Celui-ci change souvent
```

**Étape 2** : Ouvrez Instagram dans le navigateur et inspectez le DOM

- Clic droit → Inspecter
- Cherchez le titre du post, la caption, le timestamp
- Copiez le sélecteur CSS correct

**Étape 3** : Mettez à jour `config.py` avec les nouveaux sélecteurs

```python
POST_CAPTION_SPAN = "span.nouveau-class-instagram"  # Nouveau sélecteur
```

**Étape 4** : Testez

```python
from scraper import InstagramScraper

scraper = InstagramScraper()
posts = scraper.scrape("https://www.instagram.com/username", n=5)
for post in posts:
    print(post.caption)
```

## Sélecteurs fragiles et stratégies de fallback

Certains sélecteurs changent fréquemment chez Instagram :

| Sélecteur | Fragilité | Stratégie |
|-----------|-----------|----------|
| `span.x126k92a` (caption) | **TRÈS HAUTE** | ✓ API fallback implémenté |
| `time[datetime]` (timestamp) | Basse | ✗ Peu probable de changer |
| `meta[og:description]` (fallback) | Moyenne | ✓ Utilisé en fallback |

**Conseil** : Le scraper préfère d'abord l'API Instagram interceptée, puis la DOM en fallback. Ça limite les problèmes de sélecteurs.

## Logs et débogage

Le logging est structuré en JSON pour faciliter l'analyse :

```json
{
  "timestamp": "14:23:45",
  "level": "ERROR",
  "logger": "scraper",
  "message": "Aucun post trouvé. Les sélecteurs sont probablement obsolètes.",
  "screenshot": "debug_screenshot.png"
}
```

**Activer le mode débogage** :

```python
from logging_setup import setup_logging
import logging

logger = setup_logging(__name__, level=logging.DEBUG, json_mode=True)
```

## Améliorer les performances

Le scraper a déjà plusieurs optimisations :

- **Pool de tabs** : Réutilise les pages au lieu de les recréer
- **Routing bloquant** : Bloque les images/fonts/media pour réduire la bande passante
- **API interceptée** : Récupère les données via l'API au lieu de parser le DOM
- **Timeout adaptés** : `TIMEOUT_POST_LOAD=10s`, `TIMEOUT_PAGE_LOAD=15s`

Pour ajuster :

```python
# Dans config.py
WORKERS = 10  # Nombre de tabs parallèles (↑ = plus rapide mais risqué)
TIMEOUT_POST_LOAD = 10000  # Timeout par post en ms
```

## Ajouter des colonnes de données

Actuellement, le scraper retourne : `url`, `caption`, `timestamp`.

Pour ajouter des données (likes, commentaires, etc) :

**Étape 1** : Modifier `PostData` dans `scraper.py`

```python
@dataclass
class PostData:
    url: str
    caption: str = ""
    timestamp: str = ""
    likes: int = 0  # ← Nouveau champ
```

**Étape 2** : Extraire depuis l'API ou DOM dans `_scrape_post()`

```python
# Via API
api_data["likes"] = item.get("like_count", 0)

# Via DOM
data = await tab.evaluate("""() => {
    return {
        likes: document.querySelector('[aria-label*="like"]')?.innerText || 0
    }
}""")
```

## Tester les changements

Créez des tests pour vérifier que vos changements ne cassent rien :

```python
# test_scraper.py
import pytest
from scraper import InstagramScraper

@pytest.mark.asyncio
async def test_scrape_post_data_structure():
    scraper = InstagramScraper()
    posts = scraper.scrape("https://www.instagram.com/instagram", n=1)
    
    assert len(posts) > 0
    post = posts[0]
    assert hasattr(post, 'url')
    assert hasattr(post, 'caption')
    assert hasattr(post, 'timestamp')
    assert post.url.startswith('https://www.instagram.com')
```

## Monitoring en production

Si vous déployez ce scraper, surveille ces métriques :

1. **Taux d'erreur** : % de posts non scrapés
2. **Temps moyen** : Temps par post
3. **Erreurs de sélecteurs** : Indique un changement Instagram

Exemple avec logs JSON :

```bash
# Filtrer les erreurs de sélecteurs
cat logs.json | grep SelectorsOutdatedError | wc -l
```

## Checklist avant de commiter

- [ ] Tests passent
- [ ] `config.py` est à jour (aucun sélecteur hardcodé dans le code)
- [ ] Les exceptions custom sont utilisées au lieu de `Exception`
- [ ] Logging structuré partout (`logger.info(..., extra={...})`)
- [ ] Inputs validés (via `validators.py`)

## Support

Si le scraper échoue :

1. **Vérifiez `debug_screenshot.png`** → Les sélecteurs sont-ils corrects ?
2. **Consultez les logs** → Quel type d'erreur ?
3. **Testez manuellement** → Instagram accepte votre User-Agent ?
4. **Mettez à jour `config.py`** → Les sélecteurs ont changé.
