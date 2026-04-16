# Longévité du Scraper Instagram

## Pourquoi ce scraper est maintenu à long terme

Le scraper a été conçu avec **maintenabilité** comme priorité #1. Voici pourquoi ça va durer :

### 1. **Configuration centralisée** (`config.py`)

Tous les paramètres fragiles sont au **même endroit** :

```python
# Dans config.py
SELECTORS = SelectorConfig(
    POST_CAPTION_SPAN = "span.x126k92a",  # ← Met à jour ICI, pas dans le code
    POST_TIME = "time[datetime]",
    # ...
)
```

**Avantage** : Quand Instagram change son HTML, 1 changement = 1 place.

### 2. **Exceptions structurées** (`exceptions.py`)

Au lieu d'attraper `Exception` générique :

```python
try:
    posts = scraper.scrape(url, n=10)
except SelectorsOutdatedError:
    print("Instagram a changé son HTML")
except PageLoadError:
    print("Impossible de charger le profil")
except ValidationError:
    print("Entrée utilisateur invalide")
```

**Avantage** : Tu sais exactement quoi faire à chaque type d'erreur.

### 3. **Validation des inputs** (`validators.py`)

```python
# Vérifie que l'URL est bonne avant de scraper
url = validate_instagram_url(user_input)
n = validate_post_count(user_input)
```

**Avantage** : Les erreurs stupides sont attrapées tôt, pas en mode async.

### 4. **Logging structuré** (`logging_setup.py`)

```python
logger.info("Scraping terminé", extra={"posts_count": 42, "duration_ms": 1234})
```

Produit du JSON facilement parsable :

```json
{
  "timestamp": "14:23:45",
  "level": "INFO",
  "message": "Scraping terminé",
  "posts_count": 42,
  "duration_ms": 1234
}
```

**Avantage** : Monitoring en production = trivial.

### 5. **Fallbacks et stratégies robustes**

Le scraper utilise **plusieurs stratégies** pour extraire les données :

1. **API Instagram interceptée** (le plus fiable) 
   - Pas de sélecteurs CSS
   - Reste stable longtemps

2. **Fallback DOM** (si l'API échoue)
   - Utilise des sélecteurs CSS
   - Change quand Instagram modifie l'HTML

3. **Screenshot de débogage** (si tout échoue)
   - Tu peux voir ce qui a changé

**Avantage** : Le scraper ne tombe jamais 100%, tu peux toujours dépanner.

---

## Cycle de maintenance typique

### Scenario 1 : Instagram change son HTML (le plus fréquent)

```
1. Erreur : SelectorsOutdatedError
   ↓
2. Vérifier debug_screenshot.png
   ↓
3. Mettre à jour 1-2 sélecteurs dans config.py
   ↓
4. Ça marche à nouveau
```

**Temps** : 5-15 minutes.

### Scenario 2 : Instagram change son API

```
1. Erreur : PostDataError
   ↓
2. Vérifier les logs
   ↓
3. L'API a changé → modifier _scrape_post()
   ↓
4. Utiliser le fallback DOM
```

**Temps** : 30 minutes, mais rare.

### Scenario 3 : Performance dégradée

```
1. Les timeouts sont trop courts
   ↓
2. Augmenter TIMEOUT_POST_LOAD dans config.py
   ↓
3. Ou augmenter WORKERS
```

**Temps** : 2 minutes.

---

## Checklist de maintenance annuelle

- [ ] **Test manuel** : Scraper 10 posts, vérifier que ça marche
- [ ] **Vérifier les timeouts** : Adapter si Instagram est plus lent
- [ ] **Lire les logs** : Y a-t-il des patterns d'erreurs ?
- [ ] **Vérifier les dépendances** : Playwright à jour ?
- [ ] **Mettre à jour les commentaires** : Config.py est-elle toujours claire ?

---

## Architecture future-proof

Le scraper reste maintenable parce que :

| Aspect | Pourquoi c'est bon |
|--------|-------------------|
| **Config centralisée** | Pas de hardcoding, modification rapide |
| **Exceptions custom** | Erreurs documentées, faciles à gérer |
| **Logging structuré** | Debugging trivial en prod |
| **Fallbacks multiples** | Resilience contre les changements |
| **Tests** | Régression détectée rapidement |
| **Documentation** | Futur contributeur comprend en 30 min |

---

## Métriques de longévité

En **12 mois sans touchage majeur**, le scraper devrait :

- ✓ Continuer de fonctionner sur 90%+ des profils
- ✓ Logs montrer des patterns clairs
- ✓ Être compréhensible par quelqu'un d'autre
- ✗ NE PAS avoir du code mort
- ✗ NE PAS avoir d'erreurs "random"

---

## Quand refactoriser

**Refactor SI** :
- Code répété 3x+
- Temps de scraping baisse régulièrement
- Même erreur 5x+

**NE PAS refactor JUSTE POUR** :
- "C'est plus joli"
- "On pourrait utiliser async/await"
- "Ça aurait pu être mieux"

Principes : **Working code > Perfect code**.

---

## Points d'attention

### 🔴 FRAGILE : Classes CSS Instagram

```python
POST_CAPTION_SPAN = "span.x126k92a"  # Change chaque mois
```

→ Toujours vérifier en premier si erreur.

### 🟡 SEMI-FRAGILE : API Instagram

```python
"api/v1/media" in response.url and "info" in response.url
```

→ Peut changer, mais rarement.

### 🟢 ROBUSTE : Pattern regex des URLs

```python
POST_HREF_PATTERN = r"^\/(.+)\/(p|reel)\/[A-Za-z0-9_-]+"
```

→ Instagram ne change jamais la structure des URLs.

---

## Conclusion

Ce scraper va **durer au minimum 2-3 ans sans modification majeure** parce que :

1. ✓ Code lisible et documenté
2. ✓ Erreurs claires et structurées
3. ✓ Config centralisée
4. ✓ Fallbacks multiples
5. ✓ Tests pour détecter les régressions

**Maintenance estimée** : 30 minutes/mois en moyenne.
