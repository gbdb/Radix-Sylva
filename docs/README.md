# Documentation — Radix Sylva

Index des documents du répertoire `docs/` (hors déploiement ponctuel).

| Document | Contenu |
|----------|---------|
| [**installation-locale.md**](installation-locale.md) | Premier clone : Python, PostgreSQL (Docker ou natif), `venv`, `migrate`, URLs dev. |
| [**api-sync.md**](api-sync.md) | Pass A/B, endpoints `/api/v1/sync/*`, en-tête `X-Radix-Sync-Key`. |
| [**donnees-sources-et-modele.md**](donnees-sources-et-modele.md) | Structure des données (`Organism`, `Cultivar`, sources, fusion multi-sources), espèce vs cultivar, normalisation des noms, conflits, pistes (IQDHO/FIHOQ), et **un paragraphe par source d’import** avec renvoi au guide opérationnel. |
| [**gestion-des-donnees.md**](gestion-des-donnees.md) | Guide **strictement opérationnel** : où exécuter les commandes, prérequis, enchaînements recommandés après import, et rôle de la page « Gestion des données » côté Jardin bIOT (`sync_radixsylva`). |
| [**DATA_LICENSE.md**](DATA_LICENSE.md) | Brouillon — licences agrégées vs sources, photos. |
| [**deploy-digitalocean.md**](deploy-digitalocean.md) | Déploiement DigitalOcean (point d’entrée ; détails aussi dans `CONTEXT.md` à la racine du dépôt). |
| [**env-et-deploiement.md**](env-et-deploiement.md) | Variables d’environnement et bonnes pratiques prod. |

Contexte technique rapide : voir aussi [`../CONTEXT.md`](../CONTEXT.md) et [`../README.md`](../README.md) à la racine du dépôt.

**Jardin bIOT** consomme l’API et la sync (`sync_radixsylva`) : documentation dans le dépôt **biot** (`README`, dossier `docs/`, notamment [plan-radix-biot-phases.md](https://github.com/gbdb/biot/blob/main/docs/plan-radix-biot-phases.md) sur GitHub).
