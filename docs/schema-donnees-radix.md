# Schéma de données — Radix Sylva

Document généré à partir des modèles Django de l’application `botanique` (`botanique/models.py`). Les noms de tables PostgreSQL sont indiqués quand ils diffèrent du nom de modèle (préfixe historique `species_*` pour compatibilité avec Jardin bIOT / imports).

---

## Vue d’ensemble des tables métier

| Modèle Django | Table PostgreSQL | Rôle |
|---------------|------------------|------|
| `Organism` | `species_espece` | Espèce botanique (ligne principale) |
| `OrganismPhoto` | `species_organismphoto` | Photos de référence (galerie) |
| `OrganismNom` | `species_organismnom` | Noms alternatifs (multilingue / source) |
| `OrganismPropriete` | `species_organismpropriete` | Propriétés sol / exposition par source |
| `OrganismUsage` | `species_organismusage` | Usages typés (comestible, médicinal, etc.) |
| `OrganismCalendrier` | `species_organismcalendrier` | Périodes (floraison, récolte, etc.) |
| `OrganismAmendment` | `species_organismamendment` | Lien organisme ↔ amendement recommandé |
| `CompanionRelation` | `species_companionrelation` | Compagnonnage entre espèces |
| `Cultivar` | `species_cultivar` | Cultivars rattachés à une espèce |
| `CultivarPollinator` | `species_cultivar_pollinator` | Pollinisateurs au niveau cultivar |
| `CultivarPorteGreffe` | `species_cultivarportegreffe` | Porte-greffes par cultivar |
| `Amendment` | `species_amendment` | Catalogue d’amendements |
| `BaseEnrichmentStats` | `species_base_enrichment_stats` | Singleton stats d’enrichissement global |
| `DataImportRun` | `species_dataimportrun` | Journal des imports / commandes |

Tables Django standard (hors `botanique`) : `auth_user`, `auth_group`, `auth_permission`, `django_session`, `django_admin_log`, `django_content_type`, migrations, etc.

---

## `Organism` → table `species_espece`

Espèce : une ligne par taxon au niveau prévu par Radix (souvent espèce).

| Champ | Type | Nullable / défaut | Notes |
|-------|------|-------------------|--------|
| `id` | BigAutoField (PK) | auto | |
| `nom_commun` | CharField(200) | | indexé |
| `nom_latin` | CharField(200) | | indexé |
| `slug_latin` | SlugField(220) | unique, blank, null | dérivé du nom latin si vide |
| `tsn` | PositiveIntegerField | unique, null, blank | ITIS/USDA |
| `vascan_id` | PositiveIntegerField | unique, null, blank | VASCAN |
| `famille` | CharField(100) | blank | indexé |
| `genus` | CharField(80) | blank | indexé |
| `regne` | CharField(20) | défaut `plante` | choix : `plante`, `champignon`, `mousse` |
| `type_organisme` | CharField(30) | | choix : arbre fruitier, vivace, légume, etc. (voir modèle) |
| `besoin_eau` | CharField(15) | défaut `moyen`, blank | `tres_faible` … `tres_eleve` |
| `besoin_soleil` | CharField(20) | défaut `plein_soleil`, blank | ombre → plein soleil |
| `zone_rusticite` | JSONField | `[]`, blank | liste de zones avec source |
| `sol_textures` | JSONField | `[]`, blank | textures acceptées |
| `sol_ph` | JSONField | `[]`, blank | pH acceptés |
| `sol_drainage` | CharField(20) | blank | drainage |
| `sol_richesse` | CharField(20) | blank | pauvre / moyen / riche |
| `hauteur_max` | FloatField | null, blank | mètres |
| `largeur_max` | FloatField | null, blank | mètres |
| `vitesse_croissance` | CharField(20) | blank | lente → très rapide |
| `comestible` | BooleanField | défaut True | indexé |
| `parties_comestibles` | TextField | blank | texte libre |
| `toxicite` | TextField | blank | parties toxiques, précautions |
| `type_noix` | CharField(20) | blank | si pertinent (noyer, noisetier, …) |
| `age_fructification` | IntegerField | null, blank | années avant première fructification |
| `periode_recolte` | CharField(100) | blank | |
| `pollinisation` | TextField | blank | |
| `distance_pollinisation_max` | FloatField | null, blank | mètres |
| `production_annuelle` | CharField(100) | blank | |
| `fixateur_azote` | BooleanField | défaut False | indexé |
| `accumulateur_dynamique` | BooleanField | défaut False | |
| `mellifere` | BooleanField | défaut False | indexé |
| `produit_juglone` | BooleanField | défaut False | |
| `indigene` | BooleanField | défaut False | indexé |
| `description` | TextField | blank | |
| `notes` | TextField | blank | |
| `usages_autres` | TextField | blank | usages non comestibles |
| `data_sources` | JSONField | `{}`, blank | blocs par source externe |
| `photo_principale_id` | FK → OrganismPhoto | null, blank | SET_NULL |
| `enrichment_score_pct` | PositiveSmallIntegerField | null, blank | 0–100 % |
| `date_ajout` | DateTimeField | auto_now_add | |
| `date_modification` | DateTimeField | auto_now | |
| `search_vector` | SearchVectorField (PG) ou TextField | null, blank | recherche plein texte (GIN sur PG) |

