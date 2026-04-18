# Installation locale — Radix Sylva

Ce guide complète le [README](../README.md) : prérequis machine, PostgreSQL (Docker ou natif), premier `venv`, migrations et URLs utiles en développement.

Les **paquets Python** sont listés dans [`../requirements.txt`](../requirements.txt) (versions pinées ou bornées).

---

## Prérequis

- **Python 3.11+**
- **PostgreSQL obligatoire** pour la base Django (plus de SQLite — aligné production et index `search_vector`).

**Fichiers PFAF au format `.sqlite`** : fichiers **sources** pour la commande `import_pfaf`, pas la base Django.

Variables d’environnement (`SECRET_KEY`, `DATABASE_URL`, etc.) : [`env-et-deploiement.md`](env-et-deploiement.md).

Si les dépôts **Jardin bIOT** et **Radix** sont côte à côte : ports **5434** (BIOT) et **5433** (Radix), alignement des `.env` — [dev-env-local-biot-radix.md](../../biot/docs/dev-env-local-biot-radix.md).

---

## PostgreSQL : Docker ou sans Docker

### Option A — Docker Desktop (recommandé sur Mac)

1. Installer [Docker Desktop pour Mac](https://www.docker.com/products/docker-desktop/).
2. Lancer l’application une fois (icône dans la barre de menu).
3. Dans le répertoire `radixsylva/` : `docker compose up -d`
4. Dans `.env` :

```text
DATABASE_URL=postgres://radixsylva:radixsylva@127.0.0.1:5433/radixsylva
```

### Option B — PostgreSQL sans Docker (ex. Homebrew)

```bash
brew install postgresql@16
brew services start postgresql@16
createuser -s radixsylva   # ou utilisateur + mot de passe via psql selon ta config
createdb -O radixsylva radixsylva
```

Puis dans `.env` (adapter utilisateur, mot de passe, port ; souvent **5432** pour Postgres local) :

```text
DATABASE_URL=postgres://radixsylva:TON_MOT_DE_PASSE@127.0.0.1:5432/radixsylva
```

### Si la commande `docker` est introuvable

Tu n’as pas Docker installé : utilise l’**option B** ci-dessus ou installe Docker (option A).

---

## Configuration initiale

```bash
cd radixsylva
python3 -m venv .venv
source .venv/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Éditer .env : au minimum DATABASE_URL (voir ci-dessus)
```

---

## Migrations et serveur de développement

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8001
```

| Ressource | URL locale |
|-----------|------------|
| Admin Django | http://127.0.0.1:8001/admin/ |
| API (exemple) | http://127.0.0.1:8001/api/v1/organisms/ |
| Schéma OpenAPI | http://127.0.0.1:8001/api/v1/schema/ |
| Swagger | http://127.0.0.1:8001/api/v1/docs/ |

---

## Migration de données depuis Jardin bIOT

- Contexte technique et procédures : [`../CONTEXT.md`](../CONTEXT.md) (pg_dump des tables `species_*`, etc.).
- **Attention** : l’historique des photos peut différer (`species_espece.photo_principale_id` → `species_organismphoto` côté Radix) ; migration dédiée à planifier si besoin.
- Déploiement staging / prod : [migration-donnees-radix-phase-1-5.md](../../biot/docs/migration-donnees-radix-phase-1-5.md) (dépôt BIOT, repos côte à côte).
