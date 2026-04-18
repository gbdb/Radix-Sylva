# Contexte technique — Radix Sylva

## Rôle

- **Source de vérité** des données botaniques (Organism, Cultivar, CompanionRelation, Amendment, etc.).
- **API publique** `/api/v1/` (lecture). Écriture / sync avancée au fil des passes B/C.
- **Pas de GeoDjango** ; géométries éventuelles futures en JSON (comme BIOT).

## Documentation (dépôt)

- Index : **`docs/README.md`**
- Premier clone, PostgreSQL, `venv`, URLs locales : **`docs/installation-locale.md`**
- API sync (`/api/v1/sync/*`) : **`docs/api-sync.md`**
- Structure des données, sources, espèce vs cultivar, fusion multi-sources : **`docs/donnees-sources-et-modele.md`**
- Guide opérationnel (commandes `manage.py`, enchaînements, lien avec BIOT) : **`docs/gestion-des-donnees.md`**

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

État **prod** (mars 2026) — même droplet que **Jardin bIOT** ; voir aussi **`biot/docs/deploy-production-digitalocean-github.md`**.

| Élément | Valeur |
|--------|--------|
| **Fournisseur** | DigitalOcean |
| **Région** | Toronto |
| **Droplet** | Ubuntu 24.04 LTS |
| **IP publique** | `137.184.169.255` |
| **URL publique** | `https://radix.jardinbiot.ca` (admin : `/admin/`, API : `/api/v1/`) |
| **TLS** | Let’s Encrypt (Certbot + Nginx) |
| **PostgreSQL** | Sur le droplet (bases **`radixsylva`** / prod + staging selon config) |
| **Jardin bIOT (même serveur)** | `https://jardinbiot.ca` — base **`jardinbiot`** |
| **Code** | `/srv/radixsylva/` |
| **Venv** | `/srv/radixsylva/.venv/` |
| **App WSGI** | Gunicorn (socket local) |
| **systemd** | `radix-gunicorn.service` |
| **Reverse proxy** | Nginx → Gunicorn ; `/static/` → `staticfiles/` |
| **CI/CD** | GitHub Actions : push **`main`** → `git pull` + migrate + collectstatic + restart — secrets `DROPLET_IP`, `SSH_PRIVATE_KEY` |

Variables d’environnement, procédure de mise à jour et bonnes pratiques : **`docs/env-et-deploiement.md`**.

**Données / sync** — migration Mac → staging, staging → prod, sync BIOT : **`biot/docs/migration-donnees-radix-phase-1-5.md`**, **`docs/env-et-deploiement.md`**.

---

## Prochaines étapes

1. ~~Commandes `import_*` + enrichissement / mappings~~ (fait).
2. ~~API `/api/v1/sync/*` + déploiement public~~ (fait).
3. `docs/DATA_LICENSE.md` + politique photos (à compléter si besoin).
4. ~~Données prod + sync vers BIOT~~ (fait — ex. ~559 espèces côté API, cache BIOT via `sync_radixsylva`).
5. ~~Déploiement `jardinbiot.ca` + Radix sur le même droplet + GitHub Actions~~ (fait — **`biot/docs/deploy-production-digitalocean-github.md`**).
