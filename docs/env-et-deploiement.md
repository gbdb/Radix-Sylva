# Variables d’environnement et déploiement — Radix Sylva

Ce document couvre : **SECRET_KEY** / **DATABASE_URL** (dev Mac), la **configuration serveur** DigitalOcean, le **fichier `.env`** requis en production, et la **procédure de mise à jour** (déploiement).

Résumé infra actuelle : voir aussi **`CONTEXT.md`** (section déploiement).

---

## 1. Fichier `.env` (racine du projet)

Django charge **`radixsylva/.env`** (à la racine du dépôt, à côté de `manage.py`). **Ne jamais commiter** ce fichier ; le modèle reste **`.env.example`**.

---

## 2. Variables obligatoires ou usuelles

| Variable | Rôle |
|----------|------|
| **`DATABASE_URL`** | Connexion PostgreSQL. **Oblatoire.** Un seul `DATABASE_URL` actif par environnement (dev Mac, staging, prod). |
| **`SECRET_KEY`** | Signature sessions Django / sécurité. **Oblatoire en production** ; générer une clé dédiée (ne pas réutiliser le dev). |
| **`DEBUG`** | `False` en production. |
| **`ALLOWED_HOSTS`** | Liste séparée par des virgules. Inclure `radix.jardinbiot.ca`, `localhost`, `127.0.0.1` selon le cas. |
| **`CORS_ALLOW_ALL_ORIGINS`** | Souvent `False` en prod si tu restreins les origines ; aligner avec les besoins de l’API / OpenAPI. |
| **`RADIX_SYLVA_SYNC_API_KEYS`** | Liste de clés (séparées par des virgules) pour l’en-tête `X-Radix-Sync-Key` sur `/api/v1/sync/*`. Vide = pas d’auth sur ces endpoints (acceptable seulement en dev isolé). |

Générer une `SECRET_KEY` :

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Exemples `DATABASE_URL`

**Dev Mac — Docker** (`docker-compose.yml`, port 5433) :

```text
postgres://radixsylva:radixsylva@127.0.0.1:5433/radixsylva
```

**Production sur le droplet** — PostgreSQL local au serveur, bases `radix_prod` ou `radix_staging`, utilisateur `radix` (adapter mot de passe et nom de base) :

```text
postgres://radix:MOT_DE_PASSE@127.0.0.1:5432/radix_prod
```

L’instance **Gunicorn** en production doit pointer vers **`radix_prod`** pour l’URL publique `https://radix.jardinbiot.ca`. Utiliser **`radix_staging`** pour des essais (migrations, imports lourds) en changeant temporairement `DATABASE_URL` ou avec un second déploiement / utilisateur système dédié.

### Mots de passe dans `.env` (PostgreSQL / `DATABASE_URL`)

Éviter les caractères **`#`** et **`!`** dans les mots de passe utilisés dans une URL `postgres://...` dans un fichier `.env` : certains parseurs ou shells les interprètent (commentaire ou historique), ce qui casse la connexion de façon peu visible. Préférer un mot de passe alphanumérique + `_` / `-`, ou utiliser le **pourcentage d’encodage URL** pour les caractères spéciaux.

---

## 3. Configuration serveur (référence — DigitalOcean)

Aligné sur le déploiement documenté dans **`CONTEXT.md`** :

| Composant | Détail |
|-----------|--------|
| OS | Ubuntu 24.04 LTS (Toronto) |
| Code | `/srv/radixsylva/` |
| Venv | `/srv/radixsylva/.venv/` |
| Fichier env | `/srv/radixsylva/.env` (permissions restrictives, ex. `chmod 600`) |
| Gunicorn | Écoute `127.0.0.1:8001`, app WSGI `radixsylva.wsgi:application` |
| systemd | `radix-gunicorn.service` |
| Nginx | Reverse proxy HTTPS vers Gunicorn ; TLS Let’s Encrypt |
| Fichiers statiques | `python manage.py collectstatic` → `staticfiles/` ; Nginx sert `/static/` |

Dépendance Python : **`gunicorn`** est listé dans **`requirements.txt`** (installation via `pip install -r requirements.txt` dans le venv).

---

## 4. Côté Jardin bIOT (sync cache)

L’API Radix en production est : **`https://radix.jardinbiot.ca/api/v1`**.

Dans le **`.env` à la racine du repo Jardin bIOT** (pas `mobile/.env`) :

```env
RADIX_SYLVA_API_URL=https://radix.jardinbiot.ca/api/v1
# Si Radix définit RADIX_SYLVA_SYNC_API_KEYS, même valeur ici :
# RADIX_SYLVA_SYNC_API_KEY=...
```

Checklist :

1. **HTTPS** : l’URL doit être en `https://` (certificat Let’s Encrypt côté Radix).
2. **Données servies par l’API** : tant que Gunicorn utilise **`DATABASE_URL` → `radix_prod`**, la sync BIOT récupère le contenu de **`radix_prod`**. Après avoir **copié `radix_staging` → `radix_prod`** (voir §7), redémarrer Gunicorn si tu as changé le `.env`.
3. Depuis la racine **BIOT** (venv activé) :

   ```bash
   python manage.py sync_radixsylva --full
   ```

   Première fois ou reset cache : `--full` ; ensuite sans `--full` pour les deltas.

4. Vérifier **`catalog.RadixSyncState`** en admin BIOT si besoin.

