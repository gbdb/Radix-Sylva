"""
Mapping flexible des champs PFAF (et formats similaires) vers le modèle Organism.

Permet d'accepter JSON, CSV ou SQLite avec des noms de colonnes variés
(PFAF officiel, GitHub pfaf-data, exports personnalisés). Les clés sont
normalisées en snake_case pour unifier l'accès.
"""
import csv
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

# Alias possibles par champ Organism (ordre de priorité)
# Clés normalisées : on essaie chaque alias sur le row déjà normalisé
PFAF_FIELD_ALIASES: Dict[str, List[str]] = {
    'latin_name': [
        'latin_name', 'nom_latin', 'latin', 'scientific_name', 'scientificname',
        'sci_name', 'binomial', 'species', 'scientific', 'latinname', 'latin_name_full'
    ],
    'common_name': [
        'common_name', 'nom_commun', 'commonname', 'common', 'name', 'plant_name',
        'vernacular_name', 'english_name', 'vernacular', 'english', 'plantname'
    ],
    'family': ['family', 'famille', 'familie'],
    'habit': ['habit', 'type', 'growth_form'],
    'zone_rusticite': ['zone_rusticite', 'zone_min', 'zone', 'hardiness', 'uk_hardiness', 'hardiness_zone'],
    'height': ['height', 'hauteur', 'height_m', 'heightm'],
    'width': ['width', 'largeur', 'spread', 'width_m'],
    'sun': ['sun', 'light', 'shade', 'exposure', 'exposition'],
    'water': ['water', 'moisture', 'humidite', 'water_requirement'],
    'soil': ['soil', 'sol', 'soil_type'],
    'description': ['description', 'cultivation', 'cultivation_details', 'habit_description', 'cultivation_details'],
    'habitat': ['habitat', 'range', 'distribution', 'range_s'],
    'edible_parts': ['edible_parts', 'edible_uses', 'edibleuses', 'parties_comestibles'],
    'uses': ['uses', 'usages', 'uses_notes', 'usages_autres', 'medicinal', 'other_uses'],
    'toxicite': ['toxicite', 'known_hazards', 'knownhazards', 'hazards'],
    'fixateur_azote': ['nitrogen_fixer', 'fixateur_azote', 'nitrogenfixer'],
}


def to_snake(name: str) -> str:
    """Normalise un libellé en snake_case (ex: 'Latin Name' -> 'latin_name')."""
    if not name:
        return ''
    s = str(name).strip()
    s = re.sub(r'[\s\-]+', '_', s)
    s = re.sub(r'(?![_])[^\w]', '', s)
    s = s.lower().strip('_')
    return s


def normalize_row_keys(row: Dict[str, Any]) -> Dict[str, Any]:
    """Retourne un nouveau dict avec toutes les clés en snake_case."""
    return {to_snake(k): v for k, v in row.items()}


def get_row_value(
    row: Dict[str, Any],
    aliases: List[str],
    default: Any = '',
    coerce_str: bool = True,
) -> Any:
    """
    Prend la première valeur non vide trouvée parmi les alias.
    row doit avoir des clés déjà normalisées (snake_case).
    """
    for key in aliases:
        v = row.get(key)
        if v is None:
            continue
        if isinstance(v, str):
            v = v.strip()
            if not v:
                continue
            return v if not coerce_str else v
        if isinstance(v, (int, float)) and coerce_str and v != '':
            return str(v).strip() if coerce_str else v
        if v != '' and v is not None:
            return str(v).strip() if coerce_str else v
    return default


def rows_from_json(path: Path) -> List[Dict[str, Any]]:
    """Charge une liste d'objets depuis un fichier JSON."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list):
        data = [data]
    return [normalize_row_keys(item) for item in data]


def rows_from_csv(
    path: Path,
    delimiter: Optional[str] = None,
    encoding: str = 'utf-8',
) -> List[Dict[str, Any]]:
    """
    Charge un CSV ; délimiteur auto (,, ;, tab) si non fourni.
    Les en-têtes sont normalisés en snake_case.
    """
    with open(path, 'r', encoding=encoding, errors='replace') as f:
        sample = f.read(4096)
    if delimiter is None:
        delimiter = ',' if ',' in sample else (';' if ';' in sample else '\t')
    with open(path, 'r', encoding=encoding, errors='replace') as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        rows = []
        for r in reader:
            rows.append(normalize_row_keys(r))
    return rows


def rows_from_sqlite(
    path: Path,
    table: str = 'plant_data',
) -> List[Dict[str, Any]]:
    """
    Charge les lignes d'une table SQLite (ex. pfaf-data data.sqlite).
    Les noms de colonnes sont normalisés en snake_case.
    """
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table):
        raise ValueError(f'Nom de table invalide: {table}')
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(f'SELECT * FROM "{table}"')
    rows = []
    for row in cur:
        d = {to_snake(k): row[k] for k in row.keys()}
        # SQLite Row values: convert to Python types
        for k, v in d.items():
            if v is not None and not isinstance(v, (str, int, float, bool)):
                d[k] = str(v)
        rows.append(d)
    conn.close()
    return rows


def get_available_columns(data: List[Dict[str, Any]]) -> List[str]:
    """
    Retourne la liste des colonnes disponibles dans les données.
    Utile pour le débogage quand les colonnes attendues ne sont pas trouvées.
    """
    if not data:
        return []
    # Prendre les clés de la première ligne (toutes les lignes devraient avoir les mêmes clés après normalisation)
    return sorted(list(data[0].keys()))


def load_pfaf_data(
    path: Path,
    db_table: str = 'plant_data',
) -> List[Dict[str, Any]]:
    """
    Charge des données PFAF depuis un fichier.
    Format détecté par extension : .json, .csv, .sqlite / .db
    """
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))
    suffix = path.suffix.lower()
    if suffix == '.json':
        return rows_from_json(path)
    if suffix in ('.csv', '.txt'):
        return rows_from_csv(path)
    if suffix in ('.sqlite', '.sqlite3', '.db'):
        return rows_from_sqlite(path, table=db_table)
    raise ValueError(
        f'Format non supporté: {suffix}. Utilisez .json, .csv ou .sqlite/.db'
    )
