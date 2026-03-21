"""
Enrichissement d'un organisme unique depuis VASCAN, USDA/ITIS et Botanipedia.
Utilisé par le bouton « Enrichir cette espèce » sur la fiche organisme (admin)
et peut être appelé par des vues ou scripts.
"""
import time
from typing import Dict, List, Tuple

import requests

from botanique.models import Organism
from botanique.source_rules import (
    SOURCE_BOTANIPEDIA,
    SOURCE_USDA,
    SOURCE_VASCAN,
    is_empty_value,
)

# Réutilisation des recherches des commandes d'import
from botanique.management.commands.import_vascan import vascan_search
from botanique.management.commands.import_usda import itis_search
from botanique.management.commands.import_botanipedia import (
    _build_botanipedia_title,
    _extract_excerpt,
    _get_page_content,
    _search_page,
)

DELAY_DEFAULT = 0.6


def enrich_organism_vascan(
    organism: Organism,
    session: requests.Session,
    delay: float = DELAY_DEFAULT,
) -> Tuple[bool, str]:
    """
    Enrichit un organisme avec VASCAN (vascan_id, data_sources['vascan'], indigene).
    Retourne (succès, message).
    """
    nom_latin = (organism.nom_latin or "").strip()
    if not nom_latin:
        return False, "VASCAN : nom latin vide."
    time.sleep(delay)
    try:
        result = vascan_search(session, nom_latin, delay=0)
        if not result:
            return False, "VASCAN : aucune correspondance."
        taxon_id = result["taxonID"]
        scientific_name = result.get("scientificName") or result.get("canonicalName") or nom_latin
        verns = result.get("vernacularNames") or []
        fr_name = ""
        for v in verns:
            if v.get("language") == "fr" and v.get("preferredName"):
                fr_name = v.get("vernacularName") or ""
                break
        if not fr_name and verns:
            for v in verns:
                if v.get("language") == "fr":
                    fr_name = v.get("vernacularName") or ""
                    break
        common_name = fr_name or organism.nom_commun or scientific_name
        indigene = False
        for d in result.get("distribution") or []:
            if d.get("locationID") == "ISO 3166-2:CA-QC" and d.get("occurrenceStatus") in ("native", "present"):
                indigene = True
                break
        existing_sources = dict(organism.data_sources or {})
        existing_sources[SOURCE_VASCAN] = result.get("raw", result)
        organism.data_sources = existing_sources
        organism.vascan_id = taxon_id
        organism.indigene = indigene
        if fr_name and not organism.nom_commun:
            organism.nom_commun = common_name
        organism.save(update_fields=["data_sources", "vascan_id", "indigene", "nom_commun"])
        return True, f"VASCAN : vascan_id={taxon_id}"
    except Exception as e:
        return False, f"VASCAN : {e}"


def enrich_organism_usda(
    organism: Organism,
    session: requests.Session,
    delay: float = DELAY_DEFAULT,
) -> Tuple[bool, str]:
    """
    Enrichit un organisme avec USDA/ITIS (tsn, data_sources['usda']).
    Retourne (succès, message).
    """
    nom_latin = (organism.nom_latin or "").strip()
    if not nom_latin:
        return False, "USDA : nom latin vide."
    time.sleep(delay)
    try:
        result = itis_search(session, nom_latin, delay=0)
        if not result:
            return False, "USDA : aucune correspondance."
        tsn = result["tsn"]
        existing_sources = dict(organism.data_sources or {})
        raw = result.get("raw") if isinstance(result.get("raw"), dict) else result
        existing_sources[SOURCE_USDA] = raw
        organism.data_sources = existing_sources
        organism.tsn = tsn
        organism.save(update_fields=["data_sources", "tsn"])
        return True, f"USDA : tsn={tsn}"
    except Exception as e:
        return False, f"USDA : {e}"


def enrich_organism_botanipedia(
    organism: Organism,
    session: requests.Session,
    delay: float = DELAY_DEFAULT,
) -> Tuple[bool, str]:
    """
    Enrichit un organisme avec Botanipedia (data_sources['botanipedia'], description, usages_autres).
    Retourne (succès, message).
    """
    nom_latin = (organism.nom_latin or "").strip()
    if not nom_latin:
        return False, "Botanipedia : nom latin vide."
    time.sleep(delay)
    try:
        title = _build_botanipedia_title(nom_latin)
        content = _get_page_content(session, title)
        if not content:
            title = _search_page(session, nom_latin)
            if title:
                content = _get_page_content(session, title)
        if not content:
            return False, "Botanipedia : aucune page trouvée."
        excerpt = _extract_excerpt(content)
        payload = {"title": title, "excerpt": excerpt, "raw_length": len(content)}
        sources = dict(organism.data_sources or {})
        sources[SOURCE_BOTANIPEDIA] = payload
        organism.data_sources = sources
        update_fields = ["data_sources", "date_modification"]
        if is_empty_value(organism.description) and excerpt:
            organism.description = excerpt[:5000]
            update_fields.append("description")
        if is_empty_value(organism.usages_autres) and "usage" in content.lower():
            organism.usages_autres = excerpt[:1500]
            update_fields.append("usages_autres")
        organism.save(update_fields=update_fields)
        return True, f"Botanipedia : {title}"
    except Exception as e:
        return False, f"Botanipedia : {e}"


def enrich_organism(
    organism: Organism,
    sources: List[str] | None = None,
    delay: float = DELAY_DEFAULT,
) -> Dict[str, Tuple[bool, str]]:
    """
    Enrichit un organisme avec les sources demandées (vascan, usda, botanipedia).
    Retourne un dict { 'vascan': (ok, msg), 'usda': (ok, msg), 'botanipedia': (ok, msg) }.
    """
    if sources is None:
        sources = ["vascan", "usda", "botanipedia"]
    results = {}
    session = requests.Session()
    session.headers.setdefault("User-Agent", "JardinBiot/1.0 (enrichment admin)")
    if "vascan" in sources:
        results["vascan"] = enrich_organism_vascan(organism, session, delay=delay)
    if "usda" in sources:
        results["usda"] = enrich_organism_usda(organism, session, delay=delay)
    if "botanipedia" in sources:
        results["botanipedia"] = enrich_organism_botanipedia(organism, session, delay=delay)
    return results
