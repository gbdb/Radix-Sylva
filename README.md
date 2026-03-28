# Radix Sylva

Base de données botanique publique (monde tempéré, focus Québec/Canada).  
Projet Django séparé de **Jardin bIOT** — **Pass A** : squelette + modèles + API lecture + OpenAPI.

**Prod** : `https://radix.jardinbiot.ca`. Infra : [`docs/deploy-digitalocean.md`](docs/deploy-digitalocean.md) (runbook **Jardin bIOT** : `biot/docs/deploy-radix-digitalocean-runbook.md`) ; plan global : `biot/docs/plan-radix-biot-phases.md`.

## Documentation

| Document | Rôle |
|----------|------|
| [`docs/README.md`](docs/README.md) | Index des fichiers dans `docs/`. |
| [`docs/donnees-sources-et-modele.md`](docs/donnees-sources-et-modele.md) | Modèle de données, liste des sources d’import, réflexions (cultivars, conflits, pistes IQDHO/FIHOQ). |
| [`docs/gestion-des-donnees.md`](docs/gestion-des-donnees.md) | **Opérationnel** : où et comment lancer les imports et la maintenance. |

## Prérequis

- Python 3.11+
- **PostgreSQL obligatoire** (plus de SQLite pour la base Django — aligné prod + `search_vector`).

**Fichiers PFAF au format `.sqlite`** : ce sont des **fichiers source** pour l’import (`import_pfaf`), pas la base Django.

### Si `docker: command not found`

Tu n’as pas Docker installé (normal sur beaucoup de Mac). Deux options :

**A — Docker Desktop (recommandé)**  
1. Installe [Docker Desktop pour Mac](https://www.docker.com/products/docker-desktop/).  
2. Ouvre l’app une fois (icône baleine dans la barre de menu).  
3. Dans `radixsylva/` : `docker compose up -d`  
4. Dans `.env` :  
   `DATABASE_URL=postgres://radixsylva:radixsylva@127.0.0.1:5433/radixsylva`

**B — PostgreSQL sans Docker (Homebrew)**  

```bash
brew install postgresql@16
brew services start postgresql@16
createuser -s radixsylva  # ou via psql : utilisateur + mot de passe selon ta config
createdb -O radixsylva radixsylva
```

Puis dans `.env` (adapte user/mot de passe/port ; souvent port **5432**) :  
`DATABASE_URL=postgres://radixsylva:TON_MOT_DE_PASSE@127.0.0.1:5432/radixsylva`

Variables d’environnement (SECRET_KEY, `DATABASE_URL` local vs cloud) : voir **`docs/env-et-deploiement.md`**.  
Si les repos **BIOT** et **Radix** sont côte à côte : alignement des `.env` et ports **5434 / 5433** → [`../biot/docs/dev-env-local-biot-radix.md`](../biot/docs/dev-env-local-biot-radix.md).

## Configuration

```bash
cd radixsylva
python3 -m venv .venv
source .venv/bin/activate  # ou .venv\Scripts\activate sur Windows
pip install -r requirements.txt
cp .env.example .env
# Optionnel : DATABASE_URL pour Postgres (Docker port 5433 ou Homebrew 5432)
```

## Migrations

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8001
```

- Admin : http://127.0.0.1:8001/admin/
- API : http://127.0.0.1:8001/api/v1/organisms/
- OpenAPI : http://127.0.0.1:8001/api/v1/schema/
- Swagger : http://127.0.0.1:8001/api/v1/docs/

## Pass A — statut

- [x] Projet Django + app `botanique`
- [x] Modèles botaniques (`species_*` + `species_organismphoto` + `species_dataimportrun`)
- [x] `source_rules.py` (import slugify depuis `botanique.utils`)
- [x] API lecture `organisms`, `cultivars`, `amendments` + drf-spectacular
- [x] Commandes d’import botaniques (`import_*`, `merge_*`, `populate_*`, `wipe_species`, `clean_organisms_keep_hq`, etc.)
- [x] `enrichment.py`, `enrichment_score.py`, `pfaf_mapping.py`, `ancestrale_mapping.py`
- [ ] `migrate_cultivar_organisms` — reste dans **Jardin bIOT** (réattribue des spécimens)
- [x] Endpoints sync `/api/v1/sync/*` — **Pass B** (meta, amendments, organisms, cultivars, companions, deleted vide)

### API sync (cache Jardin bIOT)

- `GET /api/v1/sync/meta/` — `server_time`, `schema_version`
- `GET /api/v1/sync/amendments/?since=&page=` — filtre `date_ajout > since`
- `GET /api/v1/sync/organisms/?since=` — filtre `date_modification > since` + noms, propriétés, usages, calendrier, amendements recommandés
- `GET /api/v1/sync/cultivars/?since=` — porte-greffes + pollinisateurs
- `GET /api/v1/sync/companions/?since=` — filtre `date_ajout > since` (nouvelles relations)
- `GET /api/v1/sync/deleted/` — réservé (listes vides en v1)

Si `RADIX_SYLVA_SYNC_API_KEYS` est défini dans `.env`, envoyer l’en-tête `X-Radix-Sync-Key` (même valeur côté BIOT : `RADIX_SYLVA_SYNC_API_KEY`).

## Import des données depuis Jardin bIOT

Voir `CONTEXT.md` (pg_dump des tables `species_*` ou export JSON dédié).  
**Attention** : la colonne `species_espece.photo_principale_id` pointait vers `species_photo` dans BIOT ; ici elle pointe vers `species_organismphoto` — migration données photos à planifier (script dédié).

**Migration vers le serveur DigitalOcean (staging / prod)** : guide détaillé dans le dépôt Jardin bIOT — [`docs/migration-donnees-radix-phase-1-5.md`](../biot/docs/migration-donnees-radix-phase-1-5.md) (si les deux repos sont côte à côte).
