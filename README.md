# Social Scraper API

API REST asynchrone pour récupérer les posts de profils sociaux (Instagram, TikTok, Twitter/X, Reddit, Facebook).

Les requêtes de scraping sont exécutées dans un **worker séparé** (RQ + Redis) pour ne jamais bloquer les workers HTTP.

---

## Architecture

```
POST /v1/scrapes
      │
      ▼
  FastAPI API ──enqueue──▶ Redis Queue ──pick──▶ RQ Worker
      │                                               │
      │◀────── job_id ─────────────────────────────── │
      │                                          fetch_profile_posts()
      │                                               │
GET /v1/scrapes/{id}/result ◀── résultat stocké Redis ◀┘
```

**Stack**
- FastAPI + Uvicorn (API HTTP)
- RQ + Redis (job queue + cache + rate limiting)
- Playwright / Botasaurus (scraping)
- Pydantic Settings (configuration)
- slowapi (rate limiting)

---

## Setup rapide

### Option A — Docker (recommandé)

```bash
cp .env.example .env
# Éditer .env avec vos clés API et credentials

docker compose up --build
```

L'API est disponible sur `http://localhost:8000`.

Pour lancer aussi le dashboard RQ :
```bash
docker compose --profile dev up
# Dashboard RQ : http://localhost:9181
```

### Option B — Local

**Prérequis** : Python 3.12+, Redis lancé localement.

```bash
# 1. Créer le virtualenv et installer les dépendances
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 2. Configurer l'environnement
cp .env.example .env
# Éditer .env

# 3. Lancer l'API
uvicorn api.main:app --reload

# 4. Lancer le worker (dans un autre terminal)
python -m worker.run
```

---

## Authentification

Toutes les routes (sauf `/health`) nécessitent le header `X-API-Key`.

Configurer les clés dans `.env` :
```
API_KEYS=ma-cle-secrete,deuxieme-cle
```

Les clés sont comparées via SHA-256 — elles ne transitent jamais en clair côté serveur.

**Auth désactivée** si `API_KEYS` est vide (mode développement uniquement).

---

## Utilisation

### 1. Lancer un scrape

```bash
curl -X POST http://localhost:8000/v1/scrapes \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ma-cle-secrete" \
  -d '{"url": "https://www.instagram.com/cristiano/", "limit": 10}'
```

Réponse `202 Accepted` :
```json
{
  "job_id": "d4f8a2b1-...",
  "status": "queued"
}
```

Si le résultat est en cache, `status` vaut immédiatement `"done"`.

### 2. Vérifier le statut

```bash
curl http://localhost:8000/v1/scrapes/d4f8a2b1-... \
  -H "X-API-Key: ma-cle-secrete"
```

```json
{
  "job_id": "d4f8a2b1-...",
  "status": "running"
}
```

Statuts possibles : `queued` | `running` | `done` | `failed`

### 3. Récupérer le résultat

```bash
curl http://localhost:8000/v1/scrapes/d4f8a2b1-.../result \
  -H "X-API-Key: ma-cle-secrete"
```

```json
{
  "job_id": "d4f8a2b1-...",
  "status": "done",
  "result": {
    "profile": { "username": "cristiano", "platform": "instagram" },
    "posts": [
      {
        "id": "...",
        "platform": "instagram",
        "post_url": "https://www.instagram.com/p/...",
        "text": "...",
        "like_count": 12345678,
        "type": "image",
        "created_at": "2024-01-15T10:30:00"
      }
    ]
  }
}
```

### 4. Health check

```bash
curl http://localhost:8000/health
```

```json
{ "status": "ok", "checks": { "api": "ok", "redis": "ok" } }
```

### Boucle de polling complète (bash)

```bash
KEY="ma-cle-secrete"
BASE="http://localhost:8000"

JOB_ID=$(curl -s -X POST $BASE/v1/scrapes \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $KEY" \
  -d '{"url": "https://x.com/elonmusk", "limit": 5}' | jq -r .job_id)

echo "Job lancé : $JOB_ID"

while true; do
  STATUS=$(curl -s $BASE/v1/scrapes/$JOB_ID -H "X-API-Key: $KEY" | jq -r .status)
  echo "  → $STATUS"
  [ "$STATUS" = "done" ] || [ "$STATUS" = "failed" ] && break
  sleep 3
done

curl -s $BASE/v1/scrapes/$JOB_ID/result -H "X-API-Key: $KEY" | jq .
```

---

## Plateformes supportées

| Plateforme | URL exemple | Source primaire | Fallback |
|------------|-------------|-----------------|---------|
| Instagram  | `https://www.instagram.com/username/` | Graph API | Playwright |
| TikTok     | `https://www.tiktok.com/@username` | Botasaurus | — |
| Twitter/X  | `https://x.com/username` | Guest API | — |
| Reddit     | `https://www.reddit.com/user/username/` | Public API | — |
| Facebook   | `https://www.facebook.com/pagename` | Graph API | — |

---

## Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `API_KEYS` | `""` | Clés API séparées par virgules (vide = auth off) |
| `REDIS_URL` | `redis://localhost:6379/0` | URL Redis |
| `RATE_LIMIT_PER_MINUTE` | `60` | Requêtes/min par clé |
| `CACHE_TTL` | `600` | TTL cache Redis (secondes) |
| `JOB_TIMEOUT` | `300` | Timeout scraping (secondes) |
| `JOB_RESULT_TTL` | `3600` | Rétention résultats (secondes) |
| `SCRAPER_HEADLESS` | `true` | Mode headless Playwright |
| `LOG_JSON` | `true` | Logs JSON structurés |
| `DEBUG` | `false` | Mode debug |

---

## Documentation interactive

- Swagger UI : `http://localhost:8000/docs`
- ReDoc : `http://localhost:8000/redoc`

---

## Structure du projet

```
api/
  config.py        Pydantic Settings (env vars)
  deps.py          Dépendances FastAPI (auth, Redis, rate limit)
  errors.py        Handlers exceptions → codes HTTP
  main.py          Factory app FastAPI
  schemas.py       Modèles Pydantic request/response
  routes/
    health.py      GET /health
    scrapes.py     POST + GET /v1/scrapes

worker/
  tasks.py         Tâche RQ : run_scrape_job()

app/               Logique métier (inchangée)
  core/            config, exceptions, health, log, models
  platforms/       Providers par plateforme (API + scraper)
  services/        social_resolver, health, bench

scrapers/          Couches Playwright / Botasaurus
models/            NormalizedPost, NormalizedProfile
```

---

## CLI (usage direct, préservé)

```bash
python main.py https://www.instagram.com/cristiano/ 10 --debug
python main.py --health
```
