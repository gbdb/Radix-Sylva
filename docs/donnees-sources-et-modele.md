# Données, sources et modèle — Radix Sylva

Document de référence : **structure** des entités, **liste des sources** d’import actuelles, **espèce vs cultivar** (dont angle pépinière), **normalisation des noms de cultivars**, **gestion des conflits** entre sources, et **pistes** (listes IQDHO/FIHOQ, alias cultivars).  
Pour **exécuter** les commandes (chemins, enchaînements), voir **[gestion-des-donnees.md](gestion-des-donnees.md)**.

---

## 1. Rôle de Radix dans l’écosystème Jardin bIOT

- **Radix Sylva** est la **source de vérité** du catalogue botanique partagé : `Organism`, `Cultivar`, relations de compagnonnage, amendements, etc.
- **Jardin bIOT** conserve jardins, spécimens, utilisateurs, semences ; il **synchronise** une copie locale du catalogue via l’API (`sync_radixsylva`) pour l’app et l’admin.
- Les tables utilisent le préfixe historique **`species_*`** pour compatibilité avec d’anciens exports `pg_dump`.

---

## 2. Structure des données (vue d’ensemble)

### 2.1 Espèce — `Organism` (`species_espece`)

Une ligne par **taxon de base** utilisé comme fiche encyclopédique : noms (`nom_commun`, `nom_latin`, `slug_latin`), taxonomie (`famille`, `genus`, `tsn`, `vascan_id`), usages agronomiques (eau, soleil, sol, rusticité, etc.), textes (`description`, `notes`), et **`data_sources`** : dictionnaire JSON par identifiant de source (`hydroquebec`, `pfaf`, `vascan`, …) conservant des **blocs bruts** pour traçabilité et ré-import.

La **rusticité** est modélisée comme une **liste** dans `zone_rusticite` : chaque entrée est typiquement `{"zone": "4a", "source": "hydroquebec"}` — plusieurs sources peuvent coexister (voir §6).

### 2.2 Cultivar — `Cultivar` (`species_cultivar`)

Représente une **variété commerciale ou horticole** rattachée à une espèce : lien `organism` → `Organism`, `nom` (ex. `Honeycrisp`), `slug_cultivar` unique globalement. Champs optionnels : description, goût, couleur de fruit, résistance aux maladies, etc.

Tables associées : **`CultivarPorteGreffe`** (porte-greffe, vigueur, disponibilité par source), **`CultivarPollinator`** (pollinisateurs recommandés au niveau cultivar).

### 2.3 Tables satellite

- **`OrganismNom`** : noms alternatifs multilingues / par source (`Organism.nom_commun` reste le principal).
- **`OrganismPropriete`**, **`OrganismUsage`**, **`OrganismCalendrier`** : données détaillées **par source** (plusieurs lignes possibles par organisme).
- **`OrganismPhoto`** : galerie et photo principale ; métadonnées licence / auteur.
- **`CompanionRelation`**, **`Amendment`**, **`OrganismAmendment`** : compagnonnage et recommandations d’amendements.
- **`DataImportRun`** : historique des exécutions d’import (statut, stats).

### 2.4 Enrichissement

- Champ **`enrichment_score_pct`** sur `Organism` : score 0–100 % calculé à partir de la complétude des champs (voir `botanique/enrichment_score.py`). Recalcul via `update_enrichment_scores`.

---

## 3. Espèce vs cultivar — angle pépinière et usage du logiciel

En pépinière, l’achat se fait au niveau **cultivar** ou **commerciaux** (« Honeycrisp », « Spartan »), pas au niveau seul de l’épithète d’espèce (*Malus domestica*). Dans Radix :

- La **fiche encyclopédique de base** reste l’**espèce** (`Organism`) : rusticité générale, description, usages, sol — souvent communs à tous les cultivars du taxon.
- Le **cultivar** (`Cultivar`) porte la **spécificité** : nom commercial, caractères fruitiers, porte-greffes, pollinisation détaillée entre cultivars.

**Comment le code rattache les cultivars**

1. **Nom latin avec épithète entre guillemets simples** — ex. `Vaccinium corymbosum 'Bluecrop'`. Les fonctions `parse_cultivar_from_latin` et `find_organism_and_cultivar` dans `botanique/source_rules.py` séparent l’espèce de base et le nom de cultivar, créent ou retrouvent l’`Organism` et le `Cultivar` associé, avec un `slug_cultivar` dérivé de `slug_latin` + nom normalisé.

