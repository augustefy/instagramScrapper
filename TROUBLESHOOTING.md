# Troubleshooting — Le scraper casse ?

Utilise ce guide pour dépanner rapidement.

## Erreur 1 : `SelectorsOutdatedError`

**Symptôme** :
```
SelectorsOutdatedError: Aucun post trouvé. Instagram a probablement changé son HTML.
Vérifiez les sélecteurs dans config.py
```

**Cause** : Instagram a modifié sa structure HTML. C'est le problème le plus fréquent.

**Fixe en 10 min** :

1. Ouvre `debug_screenshot.png` (généré automatiquement)
2. Compare avec un post Instagram réel (ouvre Instagram dans le navigateur)
3. Cherche les différences dans le HTML :
   - Les éléments `<a>` des posts ?
   - Les balises `<time>` ?
   - Les captions (`<span>`) ?

4. Mets à jour `config.py` :

```python
# Dans config.py
class SelectorConfig:
    # Ancien sélecteur (cassé)
    POST_CAPTION_SPAN = "span.x126k92a"  
    
    # Nouveau sélecteur (mis à jour)
    POST_CAPTION_SPAN = "span.nouveau-class"  # ← Change ICI
```

5. Teste :
```bash
python3 example.py
```

---

## Erreur 2 : `PageLoadError`

**Symptôme** :
```
PageLoadError: Timeout au chargement de https://www.instagram.com/username
```

**Cause** :
- Connexion internet lente
- Instagram est en panne
- Le profil est privé
- Trop de requêtes (rate-limit)

**Fixe** :

### A) Augmente le timeout

```python
# Dans config.py
TIMEOUT_PAGE_LOAD = 30000  # 30 secondes au lieu de 15
```

### B) Ajoute un délai entre les requêtes

```python
# Dans scraper.py, avant de scraper le prochain profil
import time
time.sleep(5)  # Attends 5 secondes entre les profils
```

### C) Utilise headless=False pour déboguer

```python
scraper = InstagramScraper(headless=False)  # Tu vois le navigateur
```

---

## Erreur 3 : `ValidationError`

**Symptôme** :
```
ValidationError: URL doit être sur instagram.com, pas example.com
```

**Cause** : Tu as passé une URL invalide.

**Fixe** :
```python
# ❌ Mauvais
scraper.scrape("example.com/user", n=10)

# ✅ Correct
scraper.scrape("https://www.instagram.com/username", n=10)
```

---

## Erreur 4 : Aucun post trouvé (mais pas d'erreur)

**Symptôme** :
```
✓ Scraping terminé : 0 posts récupérés
```

**Cause** :
- Le profil est vide
- Les posts sont trop bas dans le scroll
- Instagram retourne rien

**Fixe** :

### A) Essaie avec headless=False
```python
scraper = InstagramScraper(headless=False)
```

Tu vois ce qui se passe exactement.

### B) Augmente le nombre de scrolls
```python
# Modifie la boucle de scroll dans _collect_n_hrefs
# Ajoute des scrolls supplémentaires
```

### C) Vérifier un profil avec beaucoup de posts
```python
# Au lieu d'un petit profil
scraper.scrape("https://www.instagram.com/instagram", n=5)
```

---

## Erreur 5 : Timeout sur les posts

**Symptôme** :
```
Warning: Timeout sur https://www.instagram.com/p/ABC123/
```

**Cause** :
- Instagram est lent
- Trop de posts en parallèle
- Mauvaise connexion

**Fixe** :

### A) Réduis les workers parallèles
```python
# Dans config.py
WORKERS = 5  # Au lieu de 10
```

### B) Augmente le timeout du post
```python
# Dans config.py
TIMEOUT_POST_LOAD = 15000  # Au lieu de 10
```

### C) Ajoute un délai entre les posts
```python
# Dans _scrape_post(), après le goto
await asyncio.sleep(0.5)  # Attends 500ms entre les posts
```

---

## Erreur 6 : `AttributeError` ou erreurs bizarres