En **dev local uniquement** (Radix sur `runserver 8001`), tu peux garder `RADIX_SYLVA_API_URL=http://127.0.0.1:8001/api/v1` — ne pas mélanger avec la prod sur la même machine sans intention claire.

---

## 5. Procédure de mise à jour (déploiement)

À exécuter sur le **droplet** (utilisateur déployant l’app, souvent `radix` ou `sudo` selon ta config) :

```bash
cd /srv/radixsylva
source .venv/bin/activate
git pull origin main
# ou: git pull origin master  — selon la branche utilisée
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart radix-gunicorn
```

Vérifications rapides :

```bash
sudo systemctl status radix-gunicorn
curl -sI https://radix.jardinbiot.ca/api/v1/sync/meta/
```

En cas de changement de **Nginx** uniquement :

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### Après mise à jour des dépendances Python

Toujours `pip install -r requirements.txt` puis **redémarrer** `radix-gunicorn` pour charger le nouveau code / binaires.

---

## 6. Développement local avec Postgres « en ligne »

Tu peux éviter Postgres Docker sur le Mac en pointant `DATABASE_URL` vers le serveur **uniquement** si :

- le pare-feu **n’expose pas** le port 5432 au monde entier ; préférer **tunnel SSH** (`ssh -L 5433:127.0.0.1:5432 user@137.184.169.255`) puis `DATABASE_URL` vers `127.0.0.1:5433`, ou  
- **trusted sources** / IP autorisée (Managed DB) — ici Postgres est **local au droplet**, donc le tunnel SSH est le schéma habituel depuis le Mac.

Attention : travailler sur **`radix_prod`** depuis un poste de dev peut **endommager les données réelles** ; privilégier **`radix_staging`** pour les expérimentations.

---

## 7. Phase 1.5 — Migration données (état connu + staging → prod)

### État réalisé (référence)

| Base | Rôle | État typique après migration initiale |
|------|------|----------------------------------------|
| **`radix_staging`** | Copie depuis le Mac / essais | Données importées (ex. **~559 espèces** depuis la base locale), validation API |
| **`radix_prod`** | Données servies par `https://radix.jardinbiot.ca` | Schéma à jour, migrations appliquées, superuser créé ; **à remplir** par copie depuis staging une fois les données validées |

Guide détaillé Mac → staging : dépôt **Jardin bIOT**, **`docs/migration-donnees-radix-phase-1-5.md`**.

### Copier `radix_staging` → `radix_prod` (sur le droplet)

Quand le contenu de **staging** est validé (comptages, admin, smoke API) :

1. **Sauvegarde** optionnelle de `radix_prod` avant écrasement (`pg_dump` ou snapshot droplet).

2. Sur le serveur (exemple — adapte utilisateur système / mots de passe) :

   ```bash
   # Dump de staging (format custom, sans dépendre des rôles du Mac)
   sudo -u postgres pg_dump --format=custom --no-owner --no-privileges \
     --file=/tmp/radix_staging_to_prod.dump radix_staging

   # Recréer la base prod (destructif)
   sudo -u postgres psql -c "DROP DATABASE IF EXISTS radix_prod;"
   sudo -u postgres psql -c "CREATE DATABASE radix_prod OWNER radix;"

   # Restauration
   sudo -u postgres pg_restore --dbname=radix_prod --verbose \
     --no-owner --no-privileges --exit-on-error /tmp/radix_staging_to_prod.dump
   ```

3. Vérifier Django : `/srv/radixsylva/.env` avec **`DATABASE_URL`** pointant vers **`radix_prod`**, puis :

   ```bash
   cd /srv/radixsylva && source .venv/bin/activate
   python manage.py migrate
   sudo systemctl restart radix-gunicorn
   ```

4. Smoke : `https://radix.jardinbiot.ca/api/v1/organisms/` (compter / spot-check).

5. **BIOT** : `RADIX_SYLVA_API_URL=https://radix.jardinbiot.ca/api/v1` puis `sync_radixsylva` (voir §4).

Les options **`--no-owner`** et **`--no-privileges`** sur **`pg_dump`** et **`pg_restore`** évitent les erreurs liés aux rôles PostgreSQL qui n’existent pas sur le serveur (ex. rôle du Mac).

---

## 8. Pièges courants (PostgreSQL / `.env`)

| Problème | Piste |
|----------|--------|
| Erreurs de **rôle** au `pg_restore` | Utiliser `--no-owner --no-privileges` sur dump et restore ; propriétaire des bases = utilisateur serveur (`radix`). |
| Connexion Django impossible alors que le mot de passe est « juste » | Caractères **`#`** ou **`!`** dans le mot de passe brut dans `DATABASE_URL` / `.env` — changer le mot de passe ou encoder l’URL (voir §2). |
| Sync BIOT ne reflète pas staging | L’API publique lit **`radix_prod`** ; copier staging → prod d’abord (§7). |

---

## 9. Références

- **Prod conjointe BIOT + Radix (DO, GitHub Actions, `jardinbiot.ca`)** : dépôt **Jardin bIOT**, `docs/deploy-production-digitalocean-github.md`.
- Runbook détaillé (Nginx, Certbot, alternatives Managed DB) : dépôt **Jardin bIOT**, `docs/deploy-radix-digitalocean-runbook.md`.
- **Phase 1.5 — copier la base locale vers `radix_staging` sur le droplet** : dépôt **Jardin bIOT**, `docs/migration-donnees-radix-phase-1-5.md`.
- `CONTEXT.md` — section déploiement.
