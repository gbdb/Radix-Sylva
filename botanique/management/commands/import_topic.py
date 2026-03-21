"""
Importe les traits depuis TOPIC (Traits of Plants in Canada) - Open Data Canada.
Remplit hauteur_max, largeur_max, OrganismCalendrier en mode fill_gaps.

Télécharger les CSV depuis https://open.canada.ca/data/dataset/bb14c6bf-75f7-4ff2-b97e-689fa768905c
(modules Literature Review ou Empirical). Structure variable selon le sous-dataset.

Usage:
  python manage.py import_topic --file data/topic/literature_review.csv
  python manage.py import_topic --file data/topic/empirical.csv --limit 100
"""
import csv
import re
from pathlib import Path

from django.core.management.base import BaseCommand

from botanique.models import Organism, OrganismCalendrier
from botanique.source_rules import (
    SOURCE_TOPIC,
    ensure_organism_genus,
    find_or_match_organism,
    is_empty_value,
)

# Alias possibles pour les colonnes TOPIC (ordre de priorité)
TOPIC_FIELD_ALIASES = {
    "latin_name": [
        "scientific_name", "species", "latin_name", "latin", "nom_latin",
        "accepted_name", "species_name", "taxon",
    ],
    "height": [
        "height", "hauteur", "plant_height", "canopy_height", "height_cm",
        "height_m", "max_height", "mature_height",
    ],
    "width": [
        "width", "largeur", "spread", "canopy_width", "diameter",
        "width_cm", "width_m", "max_width",
    ],
    "flowering": [
        "flowering", "floraison", "flowering_start", "flowering_end",
        "bloom", "bloom_period", "flowering_month",
    ],
}

MOIS_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}
SAISON_TO_MOIS = {"printemps": (3, 5), "ete": (6, 8), "été": (6, 8), "automne": (9, 11), "hiver": (12, 2)}


def _get_value(row, aliases, default=None):
    """Première valeur non vide parmi les alias."""
    for key in row:
        key_lower = key.strip().lower().replace(" ", "_")
        for alias in aliases:
            if alias.lower() == key_lower:
                val = row.get(key)
                if val is not None and str(val).strip():
                    return str(val).strip()
    return default


def _parse_float(val):
    if val is None:
        return None
    try:
        s = str(val).replace(",", ".").strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def _parse_period(text):
    """Parse période (floraison/fructification) -> (mois_debut, mois_fin)."""
    if not text or not isinstance(text, str):
        return None, None
    t = text.strip().lower()
    if not t:
        return None, None
    # Saison
    m = re.search(r"saison\s*[;:]\s*(\w+)", t, re.IGNORECASE)
    if m and m.group(1).lower() in SAISON_TO_MOIS:
        return SAISON_TO_MOIS[m.group(1).lower()]
    # Mois
    for name, num in MOIS_FR.items():
        if re.search(r"\b" + re.escape(name) + r"\b", t):
            return num, num
    return None, None


class Command(BaseCommand):
    help = "Importe les traits TOPIC (Canada) - hauteur, largeur, floraison. Mode fill_gaps."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=str, required=True, help="Chemin vers le CSV TOPIC")
        parser.add_argument("--limit", type=int, default=0, help="Limite (0 = tout)")
        parser.add_argument("--dry-run", action="store_true", help="Afficher sans écrire")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            self.stdout.write(self.style.ERROR(f"Fichier introuvable: {path}"))
            return
        limit = options["limit"] or 0
        dry_run = options["dry_run"]

        rows = []
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if limit and i >= limit:
                    break
                rows.append(row)

        self.stdout.write(self.style.SUCCESS(f"Chargé {len(rows)} lignes depuis {path.name}"))

        updated = 0
        created_cal = 0
        skipped = 0

        for row in rows:
            nom_latin = _get_value(row, TOPIC_FIELD_ALIASES["latin_name"])
            if not nom_latin:
                skipped += 1
                continue

            # Nettoyer le nom (retirer auteur, cultivar pour le match)
            nom_base = re.sub(r"\s*\([^)]*\)", " ", nom_latin).strip()
            nom_base = nom_base.split("'")[0].strip() if "'" in nom_base else nom_base

            organism, created = find_or_match_organism(
                Organism, nom_latin=nom_base, nom_commun=nom_base, defaults={}
            )
            if not organism:
                skipped += 1
                continue

            # Préparer les mises à jour (fill_gaps)
            height_raw = _get_value(row, TOPIC_FIELD_ALIASES["height"])
            width_raw = _get_value(row, TOPIC_FIELD_ALIASES["width"])
            flowering_raw = _get_value(row, TOPIC_FIELD_ALIASES["flowering"])

            hauteur_max = _parse_float(height_raw)
            if hauteur_max is not None and hauteur_max > 50:
                hauteur_max = hauteur_max / 100  # cm -> m si valeur > 50
            largeur_max = _parse_float(width_raw)
            if largeur_max is not None and largeur_max > 20:
                largeur_max = largeur_max / 100  # cm -> m

            updates = {}
            if hauteur_max is not None and is_empty_value(organism.hauteur_max):
                updates["hauteur_max"] = hauteur_max
            if largeur_max is not None and is_empty_value(organism.largeur_max):
                updates["largeur_max"] = largeur_max

            if updates and not dry_run:
                for k, v in updates.items():
                    setattr(organism, k, v)
                organism.save(update_fields=list(updates.keys()))
                updated += 1

            # data_sources
            if not dry_run:
                sources = dict(organism.data_sources or {})
                topic_payload = {"latin": nom_latin, "height": height_raw, "width": width_raw, "flowering": flowering_raw}
                sources[SOURCE_TOPIC] = topic_payload
                organism.data_sources = sources
                organism.save(update_fields=["data_sources"])

            # OrganismCalendrier floraison
            if flowering_raw:
                m1, m2 = _parse_period(flowering_raw)
                if m1 is not None and not dry_run:
                    if not OrganismCalendrier.objects.filter(
                        organisme=organism, type_periode="floraison", source=SOURCE_TOPIC
                    ).exists():
                        OrganismCalendrier.objects.create(
                            organisme=organism,
                            type_periode="floraison",
                            mois_debut=m1,
                            mois_fin=m2 or m1,
                            source=SOURCE_TOPIC,
                        )
                        created_cal += 1

            ensure_organism_genus(organism)

        self.stdout.write(
            self.style.SUCCESS(
                f"Terminé: {updated} organismes mis à jour, {created_cal} calendrier, {skipped} ignorés."
            )
        )
