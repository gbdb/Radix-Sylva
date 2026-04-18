# API publique et sync — Radix Sylva

## Pass A / B — état des lieux (technique)

- [x] Projet Django + app `botanique`
- [x] Modèles botaniques (`species_*` + `species_organismphoto` + `species_dataimportrun`)
- [x] `source_rules.py` (import slugify depuis `botanique.utils`)
- [x] API lecture `organisms`, `cultivars`, `amendments` + drf-spectacular (OpenAPI / Swagger)
- [x] Commandes d’import botaniques (`import_*`, `merge_*`, `populate_*`, `wipe_species`, `clean_organisms_keep_hq`, etc.)
- [x] `enrichment.py`, `enrichment_score.py`, `pfaf_mapping.py`, `ancestrale_mapping.py`
- [ ] `migrate_cultivar_organisms` — reste dans **Jardin bIOT** (réattribue des spécimens)
- [x] Endpoints sync `/api/v1/sync/*` — **Pass B** (meta, amendments, organisms, cultivars, companions, `deleted` réservé)

Plan global BIOT ↔ Radix : [plan-radix-biot-phases.md](../../biot/docs/plan-radix-biot-phases.md).

---

## Endpoints `/api/v1/sync/*` (cache Jardin bIOT)

Côté **Jardin bIOT**, la commande `python manage.py sync_radixsylva` consomme ces URLs pour mettre à jour les tables `species_*` locales.

| Méthode | Endpoint | Rôle |
|---------|----------|------|
| `GET` | `/api/v1/sync/meta/` | `server_time`, `schema_version` |
| `GET` | `/api/v1/sync/amendments/?since=&page=` | Filtre `date_ajout > since` |
| `GET` | `/api/v1/sync/organisms/?since=` | Filtre `date_modification > since` + noms, propriétés, usages, calendrier, amendements recommandés |
| `GET` | `/api/v1/sync/organisms/?organism_id=<pk>` | **Sync ciblée** : un seul organisme (ignore `since`) ; 0 ou 1 résultat — utilisé après une demande d’espèce (`missing-species-request`) côté BIOT |
| `GET` | `/api/v1/sync/cultivars/?since=` | Porte-greffes + pollinisateurs |
| `GET` | `/api/v1/sync/companions/?since=` | Filtre `date_ajout > since` (nouvelles relations) |
| `GET` | `/api/v1/sync/deleted/` | Réservé (listes vides en v1) |

### Authentification sync

Si `RADIX_SYLVA_SYNC_API_KEYS` est défini dans `.env` Radix, les clients doivent envoyer l’en-tête **`X-Radix-Sync-Key`** (une des clés listées). Côté BIOT, la variable **`RADIX_SYLVA_SYNC_API_KEY`** doit correspondre.

En développement isolé, laisser vide peut être acceptable ; en production, utiliser des clés fortes et restreindre l’accès réseau si possible.

Détails variables : [`env-et-deploiement.md`](env-et-deploiement.md).
