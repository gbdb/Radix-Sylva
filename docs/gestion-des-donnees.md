# Gestion des données — guide opérationnel (Radix Sylva)

Ce document décrit **où** et **comment** exécuter les commandes de chargement et de maintenance. Pour la structure des tables, les sources et les règles métier, voir **[donnees-sources-et-modele.md](donnees-sources-et-modele.md)**.

---

## 1. Où travailler

- **Imports de masse et maintenance du catalogue botanique** : dépôt **Radix Sylva**, répertoire du projet Django (ex. `cd /srv/radixsylva` en production, ou `cd radixsylva` en local).
- **Python** : environnement virtuel du projet (ex. `source .venv/bin/activate`).
- **Base** : PostgreSQL uniquement ; variable **`DATABASE_URL`** dans `.env` (voir **`env-et-deploiement.md`**).

Les commandes s’invquent avec :

```bash
python manage.py <commande> [options]
```

---

## 2. Prérequis

- Fichier **`.env`** avec au minimum `SECRET_KEY`, `DATABASE_URL`, et en prod `ALLOWED_HOSTS`, etc.
- **Certificats SSL** : pour les imports qui appellent des API HTTPS (Hydro-Québec, ITIS, VASCAN, …), en cas d’erreur SSL, préférer `pip install --upgrade certifi` ; certaines commandes proposent `--insecure` en dernier recours (ex. `import_hydroquebec`).
- **Fichiers sources optionnels** :
  - **PFAF** : fichier `.json`, `.csv` ou `.sqlite` acquis selon la licence PFAF (`import_pfaf --file …`).
  - **Hydro-Québec** : JSON téléchargé ou API ; `--file` si l’API Python est bloquée (TLS).
  - **VASCAN / USDA** : liste de noms (un par ligne) avec `--file` pour créer ou enrichir en masse.
  - **Villes (Québec, Montréal), TOPIC, Ancestrale, Arbres en ligne** : CSV selon les formats documentés dans chaque commande.

---

## 3. Enchaînement recommandé (après un ou plusieurs imports)

L’ordre des imports eux-mêmes est **largement libre** : chaque commande rattache ou crée des `Organism` par identifiants (TSN, VASCAN) ou par noms. En fin de série, il est utile de :

1. **`merge_organism_duplicates`** — après plusieurs sources, si des doublons (même espèce sous des lignes légèrement différentes) sont apparus. Toujours commencer par **`--dry-run`** pour prévisualiser.
2. **`populate_genus`** — si `genus` doit être recalculé à partir du nom latin (souvent déjà géré par les imports).
3. **`populate_proprietes_usage_calendrier`** — dérive les tables `OrganismPropriete`, `OrganismUsage`, `OrganismCalendrier` à partir des champs `Organism` et de `data_sources`.
4. **`rebuild_search_vectors`** — nécessaire après bulk import (le champ PostgreSQL `search_vector` n’est pas toujours mis à jour ligne à ligne).
5. **`update_enrichment_scores`** — recalcule `enrichment_score_pct` et les stats globales.

Exemples :

```bash
python manage.py merge_organism_duplicates --dry-run
python manage.py merge_organism_duplicates
python manage.py populate_proprietes_usage_calendrier
python manage.py rebuild_search_vectors
python manage.py update_enrichment_scores
```

---

## 4. Rappel des commandes d’import (liste)

Les détails et la philosophie de chaque source sont dans **[donnees-sources-et-modele.md](donnees-sources-et-modele.md)** § Sources. Noms des commandes :

| Commande | Rôle court |
|------------|------------|
| `import_hydroquebec` | Répertoire arbres HQ (API ou `--file` JSON). |
| `import_vascan` | API VASCAN — enrichissement ou `--file` pour créer depuis une liste. |
| `import_usda` | API ITIS — TSN et `data_sources['usda']`. |
| `import_usda_chars` | Caractéristiques USDA PLANTS (hauteur, floraison) — enrichissement strict, ne crée pas d’espèces. |
| `import_pfaf` | Fichier PFAF JSON/CSV/SQLite. |
| `import_botanipedia` | API MediaWiki Botanipedia. |
| `import_topic` | CSV Open Data Canada (TOPIC). |
| `import_arbres_quebec` | CSV Données Québec (arbres répertoriés). |
| `import_arbres_montreal` | CSV Montréal (arbres publics). |
| `import_arbres_en_ligne` | CSV trois colonnes (FR / latin / EN) + `OrganismNom`. |
| `import_ancestrale` | CSV pépinière (cultivars et porte-greffes). |
| `import_wikidata` | SPARQL — hauteur / largeur (fill gaps). |
| `import_wikimedia_photos` | Photos Wikidata / Commons. |

Autres commandes utiles : `clean_organisms_keep_hq`, `wipe_species` (destructif), `import_wikidata` / `import_wikimedia_photos` avec `--limit` et `--delay` pour respecter les APIs.

---

## 5. Page « Gestion des données » — Jardin bIOT

L’URL **`/admin/gestion-donnees/`** (staff) est implémentée dans le dépôt **Jardin bIOT**, pas dans Radix. Elle sert de **tableau de bord** pour le cache espèces côté application jardin :

- **Synchronisation** : commande **`sync_radixsylva`** (souvent avec `--full`), qui lit l’API Radix (`RADIX_SYLVA_API_URL`, typiquement `https://radix.jardinbiot.ca/api/v1`).
- **Maintenance locale** : par exemple **`rebuild_search_vectors`**, **`wipe_db_and_media`** (selon configuration exposée — voir `biot/docs/radix-biot-pass-c.md`).

Les **imports** listés au §4 ne sont **pas** lancés depuis cette page en production (Pass C) : ils s’exécutent sur **Radix** comme ci-dessus. Après un gros changement sur Radix, lancer **`sync_radixsylva`** sur le serveur BIOT (ou depuis un poste configuré) pour aligner le cache.

Variables utiles côté BIOT : `RADIX_SYLVA_API_URL`, éventuellement `RADIX_SYLVA_SYNC_API_KEY` si les clés sync sont activées sur Radix (`RADIX_SYLVA_SYNC_API_KEYS`).

---

## 6. Production (DigitalOcean)

- Code : `/srv/radixsylva/`, venv : `/srv/radixsylva/.venv/`.
- Exemple :  
  `sudo -u radix /srv/radixsylva/.venv/bin/python /srv/radixsylva/manage.py import_hydroquebec --limit 0`  
  (adapter l’utilisateur système selon l’installation.)

Redémarrage du service WSGI généralement **pas** requis après un import pur base de données ; il l’est après déploiement de code (`git pull`, migrations, `collectstatic`).

---

## 7. Voir aussi

- [donnees-sources-et-modele.md](donnees-sources-et-modele.md) — modèle, conflits, cultivars.
- [README.md](README.md) — index des docs.
- [DATA_LICENSE.md](DATA_LICENSE.md) — licences des agrégats et des sources.