**Champs PFAF / import — correspondance actuelle**

Le fichier `botanique/pfaf_mapping.py` mappe des colonnes PFAF vers des concepts Radix, **sans colonnes dédiées** pour des notes d’usages comestibles séparées ni pour des notes « known hazards » distinctes de la toxicité :

- `edible_parts` / `edible_uses` (alias) → concept **`parties_comestibles`** (et flux d’import vers ce champ selon la commande d’import).
- `uses`, `medicinal`, `other_uses` → **`usages_autres`** (agrégation textuelle côté mapping).
- `known_hazards` → **`toxicite`**.

Il n’existe **pas** dans le modèle de champs scalaires `edibility_rating`, `medicinal_rating`, ni un champ nommé `edible_uses_notes` ou `known_hazards` : pour le texte des dangers, c’est **`toxicite`** qui sert de réceptacle.

---

## `OrganismPhoto` → `species_organismphoto`

| Champ | Type | Notes |
|-------|------|--------|
| `id` | PK | |
| `organism_id` | FK Organism | null, CASCADE |
| `image` | ImageField | `organism_photos/%Y/%m/` |
| `type_photo` | CharField(40) | blank |
| `titre` | CharField(200) | blank |
| `description` | TextField | blank |
| `date_prise` | DateField | null, blank |
| `source_url` | URLField | blank |
| `source_author` | CharField(200) | blank |
| `source_license` | CharField(50) | blank |
| `date_ajout` | DateTimeField | auto_now_add |

---

## `OrganismNom` → `species_organismnom`

| Champ | Type |
|-------|------|
| `id` | PK |
| `organism_id` | FK Organism, CASCADE |
| `nom` | CharField(200) |
| `langue` | `fr` / `en` / `autre` |
| `source` | CharField(80) |
| `principal` | BooleanField, défaut False |

---

## `OrganismPropriete` → `species_organismpropriete`

| Champ | Type |
|-------|------|
| `id` | PK |
| `organisme_id` | FK Organism, CASCADE |
| `type_sol` | JSONField, default list |
| `ph_min`, `ph_max` | FloatField, null |
| `tolerance_ombre` | CharField, choix exposition |
| `source` | CharField(50), blank |

---

## `OrganismUsage` → `species_organismusage`

| Champ | Type |
|-------|------|
| `id` | PK |
| `organisme_id` | FK Organism, CASCADE |
| `type_usage` | CharField(30) | comestible (fruit, feuille, …), médicinal, bois, ornement, autre |
| `parties` | CharField(200), blank |
| `description` | TextField, blank |
| `source` | CharField(50), blank |

---

## `OrganismCalendrier` → `species_organismcalendrier`

| Champ | Type |
|-------|------|
| `id` | PK |
| `organisme_id` | FK Organism, CASCADE |
| `type_periode` | floraison, fructification, récolte, semis, taille, autre |
| `mois_debut`, `mois_fin` | PositiveSmallIntegerField 1–12, null |
| `source` | CharField(50), blank |

---

## `CompanionRelation` → `species_companionrelation`

| Champ | Type |
|-------|------|
| `id` | PK |
| `organisme_source_id`, `organisme_cible_id` | FK Organism, CASCADE |
| `type_relation` | CharField(30) | compagnon positif, allélopathie, etc. |
| `force` | IntegerField, défaut 5 (1–10) |
| `distance_optimale` | FloatField, null |
| `description` | TextField, blank |
| `source_info` | CharField(200), blank |
| `date_ajout` | DateTimeField, auto_now_add |

Contrainte d’unicité : (`organisme_source`, `organisme_cible`, `type_relation`).

---

## `Cultivar` → `species_cultivar`

| Champ | Type |
|-------|------|
| `id` | PK |
| `organism_id` | FK Organism, CASCADE |
| `slug_cultivar` | SlugField(250), unique |
| `nom` | CharField(200) |
| `description` | TextField, blank |
| `couleur_fruit` | CharField(100), blank |
| `gout` | CharField(200), blank |
| `resistance_maladies` | TextField, blank |
| `notes` | TextField, blank |
| `date_ajout`, `date_modification` | DateTimeField |

---

## `CultivarPollinator` → `species_cultivar_pollinator`

