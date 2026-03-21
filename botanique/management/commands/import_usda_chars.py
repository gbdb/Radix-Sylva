"""
Importe les caractéristiques USDA PLANTS (hauteur, largeur, floraison).
Mode enrich-only strict : ne crée jamais de nouveaux organismes.
Utilise uniquement find_or_match_organism(..., create_missing=False).
Si l'organisme n'existe pas en base → skip et log "ignoré".

Utilise l'API USDA PLANTS ou un fichier CSV (symbol,scientific_name,height,spread,bloom_period).

Usage:
  python manage.py import_usda_chars --limit 50
  python manage.py import_usda_chars --file data/usda/characteristics.csv
"""
import re
import sys
import time
from pathlib import Path

import requests
from django.db import models
from django.core.management.base import BaseCommand

from botanique.models import Organism, OrganismCalendrier
from botanique.source_rules import (
    SOURCE_USDA_PLANTS,
    ensure_organism_genus,
    find_or_match_organism,
    is_empty_value,
    latin_name_without_author,
)

USER_AGENT = "JardinBiot/1.0 (species import; Django management command)"
USDA_SEARCH_URL = "https://plants.usda.gov/api/plants/search"
USDA_SEARCH_ALT = "https://plants.sc.egov.usda.gov/api/plants/search"

# Mois anglais -> numéro
MONTH_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _search_key(nom_latin: str) -> str:
    """Genre + espèce pour la recherche USDA."""
    if not nom_latin or not nom_latin.strip():
        return ""
    s = re.sub(r"\s*\([^)]*\)", " ", nom_latin)
    return " ".join(s.split()[:2]).strip()


def _parse_height_ft(val: str) -> float | None:
    """Parse hauteur en pieds (ex. '50 feet', '10-20 ft') -> mètres."""
    if not val or not isinstance(val, str):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:feet|ft|')", val, re.IGNORECASE)
    if m:
        ft = float(m.group(1))
        return round(ft * 0.3048, 2)  # ft -> m
    m = re.search(r"(\d+(?:\.\d+)?)\s*m(?:eters?)?", val, re.IGNORECASE)
    if m:
        return float(m.group(1))
    try:
        x = float(str(val).replace(",", ".").strip())
        return x if x < 100 else x / 100  # cm -> m si > 100
    except (TypeError, ValueError):
        return None


def _parse_spread_ft(val: str) -> float | None:
    """Parse largeur/spread en pieds -> mètres."""
    return _parse_height_ft(val) if val else None


def _parse_bloom_months(val: str) -> tuple[int | None, int | None]:
    """Parse Bloom Period (ex. 'May-June', 'Spring') -> (mois_debut, mois_fin)."""
    if not val or not isinstance(val, str):
        return None, None
    t = val.strip().lower()
    if not t:
        return None, None
    # Spring, Summer, Fall, Winter
    seasons = {"spring": (3, 5), "summer": (6, 8), "fall": (9, 11), "autumn": (9, 11), "winter": (12, 2)}
    for name, (m1, m2) in seasons.items():
        if name in t:
            return m1, m2
    # May-June, March to July
    for name, num in MONTH_EN.items():
        if name in t:
            m = re.findall(r"\b(" + "|".join(MONTH_EN.keys()) + r")\b", t)
            if m:
                nums = [MONTH_EN.get(x.lower(), 0) for x in m if MONTH_EN.get(x.lower())]
                if nums:
                    return min(nums), max(nums)
            return num, num
    return None, None