2. **Catalogues pépinière sans nom binomial complet** — ex. **`import_ancestrale`** : fichier CSV (une colonne texte du type `TypePlante Cultivar [Porte-greffe] [Âge]`). Un mapping **`ancestrale_mapping.TYPE_PLANTE_TO_NOM_LATIN`** relie un libellé court (ex. type de plante) au **nom latin** de l’espèce déjà présente en base. La commande **ne crée pas** d’`Organism` : si l’espèce n’existe pas, la ligne est ignorée (avec avertissement). Elle crée ou met à jour des **`Cultivar`** et **`CultivarPorteGreffe`**.

3. **Sources « grand public » ou flore** (Hydro, VASCAN, inventaires d’arbres) — souvent au niveau **espèce** ; les cultivars y sont rares ou implicites. Ils complètent la base pour l’identification et l’écologie, pas pour le catalogue complet des variétés vendues.

---

## 4. Normalisation des noms de cultivars entre catalogues

### 4.1 Ce qui est implémenté aujourd’hui

- **Unicité technique** : `get_unique_slug_cultivar` construit `slug_cultivar` = `{slug_latin}-{slug_du_nom}` avec `slugify_latin`, et ajoute un suffixe numérique en cas de collision.
- **Parsing** : détection d’un cultivar en **fin de nom latin** via motif `... 'Nom Cultivar'` (`parse_cultivar_from_latin`).
- **Matching d’espèces** : `normalize_latin_name` (minuscules, sans accents, espaces) et recherches fuzzy pour éviter les doublons d’`Organism` sur des variantes de graphie du nom scientifique.

### 4.2 Ce qui n’est pas encore couvert (pistes)

Les catalogues écrivent souvent le même cultivar différemment : `Honey Crisp`, `Honeycrisp`, `Malus domestica 'Honeycrisp'`, etc. Il n’existe **pas** aujourd’hui de table d’**alias** ni de règle de fusion « métier » entre ces variantes : deux graphies peuvent théoriquement produire deux slugs différents si elles arrivent par des canaux qui ne passent pas par le même parsing.

**Pistes possibles** (à valider produit / technique) :

- Table du type **`CultivarAlias`** (libellé normalisé, `cultivar_id`, `source`) pour rattacher les variantes catalogue à un même `Cultivar`.
- Règle de **canonicalisation** affichage : un seul « nom préféré » par cultivar, les alias en lecture seule.
- Matching **fuzzy** uniquement en **import** (suggestion ou fusion manuelle), pour éviter les fusions automatiques dangereuses entre homonymes.

Tant que ces pistes ne sont pas en place, la documentation opérationnelle consiste à **contrôler les fichiers source** et à utiliser `merge_organism_duplicates` côté espèce quand c’est pertinent.

---

## 5. Conflits entre sources (ex. zone 4 vs zone 5)

### 5.1 Principe général

- Chaque import met à jour `Organism` selon un mode **`MERGE_OVERWRITE`** ou **`MERGE_FILL_GAPS`** (ne remplir que les champs vides), selon la commande et le contexte.
- Les **données brutes** restent dans `data_sources[source_id]` pour audit.

### 5.2 Priorité par champ

Dans `botanique/source_rules.py`, le dictionnaire **`FIELD_PRIMARY_SOURCE`** indique quelle source **prime** pour certains champs « scalaires » quand on veut une seule valeur affichée ou une règle cohérente — ex. contexte québécois : **Hydro-Québec** pour `zone_rusticite`, besoins eau/soleil, sol, famille, description (liste indicative ; certains champs peuvent être ajustés au fil du temps).

### 5.3 Rusticité : plusieurs vérités + affichage prudent

- La liste **`zone_rusticite`** agrège des entrées **par source** via `merge_zones_rusticite` : une source ne remplace pas une autre ; elle met à jour sa propre entrée ou en ajoute une.
- Pour une **vue unique** « zone représentative », `Organism.get_primary_zone()` trie les zones (ordre USDA numérique + sous-zones a/b) et retient la **plus froide** — comportement **conservateur** pour le jardinier (analogue à l’ancienne logique `merge_zone_rusticite` sur chaînes).
- Exemple : un catalogue indique zone **5** et un autre zone **4** → les deux peuvent coexister dans le JSON ; la zone « primaire » affichée suivra la logique conservative (ici tendance vers le **4**).