| Champ | Type |
|-------|------|
| `id` | PK |
| `cultivar_id` | FK Cultivar, CASCADE |
| `companion_cultivar_id` | FK Cultivar, null |
| `companion_organism_id` | FK Organism, null |
| `notes` | TextField, blank |
| `source` | CharField(200), blank |

Contrainte : au moins un des deux compagnons doit être renseigné.

---

## `CultivarPorteGreffe` → `species_cultivarportegreffe`

| Champ | Type |
|-------|------|
| `id` | PK |
| `cultivar_id` | FK Cultivar, CASCADE |
| `nom_porte_greffe` | CharField(100) |
| `vigueur` | CharField(20), choix nain → standard, blank |
| `hauteur_max_m` | FloatField, null |
| `notes` | TextField, blank |
| `source` | CharField(80) |
| `disponible_chez` | JSONField, default list |

---

## `Amendment` → `species_amendment`

| Champ | Type |
|-------|------|
| `id` | PK |
| `nom` | CharField(200) |
| `type_amendment` | CharField(25), choix compost, fumier, minéraux, etc. |
| `azote_n`, `phosphore_p`, `potassium_k` | FloatField, null |
| `effet_ph` | CharField(15), blank |
| `bon_pour_sols`, `bon_pour_types` | JSONField, default list |
| `description` | TextField, blank |
| `dose_recommandee`, `periode_application` | CharField(200), blank |
| `biologique` | BooleanField, défaut True |
| `date_ajout` | DateTimeField, auto_now_add |

---

## `OrganismAmendment` → `species_organismamendment`

| Champ | Type |
|-------|------|
| `id` | PK |
| `organisme_id` | FK Organism, CASCADE |
| `amendment_id` | FK Amendment, CASCADE |
| `priorite` | IntegerField, choix 1–4 (recommandé → à éviter) |
| `dose_specifique`, `moment_application` | CharField(200), blank |
| `notes` | TextField, blank |
| `date_ajout` | DateTimeField, auto_now_add |

`unique_together` : (`organisme`, `amendment`).

---

## `BaseEnrichmentStats` → `species_base_enrichment_stats`

| Champ | Type |
|-------|------|
| `id` | PK |
| `global_score_pct` | PositiveSmallIntegerField, null |
| `organism_count` | PositiveIntegerField, défaut 0 |
| `last_updated` | DateTimeField, auto_now |
| `computed_at` | DateTimeField, null |

---

## `DataImportRun` → `species_dataimportrun`

| Champ | Type |
|-------|------|
| `id` | PK |
| `source` | CharField(80), choix (pfaf, seeds, import_vascan, …) |
| `status` | `running` / `success` / `failure` |
| `started_at` | DateTimeField, auto_now_add |
| `finished_at` | DateTimeField, null |
| `stats` | JSONField, default dict |
| `output_snippet` | TextField, blank |
| `trigger` | admin_import, gestion_donnees, api |
| `user_id` | FK User, SET_NULL, null |

---

## Champs Organism et import PFAF (FAQ)

| Besoin PFAF / données | Présent sur `Organism` ? | Recommandation |
|------------------------|---------------------------|----------------|
| **edibility_rating (0–5)** | Non | Ajouter une migration (`PositiveSmallIntegerField` + validators 0–5), ou stocker sous une clé dans `data_sources` (ex. `data_sources['pfaf']['edibility_rating']`) sans colonne dédiée. |
| **medicinal_rating** | Non | Idem : migration ou `data_sources`. |
| **edible_uses_notes** (texte long usages comestibles) | Pas de champ dénommé ainsi | Utiliser **`parties_comestibles`** et/ou des lignes **`OrganismUsage`** (types comestibles). Pour garder une note PFAF brute séparée, prévoir un nouveau champ ou une sous-clé JSON dans `data_sources`. |
| **known_hazards** | Pas de colonne `known_hazards` | Le mapping PFAF envoie ce contenu vers **`toxicite`**. Si vous voulez deux champs distincts (toxicité vs « hazards » PFAF), il faudrait une migration ou du JSON. |

En résumé : les **notes de dangers PFAF** peuvent être importées dans **`toxicite`** sans migration. Les **notes d’usages comestibles** peuvent aller dans **`parties_comestibles`** / **`OrganismUsage`**. Les **notations numériques 0–5** (comestibilité, médicinal) **n’existent pas** sur le modèle : il faut **migration** (ou stockage dans **`data_sources`**) si vous voulez les requêter / indexer proprement en SQL.

---

## Sync API (Jardin bIOT)

Les champs scalaires synchronisés pour `Organism` sont listés dans `botanique/sync_payload.py` (`ORGANISM_SYNC_FIELDS`) : alignés sur la liste ci-dessus hors `id`, `photo_principale`, `search_vector`.

---

*Référence code : `botanique/models.py`, `botanique/pfaf_mapping.py`, `botanique/sync_payload.py`.*