def usda_search(session: requests.Session, scientific_name: str) -> dict | None:
    """
    Recherche USDA PLANTS par nom scientifique.
    Retourne le premier résultat avec symbol, ou None.
    """
    q = _search_key(scientific_name)
    if not q:
        return None
    for base in [USDA_SEARCH_URL, USDA_SEARCH_ALT]:
        try:
            r = session.get(
                f"{base}/basic",
                params={"scientific_name": q},
                timeout=15,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if not data:
                continue
            # Structure variable selon l'API
            items = data if isinstance(data, list) else data.get("data") or data.get("results") or []
            if isinstance(data, dict) and "data" not in data:
                items = [data]
            if not items:
                continue
            first = items[0] if isinstance(items[0], dict) else None
            if first and first.get("symbol"):
                return first
            # Chercher dans une structure imbriquée
            for k in ("plants", "species", "records"):
                arr = data.get(k)
                if isinstance(arr, list) and arr and isinstance(arr[0], dict) and arr[0].get("symbol"):
                    return arr[0]
        except Exception:
            continue
    return None


def usda_fetch_characteristics(session: requests.Session, symbol: str) -> dict | None:
    """
    Récupère les caractéristiques (height, spread, bloom) pour un symbol USDA.
    Tente l'API full search ou le parsing HTML du plant profile.
    """
    # Full API peut contenir plus de champs
    for base in [USDA_SEARCH_URL, USDA_SEARCH_ALT]:
        try:
            r = session.get(
                base,
                params={"symbol": symbol},
                timeout=15,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if not data:
                continue
            # Extraire height, spread, bloom
            item = data if isinstance(data, dict) else (data[0] if isinstance(data, list) and data else None)
            if isinstance(data, list) and data:
                item = data[0]
            if not isinstance(item, dict):
                continue
            out = {}
            for key in ("height", "matureHeight", "maxHeight", "plantHeight"):
                if item.get(key):
                    out["height"] = item[key]
                    break
            for key in ("spread", "matureSpread", "maxSpread", "plantSpread"):
                if item.get(key):
                    out["spread"] = item[key]
                    break
            for key in ("bloomPeriod", "bloom_period", "floweringPeriod"):
                if item.get(key):
                    out["bloom"] = item[key]
                    break
            if out:
                return out
        except Exception:
            continue

    # Fallback: plant profile HTML (si API ne renvoie pas les chars)
    try:
        url = f"https://plants.sc.egov.usda.gov/home/plantProfile?symbol={symbol}"
        r = session.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
        if r.status_code == 200 and "Height" in r.text:
            # Parsing basique
            out = {}
            for label, key in [("Height", "height"), ("Spread", "spread"), ("Bloom Period", "bloom")]:
                m = re.search(rf"{re.escape(label)}[:\s]*([^<\n]+)", r.text, re.IGNORECASE)
                if m:
                    out[key] = m.group(1).strip()
            if out:
                return out
    except Exception:
        pass
    return None


class Command(BaseCommand):
    help = "Importe hauteur, largeur, floraison depuis USDA PLANTS. Mode fill_gaps."

    def add_arguments(self, parser):
        parser.add_argument(
            "--enrich",
            action="store_true",
            help="Enrichir les organismes existants via API (défaut si --file absent)",
        )
        parser.add_argument("--file", type=str, default=None, help="CSV: symbol,scientific_name,height,spread,bloom_period")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--delay", type=float, default=0.6)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        import csv as csv_module

        file_path = options.get("file")
        enrich = bool(options.get("enrich")) or not file_path
        limit = options["limit"] or 0
        delay = max(0.3, options["delay"])
        dry_run = options["dry_run"]

        if enrich:
            qs = Organism.objects.filter(
                models.Q(hauteur_max__isnull=True) | models.Q(hauteur_max=0) |
                models.Q(largeur_max__isnull=True) | models.Q(largeur_max=0)
            ).exclude(nom_latin="").order_by("nom_latin")
            if limit > 0:
                qs = qs[:limit]
            organisms = list(qs)
            self.stdout.write(self.style.SUCCESS(f"Enrichissement USDA chars: {len(organisms)} organismes."))
        elif file_path:
            path = Path(file_path)
            if not path.exists():
                self.stdout.write(self.style.ERROR(f"Fichier introuvable: {path}"))
                return
            rows = []
            with open(path, newline="", encoding="utf-8", errors="replace") as f:
                for i, row in enumerate(csv_module.DictReader(f)):
                    if limit and i >= limit:
                        break
                    rows.append(row)
            organisms = None
            self.stdout.write(self.style.SUCCESS(f"Import USDA chars depuis {path.name}: {len(rows)} lignes."))

        enrichis = 0
        ignorés = 0
        erreurs = 0
        cal_created = 0

        if enrich:
            session = requests.Session()
            session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
            for organism in organisms:
                time.sleep(delay)
                nom = latin_name_without_author(organism.nom_latin or "")
                if not nom:
                    ignorés += 1
                    self.stdout.write(self.style.WARNING(f"  ignoré: {organism.nom_latin or '(vide)'}"))
                    continue
                try:
                    result = usda_search(session, nom)
                    if not result:
                        ignorés += 1
                        self.stdout.write(self.style.WARNING(f"  ignoré: {nom}"))
                        continue
                    symbol = result.get("symbol")
                    if not symbol:
                        ignorés += 1
                        self.stdout.write(self.style.WARNING(f"  ignoré: {nom}"))
                        continue
                    chars = usda_fetch_characteristics(session, symbol)
                    if not chars:
                        chars = {"height": result.get("height"), "spread": result.get("spread"), "bloom": result.get("bloomPeriod")}
                    ok, cal = self._apply_chars(organism, chars, dry_run)
                    if ok:
                        enrichis += 1
                    if cal:
                        cal_created += 1
                    ensure_organism_genus(organism)
                except Exception as e:
                    erreurs += 1
                    self.stdout.write(self.style.ERROR(f"  erreur {nom}: {e}"))
        else:
            for row in rows:
                symbol = (row.get("symbol") or row.get("Symbol") or "").strip()
                sci = (row.get("scientific_name") or row.get("Scientific_Name") or row.get("species") or "").strip()
                if not sci and not symbol:
                    ignorés += 1
                    continue
                organism, _ = find_or_match_organism(
                    Organism,
                    nom_latin=sci or symbol,
                    nom_commun=sci or symbol,
                    defaults={},
                    create_missing=False,  # enrich-only: ne jamais créer de nouveaux organismes
                )
                if organism is None:
                    ignorés += 1
                    self.stdout.write(self.style.WARNING(f"  ignoré: {sci or symbol}"))
                    continue
                try:
                    chars = {
                        "height": row.get("height") or row.get("Height"),
                        "spread": row.get("spread") or row.get("Spread"),
                        "bloom": row.get("bloom_period") or row.get("Bloom_Period") or row.get("bloom"),
                    }
                    ok, cal = self._apply_chars(organism, chars, dry_run)
                    if ok:
                        enrichis += 1
                    if cal:
                        cal_created += 1
                    ensure_organism_genus(organism)
                except Exception as e:
                    erreurs += 1
                    self.stdout.write(self.style.ERROR(f"  erreur {sci or symbol}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Terminé: enrichis={enrichis}, ignorés={ignorés}, erreurs={erreurs}"
            + (f", {cal_created} entrées calendrier" if cal_created else "")
            + "."
        ))

    def _apply_chars(self, organism, chars, dry_run):
        """Applique height, spread, bloom. Retourne (updated, cal_created)."""
        updated = False
        cal_created = False
        h = _parse_height_ft(chars.get("height") or "")
        if h is not None and is_empty_value(organism.hauteur_max) and not dry_run:
            organism.hauteur_max = h
            organism.save(update_fields=["hauteur_max"])
            updated = True
        w = _parse_spread_ft(chars.get("spread") or "")
        if w is not None and is_empty_value(organism.largeur_max) and not dry_run:
            organism.largeur_max = w
            organism.save(update_fields=["largeur_max"])
            updated = True
        m1, m2 = _parse_bloom_months(chars.get("bloom") or "")
        if m1 is not None and not dry_run:
            if not OrganismCalendrier.objects.filter(organisme=organism, type_periode="floraison", source=SOURCE_USDA_PLANTS).exists():
                OrganismCalendrier.objects.create(
                    organisme=organism, type_periode="floraison", mois_debut=m1, mois_fin=m2 or m1, source=SOURCE_USDA_PLANTS
                )
                cal_created = True
            updated = True
        if not dry_run and (h or w or m1):
            sources = dict(organism.data_sources or {})
            sources[SOURCE_USDA_PLANTS] = chars
            organism.data_sources = sources
            organism.save(update_fields=["data_sources"])
        return updated, cal_created
