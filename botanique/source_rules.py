"""
Règles de fusion des données multi-sources (Hydro-Québec, PFAF, etc.).

Stratégie #3/#4 :
- Chaque source stocke son bloc brut dans Organism.data_sources[source_id].
- Les champs "principaux" du modèle = une seule valeur, selon priorité ou merge.
- Mode "fill_gaps" : ne remplir que les champs actuellement vides (ne pas écraser).
- Règles par type de champ (ex. zone = plus conservative) pour conflits futurs.
"""
import re
import unicodedata
from typing import Any, Dict, Optional, Tuple

from django.db.models import Q

# Import utilisé par get_unique_slug_latin (même logique que Organism.save)
from botanique.utils import slugify_latin as _slugify_latin

# Identifiants des sources (clés dans data_sources)
SOURCE_HYDROQUEBEC = 'hydroquebec'
SOURCE_PFAF = 'pfaf'
SOURCE_VASCAN = 'vascan'
SOURCE_VILLE_QUEBEC = 'ville_quebec'
SOURCE_VILLE_MONTREAL = 'ville_montreal'
SOURCE_USDA = 'usda'
SOURCE_BOTANIPEDIA = 'botanipedia'
SOURCE_TOPIC = 'topic'
SOURCE_USDA_PLANTS = 'usda_plants'
SOURCE_WIKIDATA = 'wikidata'

# Mode de fusion pour un import
MERGE_OVERWRITE = 'overwrite'   # Écraser les champs avec les valeurs de la source
MERGE_FILL_GAPS = 'fill_gaps'   # Ne remplir que les champs actuellement vides

# Priorité d'affichage par champ (quelle source est préférée quand les deux ont une valeur)
# Contexte Québec : HQ prioritaire. Pas de dépendance à PFAF.
FIELD_PRIMARY_SOURCE: Dict[str, str] = {
    # Contexte québécois prioritaire
    'zone_rusticite': SOURCE_HYDROQUEBEC,
    'besoin_eau': SOURCE_HYDROQUEBEC,
    'besoin_soleil': SOURCE_HYDROQUEBEC,
    'sol_textures': SOURCE_HYDROQUEBEC,
    'sol_ph': SOURCE_HYDROQUEBEC,
    'famille': SOURCE_HYDROQUEBEC,
    'description': SOURCE_HYDROQUEBEC,
    'usages_autres': SOURCE_HYDROQUEBEC,
    'parties_comestibles': SOURCE_HYDROQUEBEC,
    'toxicite': SOURCE_HYDROQUEBEC,
    'indigene': SOURCE_VASCAN,
}
# Champs non listés : première source qui remplit gagne (ou fill_gaps).


