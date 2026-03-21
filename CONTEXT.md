# Contexte technique — Radix Sylva

## Rôle

- **Source de vérité** des données botaniques (Organism, Cultivar, CompanionRelation, Amendment, etc.).
- **API publique** `/api/v1/` (lecture). Écriture / sync avancée au fil des passes B/C.
- **Pas de GeoDjango** ; géométries éventuelles futures en JSON (comme BIOT).

## Base de données

- **PostgreSQL** en production et **recommandé en dev** (`docker-compose.yml`, port host `5433`).
- SQLite possible pour un smoke test ; `SearchVectorField` dégrade en `TextField` (comme le catalogue BIOT).

## Tables

- Préfixe historique **`species_*`** pour compatibilité avec export `pg_dump` depuis Jardin bIOT.
- **Nouveau** : `species_organismphoto` (photos espèce, remplace à terme le lien vers `species.Photo` côté BIOT).
- **`species_dataimportrun`** : historique des imports botaniques (même nom de table que sous l’app `species` dans BIOT).

## Dépendances avec Jardin bIOT

- Les tags utilisateur (`UserTag`, `OrganismUserTag`) et l’inventaire semences (`SeedSupplier`, …) **restent dans BIOT**.
- `botanique/source_rules.py` est une copie de `biot/species/source_rules.py` avec import `slugify_latin` depuis `botanique.utils`.

## Prochaines étapes

1. ~~Commandes `import_*` + `enrichment.py` / `enrichment_score` / mappings~~ (fait).
2. Endpoints `GET /api/v1/sync/...` + auth par clé (`RADIX_SYLVA_SYNC_API_KEYS`) — Pass B.
3. `docs/DATA_LICENSE.md` + politique photos (à compléter avant public).
4. Données : export depuis BIOT ou `pg_dump` tables `species_*` (voir README — attention `photo_principale`).