### 5.4 Limites

Les conflits **nuancés** (ex. plage vs point, USDA vs échelle locale) ne sont pas résolus par un moteur de règles complet : la traçabilité par source et l’intervention manuelle ou une évolution future des règles restent possibles.

---

## 6. Sources d’import — tableau et paragraphes

Chaque paragraphe se termine par un renvoi au guide **[gestion-des-donnees.md](gestion-des-donnees.md)** pour l’exécution concrète.

| Source (clé typique) | Commande |
|----------------------|----------|
| Hydro-Québec | `import_hydroquebec` |
| VASCAN (Canadensys) | `import_vascan` |
| USDA / ITIS (TSN) | `import_usda` |
| USDA PLANTS (caractéristiques) | `import_usda_chars` |
| PFAF | `import_pfaf` |
| Botanipedia | `import_botanipedia` |
| TOPIC (Canada) | `import_topic` |
| Ville de Québec | `import_arbres_quebec` |
| Ville de Montréal | `import_arbres_montreal` |
| Arbres en ligne | `import_arbres_en_ligne` |
| Pépinière Ancestrale | `import_ancestrale` |
| Wikidata | `import_wikidata` |
| Wikimedia / Commons (photos) | `import_wikimedia_photos` |

### 6.1 Hydro-Québec (`hydroquebec`)

Import du répertoire d’arbres et arbustes (dimensions, sécurité, rusticité, sol, descriptions feuilles/fleurs/fruits, etc.). Utilise l’API ou un fichier JSON local (`--file`) si l’accès API pose problème (SSL). Options utiles : `--limit` (0 = tout), `--merge` overwrite vs fill_gaps, `--fetch-details`, `--enrich-from-api`, `--insecure` en dernier recours. Alimente massivement les champs `Organism` et `data_sources['hydroquebec']`. *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

### 6.2 VASCAN (`vascan`)

Interroge l’API de recherche Canadensys pour associer un **`vascan_id`** et des métadonnées (noms, distribution, statuts). Mode **`--enrich`** pour les organismes existants sans identifiant ; **`--file`** pour une liste de noms scientifiques (export checklist, tabulations). Pour les noms avec cultivar, la recherche retombe sur le **genre + espèce**. *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

### 6.3 USDA / ITIS (`usda`)

Enrichissement avec le **TSN** ITIS et données associées dans `data_sources['usda']`. Comportement analogue à VASCAN : **`--enrich`** ou **`--file`**. La recherche utilise le **genre + espèce** (sans auteur). *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

### 6.4 USDA PLANTS — caractéristiques (`usda_plants` dans le code)

`import_usda_chars` : hauteur, largeur, période de floraison vers `Organism` / `OrganismCalendrier`. **Strictement enrichissant** : ne crée **pas** de nouveaux organismes. API ou fichier CSV. *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

### 6.5 PFAF (`pfaf`)

Import depuis fichier **JSON, CSV ou SQLite** (table par défaut `plant_data`). Licence PFAF payante — n’utiliser que des fichiers acquis légalement. Défaut **`--merge=fill_gaps`** pour ne pas écraser les champs déjà remplis par Hydro. Mapping des colonnes via `pfaf_mapping.py`. *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

### 6.6 Botanipedia (`botanipedia`)

Enrichissement via l’API MediaWiki : recherche par nom latin, contenu de fiche dans `data_sources['botanipedia']`, complément de description / usages si vides (`--enrich`). Paramètres `--limit`, `--delay`, `--verbose`. *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

### 6.7 TOPIC — Traits of Plants in Canada (`topic`)

Import CSV depuis les jeux **Open Data Canada** (modules literature review ou empirical). Remplit notamment hauteur, largeur et lignes de calendrier en **fill_gaps**. *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

### 6.8 Ville de Québec (`ville_quebec`)

CSV **Arbres répertoriés** (colonnes `NOM_LATIN`, `NOM_FRANCAIS`). Associe les espèces présentes à l’inventaire urbain ; remplit `data_sources['ville_quebec']`. Options `--limit`, `--dry-run`. *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

### 6.9 Ville de Montréal (`ville_montreal`)

CSV **Arbres publics** ; colonnes variables (`ESSENCE`, `genre`/`espece`, etc.). Même idée : rattachement à des `Organism` et `data_sources['ville_montreal']`. *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

### 6.10 Arbres en ligne (`arbres_en_ligne`)