**Symptôme** :
```
AttributeError: 'NoneType' object has no attribute 'xxx'
```

**Cause** : Le code a trouvé une situation inattendue.

**Fixe** :

1. Ouvre `debug_screenshot.png`
2. Regarde ce qui est différent
3. Cherche l'erreur dans les logs

**Logs avancés** :
```python
from logging_setup import setup_logging
import logging

logger = setup_logging(__name__, level=logging.DEBUG, json_mode=True)
```

---

## Erreur 7 : Trop lent

**Symptôme** :
```
Scraping 100 posts prend 30 minutes
```

**Cause** :
- Pas assez de workers
- Trop d'attentes
- Trop de choses bloquées

**Fixe** :

### A) Augmente les workers

```python
# Dans config.py
WORKERS = 20  # Au lieu de 10
```

⚠️ Attention : trop élevé = Instagram te ban-rate-limit.

### B) Réduis les timeouts
```python
TIMEOUT_POST_LOAD = 5000  # Moins d'attente
```

### C) Vérifiez le benchmark
```python
# Dans scraper.py
print(self.bench.elapsed)  # Voir où ça prend du temps
```

---

## Erreur 8 : Instagram te rate-limit

**Symptôme** :
```
Erreurs aléatoires 429, "trop de requêtes"
```

**Cause** : Tu scrapes trop vite.

**Fixe** :

### A) Réduis le nombre de workers
```python
WORKERS = 5  # Moins de requêtes parallèles
```

### B) Ajoute des délais
```python
await asyncio.sleep(2)  # Entre chaque requête
```

### C) Change le user-agent
```python
# Dans config.py
USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) ..."
```

### D) Attends entre les sessions
```python
import time
time.sleep(300)  # Attends 5 minutes
scraper = InstagramScraper()
```

---

## Erreur 9 : Les sélecteurs changent trop souvent

**Problème** : `POST_CAPTION_SPAN` change chaque mois chez Instagram.

**Stratégie** :

1. **Préfère l'API** : Le code utilise l'API Instagram quand possible (meilleur)
2. **Fallback DOM** : Utilise la DOM en dernier recours
3. **Screenshot de debug** : Si ça casse, tu as une image pour réparer

```python
# Dans _scrape_post()
if api_data:  # ← L'API est préférée
    return PostData(...)
else:  # ← Fallback DOM
    data = await tab.evaluate(...)
```

---

## Checklist rapide

```
[ ] L'URL est-elle correcte ? (https://www.instagram.com/username)
[ ] Le nombre de posts est-il valide ? (1-10000)
[ ] Instagram est-elle accessible ? (Teste dans le navigateur)
[ ] Le profil a-t-il des posts ? (Vérifie manuellement)
[ ] Vérifiez debug_screenshot.png ?
[ ] Les timeouts sont-ils assez élevés ? (TIMEOUT_PAGE_LOAD, TIMEOUT_POST_LOAD)
[ ] Y a-t-il des logs d'erreur ? (Cherche `error` ou `exception`)
[ ] Les workers ne sont-ils pas trop élevés ? (WORKERS <= 20)
```

---

## Communiquer le problème

Si tu as besoin d'aide, fournis :

1. ❌ L'erreur exacte
2. 📸 `debug_screenshot.png`
3. 📝 Les logs (stderr)
4. ⚙️ Ta config (config.py)
5. 📱 Le profil que tu essaies de scraper
6. 🌍 Ta région / VPN (pour les Instagram régionales)

---

## Escalade : Faut vraiment comprendre

Fichiers à lire :
- `config.py` — Comprendre les sélecteurs
- `MAINTENANCE.md` — Guide complet
- `scraper.py` — Le code
- `exceptions.py` — Types d'erreurs

**Logs détaillés** :
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Conclusion

**90% des problèmes** sont causés par :
1. ❌ Sélecteurs obsolètes → Met à jour `config.py`
2. ❌ Timeouts trop bas → Augmente les timeouts
3. ❌ URL invalide → Vérifies l'URL

Essaie ces 3 choses d'abord avant de paniquer 😎
