"""
Importe hauteur_max et largeur_max depuis Wikidata (SPARQL).
Mode fill_gaps uniquement. P2048=height, P2049=width.

Usage:
  python manage.py import_wikidata --enrich --limit 50
  python manage.py import_wikidata --enrich --delay 0.3
"""
import re
import sys
import time

import requests
from django.core.management.base import BaseCommand

from botanique.models import Organism, OrganismCalendrier
from botanique.source_rules import (
    SOURCE_WIKIDATA,
    ensure_organism_genus,
    is_empty_value,
    latin_name_without_author,
)

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = "JardinBiot/1.0 (species import; Django management command)"


def _search_key(nom_latin: str) -> str:
    """Genre + espèce pour la requête Wikidata."""
    if not nom_latin or not nom_latin.strip():
        return ""
    s = re.sub(r"\s*\([^)]*\)", " ", nom_latin)
    return " ".join(s.split()[:2]).strip()


def _parse_wikidata_quantity(val) -> float | None:
    """
    Parse une valeur Quantity Wikidata (peut être un URI ou un littéral).
    Retourne la valeur en mètres.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val) if val > 0 else None
    s = str(val).strip()
    if not s:
        return None
    # Format "123" ou "123.45" (sans unité dans le binding)
    m = re.search(r"^([\d.]+)", s)
    if m:
        try:
            x = float(m.group(1))
            # Si valeur > 50, probablement en cm
            if x > 50:
                return round(x / 100, 2)
            return round(x, 2)
        except ValueError:
            pass
    return None


def wikidata_fetch(session: requests.Session, scientific_name: str) -> dict | None:
    """
    Requête SPARQL Wikidata pour un taxon. Retourne {height, width, qid} ou None.
    """
    name = _search_key(scientific_name)
    if not name:
        return None
    # Échapper les guillemets dans le nom
    safe = name.replace('"', '\\"')
    query = f"""
    SELECT ?height ?width ?item WHERE {{
      ?item wdt:P31/wdt:P279* wd:Q16521 .
      ?item wdt:P225 "{safe}"@en .
      OPTIONAL {{ ?item wdt:P2048 ?height . }}
      OPTIONAL {{ ?item wdt:P2049 ?width . }}
    }}
    LIMIT 1
    """
    try:
        r = session.get(
            WIKIDATA_SPARQL,
            params={"query": query, "format": "json"},
            timeout=20,
            headers={"User-Agent": USER_AGENT},
        )
        r.raise_for_status()
        data = r.json()
        bindings = data.get("results", {}).get("bindings", [])
        if not bindings:
            return None
        row = bindings[0]
        out = {}
        if "height" in row:
            v = row["height"].get("value")
            if v:
                out["height"] = v
        if "width" in row:
            v = row["width"].get("value")
            if v:
                out["width"] = v
        if "item" in row:
            uri = row["item"].get("value", "")
            m = re.search(r"Q\d+", uri)
            if m:
                out["qid"] = m.group(0)
        return out if (out.get("height") or out.get("width")) else None
    except Exception:
        return None


class Command(BaseCommand):
    help = "Importe hauteur et largeur depuis Wikidata (SPARQL). Mode fill_gaps."

    def add_arguments(self, parser):
        parser.add_argument("--enrich", action="store_true", help="Enrichir les organismes existants")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--delay", type=float, default=0.5)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        enrich = options["enrich"]
        limit = options["limit"] or 0
        delay = max(0.2, options["delay"])
        dry_run = options["dry_run"]

        if not enrich:
            self.stdout.write(self.style.ERROR(
                "Option requise : cochez « enrich » pour enrichir les organismes existants "
                "(hauteur et largeur depuis Wikidata)."
            ))
            sys.exit(1)

        from django.db.models import Q

        qs = Organism.objects.filter(
            Q(hauteur_max__isnull=True) | Q(hauteur_max=0) | Q(largeur_max__isnull=True) | Q(largeur_max=0)
        ).exclude(nom_latin="").order_by("nom_latin")
        if limit > 0:
            qs = qs[:limit]
        organisms = list(qs)
        self.stdout.write(self.style.SUCCESS(f"Enrichissement Wikidata: {len(organisms)} organismes."))

        updated = 0
        skipped = 0
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})

        for organism in organisms:
            time.sleep(delay)
            nom = latin_name_without_author(organism.nom_latin or "")
            if not nom:
                skipped += 1
                continue
            result = wikidata_fetch(session, nom)
            if not result:
                skipped += 1
                continue

            h = _parse_wikidata_quantity(result.get("height"))
            w = _parse_wikidata_quantity(result.get("width"))
            if not h and not w:
                skipped += 1
                continue

            changed = False
            if h is not None and is_empty_value(organism.hauteur_max) and not dry_run:
                organism.hauteur_max = h
                organism.save(update_fields=["hauteur_max"])
                changed = True
            if w is not None and is_empty_value(organism.largeur_max) and not dry_run:
                organism.largeur_max = w
                organism.save(update_fields=["largeur_max"])
                changed = True

            if changed:
                updated += 1
                sources = dict(organism.data_sources or {})
                sources[SOURCE_WIKIDATA] = {"qid": result.get("qid"), "height": result.get("height"), "width": result.get("width")}
                organism.data_sources = sources
                organism.save(update_fields=["data_sources"])
                ensure_organism_genus(organism)

        self.stdout.write(self.style.SUCCESS(f"Terminé: {updated} mis à jour, {skipped} ignorés."))