def is_empty_value(value: Any) -> bool:
    """Indique si une valeur est considérée comme vide (à remplir par une autre source)."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    if isinstance(value, (int, float)):
        # 0 pourrait être valide pour hauteur; on ne considère pas numérique comme "vide" ici
        return False
    return False


def apply_fill_gaps(current: Optional[Dict[str, Any]], defaults: Dict[str, Any]) -> Dict[str, Any]:
    """
    Filtre `defaults` pour ne garder que les champs où `current` est vide.
    Si `current` est None (nouvel enregistrement), retourne tous les defaults.
    """
    if current is None:
        return dict(defaults)
    merged = {}
    for key, new_val in defaults.items():
        if key not in current:
            merged[key] = new_val
            continue
        cur_val = current.get(key)
        if is_empty_value(cur_val):
            merged[key] = new_val
    return merged


# Regex pour zone USDA (ex. 4a, 5b, 10)
_ZONE_PATTERN = re.compile(r'^(\d+)([ab])?$', re.IGNORECASE)


def zone_rusticite_order(zone: str) -> tuple:
    """
    Clé de tri pour zones USDA : plus le nombre est petit, plus la zone est froide.
    Utilisé pour prendre la zone la plus conservative (plante plus rustique).
    """
    if not zone or not zone.strip():
        return (99, 0)
    m = _ZONE_PATTERN.match(zone.strip())
    if not m:
        return (99, 0)
    num = int(m.group(1))
    sub = (0 if (m.group(2) or '').lower() == 'a' else 1)
    return (num, sub)


def merge_zone_rusticite(current: Optional[str], new: Optional[str]) -> str:
    """
    Retourne la zone la plus conservative (la plus froide = plus petit numéro).
    Ex. 4a et 5b → 4a.
    DEPRECATED: Utiliser merge_zones_rusticite() pour le nouveau format JSONField.
    """
    if is_empty_value(new):
        return (current or '').strip()
    if is_empty_value(current):
        return (new or '').strip()
    cur = (current or '').strip()
    neu = (new or '').strip()
    if not cur:
        return neu
    if not neu:
        return cur
    return cur if zone_rusticite_order(cur) <= zone_rusticite_order(neu) else neu


def latin_name_without_author(name: str) -> str:
    """
    Retire l'auteur du nom latin (ex. "Vaccinium corymbosum L." → "Vaccinium corymbosum").
    Ne touche pas aux cultivars (ex. "Vaccinium corymbosum 'Blueray'" reste inchangé).
    """
    if not name or not name.strip():
        return ''
    s = name.strip()
    parts = s.split()
    if len(parts) <= 1:
        return s
    # Si le dernier segment ressemble à un auteur (L., Lam., etc.)
    last = parts[-1]
    if re.match(r'^[A-Z][a-z]?\.?$', last) or (len(last) <= 4 and last.endswith('.')):
        return ' '.join(parts[:-1]).strip()
    return s


# Regex: nom latin se terminant par un segment entre guillemets simples (cultivar)
_CULTIVAR_SUFFIX_RE = re.compile(r"\s+'([^']+)'\s*$")
# Parenthèse finale du type (Espèce 'Variante') ou ('Variante') à ignorer pour le parsing
_TRAILING_PAREN_ALTERNATE_RE = re.compile(r"\s*\([^)]*'[^']+'[^)]*\)\s*$")


def nom_latin_for_genus(nom_latin: str) -> str:
    """
    Retourne le nom latin « propre » utilisé pour déduire le genre :
    normalisation guillemets, retrait parenthèse finale (Espèce 'Variante'),
    retrait suffixe cultivar '...', retrait auteur.
    """
    if not nom_latin or not nom_latin.strip():
        return ''
    s = nom_latin.strip().replace('\u2019', "'").replace('\u2018', "'")
    s = _TRAILING_PAREN_ALTERNATE_RE.sub('', s).strip()
    m = _CULTIVAR_SUFFIX_RE.search(s)
    if m:
        s = s[: m.start()].strip()
    s = latin_name_without_author(s)
    return s.strip()


def get_genus_from_nom_latin(nom_latin: str) -> str:
    """
    Extrait le genre botanique du nom latin (premier mot après nettoyage).
    Gère hybrides (Genus x epithet) → genre = premier mot.
    """
    clean = nom_latin_for_genus(nom_latin or '')
    if not clean:
        return ''
    first = clean.split()[0]
    return first.strip() if first else ''


def ensure_organism_genus(organism) -> None:
    """
    Calcule et assigne organism.genus à partir de organism.nom_latin.
    Sauvegarde l'organisme si genus a été mis à jour. À appeler après création/mise à jour d'un Organism.
    """
    if not organism or not hasattr(organism, 'genus'):
        return
    nom = (organism.nom_latin or '').strip()
    if not nom:
        return
    genus = get_genus_from_nom_latin(nom)
    if genus and (not organism.genus or organism.genus != genus):
        organism.genus = genus
        organism.save(update_fields=['genus'])


def parse_cultivar_from_latin(nom_latin: str) -> Tuple[str, Optional[str]]:
    """
    Sépare le nom latin en espèce de base et nom de cultivar si présent.

    Ex: "Vaccinium corymbosum 'Bluecrop'" -> ("Vaccinium corymbosum", "Bluecrop")
    Ex: "Malus pumila 'Dolgo'" -> ("Malus pumila", "Dolgo")
    Ex: "Amelanchier alnifolia 'Smokey' ('Amelanchier alnifolia 'Smoky')" -> ("Amelanchier alnifolia", "Smokey")
    Ex: "Vaccinium corymbosum" -> ("Vaccinium corymbosum", None)

    Returns:
        (nom_latin_espece, nom_cultivar ou None)
    """
    if not nom_latin or not nom_latin.strip():
        return ('', None)
    # Normaliser guillemets typographiques (U+2018, U+2019) en ASCII pour la regex
    s = nom_latin.strip().replace('\u2019', "'").replace('\u2018', "'")
    # Retirer une parenthèse finale type (Espèce 'Variante') pour ne parser que le premier cultivar
    s = _TRAILING_PAREN_ALTERNATE_RE.sub('', s).strip()
    m = _CULTIVAR_SUFFIX_RE.search(s)
    if m:
        cultivar_name = m.group(1).strip()
        base_latin = s[: m.start()].strip()
        if base_latin and cultivar_name:
            return (base_latin, cultivar_name)
    return (s, None)


def get_unique_slug_cultivar(Cultivar, organism, nom_cultivar: str) -> str:
    """
    Retourne un slug_cultivar unique pour un cultivar sous une espèce donnée.
    Format: {organism.slug_latin}-{nom_cultivar_slug}, avec suffixe numérique en cas de collision.
    """
    if not organism or not organism.slug_latin or not nom_cultivar or not nom_cultivar.strip():
        return ''
    base = organism.slug_latin + '-' + _slugify_latin(nom_cultivar.strip())
    candidate = base
    suffix = 2
    while Cultivar.objects.filter(slug_cultivar=candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def normalize_latin_name(name: str) -> str:
    """
    Normalise un nom latin pour matching fuzzy.
    - Lowercase
    - Suppression accents (é → e, à → a)
    - Normalisation espaces/punctuation
    """
    if not name:
        return ''
    # Lowercase
    normalized = name.lower().strip()
    # Supprimer accents (é → e, à → a)
    normalized = unicodedata.normalize('NFD', normalized)
    normalized = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    # Normaliser espaces/punctuation
    normalized = re.sub(r'[^\w\s]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized.strip()


def merge_zones_rusticite(current_zones: list, new_zone: str, source: str) -> list:
    """
    Ajoute ou met à jour une zone pour une source donnée.
    
    Args:
        current_zones: Liste existante [{"zone": "4a", "source": "hydroquebec"}, ...]
        new_zone: Nouvelle zone à ajouter/mettre à jour (ex. "5b")
        source: Source de la zone (ex. "pfaf")
    
    Returns:
        Liste mise à jour avec la nouvelle zone pour cette source.
    """
    if not new_zone or not new_zone.strip():
        return current_zones or []
    
    zones = list(current_zones or [])
    new_zone_clean = new_zone.strip()
    
    # Chercher si cette source a déjà une zone
    found = False
    for i, z in enumerate(zones):
        if isinstance(z, dict) and z.get('source') == source:
            zones[i] = {"zone": new_zone_clean, "source": source}
            found = True
            break
    
    if not found:
        zones.append({"zone": new_zone_clean, "source": source})
    
    return zones


def find_organism_by_latin_fuzzy(Organism, nom_latin: str):
    """
    Cherche un organisme par nom_latin avec matching fuzzy (normalisation).
    Retourne le premier match trouvé ou None.
    """
    if not nom_latin or not nom_latin.strip():
        return None
    
    # Essai 1: Exact match (case-insensitive)
    exact = Organism.objects.filter(nom_latin__iexact=nom_latin.strip()).first()
    if exact:
        return exact
    
    # Essai 2: Fuzzy - normaliser et chercher avec regex
    norm = normalize_latin_name(nom_latin)
    if norm:
        # Chercher avec regex flexible (espaces → .*)
        pattern = norm.replace(' ', '.*')
        fuzzy = Organism.objects.filter(nom_latin__iregex=pattern).first()
        if fuzzy:
            return fuzzy
        
        # Essai 3: Chercher par mots-clés (si plusieurs mots)
        words = norm.split()
        if len(words) > 1:
            # Chercher où tous les mots sont présents
            q = Q()
            for word in words:
                q &= Q(nom_latin__icontains=word)
            fuzzy = Organism.objects.filter(q).first()
            if fuzzy:
                return fuzzy
    
    return None


def find_organism_by_common_name(Organism, nom_commun: str):
    """
    Cherche un organisme par nom_commun (exact match case-insensitive).
    Retourne le premier match trouvé ou None.
    """
    if not nom_commun or not nom_commun.strip():
        return None
    
    return Organism.objects.filter(nom_commun__iexact=nom_commun.strip()).first()


def get_unique_slug_latin(Organism, nom_latin: str) -> str:
    """
    Retourne un slug_latin unique à partir du nom latin (normalisation + suffixe si collision).
    Utilisable par les commandes d'import pour éviter IntegrityError sur la contrainte unique.
    """
    if not nom_latin or not nom_latin.strip():
        return ''
    base = _slugify_latin(nom_latin.strip())
    if not base:
        return ''
    candidate = base
    suffix = 2
    while Organism.objects.filter(slug_latin=candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def find_or_match_organism(
    Organism,
    nom_latin: str,
    nom_commun: str,
    defaults: Optional[Dict[str, Any]] = None,
    *,
    tsn: Optional[int] = None,
    vascan_id: Optional[int] = None,
    create_missing: bool = True,
) -> Tuple[Optional[Any], bool]:
    """
    Trouve ou crée un organisme avec matching intelligent.

    Ordre de recherche :
    1. Si vascan_id fourni : chercher par vascan_id
    2. Si tsn fourni : chercher par tsn
    3. Si nom_latin fourni : chercher par nom_latin (exact, sans auteur, fuzzy)
    4. Si nom_commun fourni : chercher par nom_commun
    5. Créer nouveau (nom_latin requis, utiliser nom_commun comme fallback)

    Args:
        Organism: Classe modèle Organism
        nom_latin: Nom scientifique latin
        nom_commun: Nom commun
        defaults: Dict de valeurs par défaut pour création/mise à jour
        tsn: Taxonomic Serial Number (ITIS/USDA), optionnel
        vascan_id: Identifiant VASCAN (Canadensys), optionnel

    Returns:
        Tuple (organism or None, was_created) où was_created est True si nouvel organisme créé.
        Si create_missing=False et rien n'est trouvé, retourne (None, False).
    """
    defaults = defaults or {}
    was_created = False

    # 0. Recherche par identifiants taxonomiques (évite les doublons)
    if vascan_id is not None:
        by_vascan = Organism.objects.filter(vascan_id=vascan_id).first()
        if by_vascan:
            return by_vascan, False
    if tsn is not None:
        by_tsn = Organism.objects.filter(tsn=tsn).first()
        if by_tsn:
            return by_tsn, False

    # 1. Si nom_latin fourni, chercher par nom_latin (exact, sans auteur, fuzzy)
    if nom_latin and nom_latin.strip():
        nom_latin_clean = nom_latin.strip()
        
        # 1a. Exact match
        exact = Organism.objects.filter(nom_latin__iexact=nom_latin_clean).first()
        if exact:
            if not exact.nom_latin:
                exact.nom_latin = nom_latin_clean
                exact.save(update_fields=['nom_latin'])
            return exact, False
        
        # 1b. Match (nom_latin, nom_commun) pour éviter confusions cultivars/espèces
        if nom_commun and nom_commun.strip():
            exact_both = Organism.objects.filter(
                nom_latin__iexact=nom_latin_clean,
                nom_commun__iexact=nom_commun.strip(),
            ).first()
            if exact_both:
                return exact_both, False
        
        # 1c. Match nom latin sans auteur (Vaccinium corymbosum L. ≈ Vaccinium corymbosum)
        base = latin_name_without_author(nom_latin_clean)
        if base and base != nom_latin_clean:
            without_author = Organism.objects.filter(
                Q(nom_latin__iexact=base)
                | Q(nom_latin__istartswith=base + ' ')
            ).first()
            if without_author:
                if not without_author.nom_latin or without_author.nom_latin != nom_latin_clean:
                    without_author.nom_latin = nom_latin_clean
                    without_author.save(update_fields=['nom_latin'])
                return without_author, False
        
        # 1d. Fuzzy matching
        fuzzy = find_organism_by_latin_fuzzy(Organism, nom_latin_clean)
        if fuzzy:
            if not fuzzy.nom_latin or normalize_latin_name(fuzzy.nom_latin) != normalize_latin_name(nom_latin_clean):
                fuzzy.nom_latin = nom_latin_clean
                fuzzy.save(update_fields=['nom_latin'])
            return fuzzy, False
    
    # 2. Si nom_latin manque mais nom_commun fourni, chercher par nom_commun
    if (not nom_latin or not nom_latin.strip()) and nom_commun and nom_commun.strip():
        by_common = find_organism_by_common_name(Organism, nom_commun)
        if by_common:
            # Ajouter nom_latin si fourni maintenant
            if nom_latin and nom_latin.strip() and not by_common.nom_latin:
                by_common.nom_latin = nom_latin.strip()
                by_common.save(update_fields=['nom_latin'])
            return by_common, False
    
    # 3. Créer nouveau si rien trouvé
    # nom_latin est requis pour créer, utiliser nom_commun comme fallback si nécessaire
    if not create_missing:
        return None, False

    create_data = dict(defaults)
    if tsn is not None:
        create_data['tsn'] = tsn
    if vascan_id is not None:
        create_data['vascan_id'] = vascan_id
    if not create_data.get('nom_latin'):
        if nom_latin and nom_latin.strip():
            create_data['nom_latin'] = nom_latin.strip()
        elif nom_commun and nom_commun.strip():
            create_data['nom_latin'] = nom_commun.strip()
        else:
            raise ValueError("Impossible de créer un organisme sans nom_latin ni nom_commun")
    
    if not create_data.get('nom_commun') and nom_commun and nom_commun.strip():
        create_data['nom_commun'] = nom_commun.strip()
    
    organism = Organism.objects.create(**create_data)
    return organism, True


def find_organism_and_cultivar(
    Organism,
    Cultivar,
    nom_latin: str,
    nom_commun: str,
    defaults_organism: Optional[Dict[str, Any]] = None,
    defaults_cultivar: Optional[Dict[str, Any]] = None,
    *,
    tsn: Optional[int] = None,
    vascan_id: Optional[int] = None,
) -> Tuple[Any, Optional[Any], bool]:
    """
    Trouve ou crée l'espèce (Organism) et, si le nom latin contient un cultivar, le cultivar associé.

    Si nom_latin contient un motif cultivar (ex. "Vaccinium corymbosum 'Bluecrop'") :
      - Trouve ou crée l'Organism pour l'espèce de base.
      - Crée ou récupère le Cultivar sous cet Organism.
      - Retourne (organism, cultivar, was_organism_created).

    Sinon : comportement identique à find_or_match_organism, avec (organism, None, was_created).

    Returns:
        (organism, cultivar ou None, was_organism_created)
    """
    base_latin, nom_cultivar = parse_cultivar_from_latin(nom_latin or '')
    defaults_organism = defaults_organism or {}
    defaults_cultivar = defaults_cultivar or {}

    if nom_cultivar and base_latin:
        # Dériver nom_commun espèce : retirer le nom du cultivar en fin de chaîne si présent
        nom_commun_clean = (nom_commun or '').strip()
        nom_commun_espece = re.sub(
            r'\s+' + re.escape(nom_cultivar) + r'\s*$',
            '',
            nom_commun_clean,
            flags=re.IGNORECASE,
        ).strip() or nom_commun_clean
        organism, was_created = find_or_match_organism(
            Organism,
            nom_latin=base_latin,
            nom_commun=nom_commun_espece,
            defaults=defaults_organism,
            tsn=tsn,
            vascan_id=vascan_id,
        )
        slug_cultivar = get_unique_slug_cultivar(Cultivar, organism, nom_cultivar)
        cultivar_defaults = {
            'nom': nom_cultivar,
            **defaults_cultivar,
        }
        cultivar, _ = Cultivar.objects.get_or_create(
            organism=organism,
            slug_cultivar=slug_cultivar,
            defaults=cultivar_defaults,
        )
        return (organism, cultivar, was_created)

    organism, was_created = find_or_match_organism(
        Organism,
        nom_latin=nom_latin or '',
        nom_commun=nom_commun or '',
        defaults=defaults_organism,
        tsn=tsn,
        vascan_id=vascan_id,
    )
    return (organism, None, was_created)