CSV à trois colonnes (`Version francaise`, `Traduction latin`, `Traduction Anglais`). Mode **create_only** pour les organismes dont le `slug_latin` n’existe pas encore ; alimente **`OrganismNom`** (FR + EN). *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

### 6.11 Pépinière Ancestrale (`ancestrale`)

CSV une colonne par ligne : type de plante, nom de cultivar, porte-greffe et âge parsés. Dépend du mapping type → nom latin et de la **présence préalable** de l’espèce en base. Crée / met à jour **`Cultivar`** et **`CultivarPorteGreffe`**. *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

### 6.12 Wikidata (`wikidata`)

Requêtes SPARQL pour **hauteur** et **largeur** (propriétés type P2048/P2049), mode **fill_gaps** sur les organismes existants. `--enrich`, `--limit`, `--delay`, `--dry-run`. *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

### 6.13 Wikimedia Commons / Wikidata — photos

`import_wikimedia_photos` : télécharge des images (feuillage, fleurs, fruits, racines) via Wikidata et Commons, avec **attribution** et licence. Options `--limit`, `--delay`, `--skip-existing` / `--no-skip`. *Exécution : [gestion-des-donnees.md](gestion-des-donnees.md).*

---

## 7. IQDHO, FIHOQ et listes professionnelles (analyse)

Les **listes de végétaux** diffusées par des organismes québécois tels que l’**IQDHO** (référence pour l’horticulture ornementale) et la **FIHOQ** (fédération sectorielle) sont souvent **plus proches du vocabulaire des pépiniéristes** (noms commerciaux, cultivars, porte-greffe) que les sites grand public ou la seule flore vasculaire.

**Intérêt potentiel pour Radix**

- Améliorer la **couverture cultivar** et l’**alignement** avec les commandes d’achat réelles au Québec.
- Servir de **pont** entre les noms de catalogue et les `Organism`/`Cultivar` internes (en complément de VASCAN/USDA, plutôt orientés taxonomie).

**Contraintes et précautions**

- **Licences et conditions d’usage** : vérifier pour chaque liste si la republication dans une base agrégée (même privée puis sync vers BIOT) est permise.
- **Format et fraîcheur** : PDF, tableur ou extrait web — coût de **parsing** et de maintenance.
- **Correspondance taxonomique** : les listes pro utilisent parfois des **noms commerciaux** ou des **synonymes** ; il faudrait une stratégie d’appariement (manuelle au début) et éventuellement la table d’alias cultivars (§4.2).

**Pistes d’intégration**

- Import **ponctuel** ou **récurrent** sous forme de nouvelle commande `import_*` dédiée, avec traçabilité dans `data_sources`.
- Appariement d’abord sur **`tsn` / `vascan_id` / `slug_latin`**, puis sur **nom de cultivar normalisé** + validation humaine pour les cas ambigus.

Aucune de ces intégrations n’est implémentée dans le code à ce jour ; ce paragraphe fixe le cadre de décision.

---

## 8. Fusion de doublons et qualité

- **`merge_organism_duplicates`** : regroupe les organismes qui partagent un nom latin normalisé (sans auteur) et un même nom commun ; fusionne les relations et tables liées. Utiliser **`--dry-run`** avant exécution réelle.
- **`clean_organisms_keep_hq`** : nettoyage ciblé (voir aide de la commande) selon les besoins de maintenance.

---

## 9. API et synchronisation vers Jardin bIOT

Les endpoints **`/api/v1/sync/*`** exposent organismes (avec données liées), cultivars, amendements, compagnonnage, etc., avec filtrage temporel (`since`). Côté BIOT, **`sync_radixsylva`** matérialise le cache local. Les clés optionnelles `RADIX_SYLVA_SYNC_API_KEYS` / `RADIX_SYLVA_SYNC_API_KEY` sécurisent l’accès.

---

## 10. Licences

Voir **[DATA_LICENSE.md](DATA_LICENSE.md)** : distinction entre agrégation projet, licences par source et métadonnées des médias.

---

## 11. Fichiers code clés

- `botanique/models.py` — modèles.
- `botanique/source_rules.py` — fusion, matching, cultivars, zones.
- `botanique/management/commands/import_*.py` — imports.
- `botanique/enrichment_score.py` — score de complétude.
- `botanique/sync_payload.py` / `sync_views.py` — charge utile de synchronisation API.
