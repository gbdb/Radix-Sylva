# Contexte technique — Radix Sylva

## Rôle

- **Source de vérité** des données botaniques (Organism, Cultivar, CompanionRelation, Amendment, etc.).
- **API publique** `/api/v1/` (lecture). Écriture / sync avancée au fil des passes B/C.
- **Pas de GeoDjango** ; géométries éventuelles futures en JSON (comme BIOT).

## Base de données

- **PostgreSQL obligatoire** en dev et prod (`DATABASE_URL` dans `.env`). Docker local : `docker-compose.yml`, port host `5433`.

## Tables

- Préfixe historique **`species_*`** pour compatibilité avec export `pg_dump` depuis Jardin bIOT.
- **Nouveau** : `species_organismphoto` (photos espèce, remplace à terme le lien vers `species.Photo` côté BIOT).
- **`species_dataimportrun`** : historique des imports botaniques (même nom de table que sous l’app `species` dans BIOT).

## Dépendances avec Jardin bIOT

- Les tags utilisateur (`UserTag`, `OrganismUserTag`) et l’inventaire semences (`SeedSupplier`, …) **restent dans BIOT**.
- `botanique/source_rules.py` est une copie de `biot/species/source_rules.py` avec import `slugify_latin` depuis `botanique.utils`.

---

## Déploiement production (DigitalOcean)

État au **déploiement initial** (à maintenir à jour si l’infra change) :

| Élément | Valeur |
|--------|--------|
| **Fournisseur** | DigitalOcean |
| **Région** | Toronto |
| **Droplet** | Ubuntu 24.04 LTS |
| **IP publique** | `137.184.169.255` |
| **URL publique** | `https://radix.jardinbiot.ca` (admin : `/admin/`) |
| **TLS** | Let’s Encrypt (Certbot + Nginx) |
| **PostgreSQL** | Installé **sur le droplet** (pas Managed DB) ; utilisateur DB : `radix` |
| **Bases** | `radix_staging` (données importées depuis le Mac, ex. ~559 espèces — validation), `radix_prod` (schéma prêt ; **à alimenter** par copie staging→prod quand validé) |
| **Code** | `/srv/radixsylva/` |
| **Venv** | `/srv/radixsylva/.venv/` |
| **App WSGI** | Gunicorn, **port local** `127.0.0.1:8001` |
| **systemd** | `radix-gunicorn.service` |
| **Reverse proxy** | Nginx → Gunicorn ; fichiers statiques servis par Nginx (`/static/` → `staticfiles/`) |

Variables d’environnement, procédure de mise à jour et bonnes pratiques : **`docs/env-et-deploiement.md`**.

**Phase 1.5 (données)** — Mac → **`radix_staging`** : **`biot/docs/migration-donnees-radix-phase-1-5.md`**. Puis **`radix_staging` → `radix_prod`**, BIOT en **`https://radix.jardinbiot.ca/api/v1`** : **`docs/env-et-deploiement.md`** (§4, §7, §8).

---

## Prochaines étapes

1. ~~Commandes `import_*` + `enrichment.py` / `enrichment_score` / mappings~~ (fait).
2. Endpoints `GET /api/v1/sync/...` + auth par clé (`RADIX_SYLVA_SYNC_API_KEYS`) — Pass B.
3. `docs/DATA_LICENSE.md` + politique photos (à compléter avant public).
4. Données : **staging** OK (import Mac) ; **copier staging → prod** puis BIOT `sync_radixsylva` — **`docs/env-et-deploiement.md`** §7 ; guide Mac → staging : **`biot/docs/migration-donnees-radix-phase-1-5.md`**.
5. ~~Déploiement public sous-domaine `jardinbiot.ca`~~ (fait — voir section ci-dessus).
