"""
Importe la présence des espèces dans l'inventaire « Arbres publics » (Ville de Montréal).
Associe chaque essence (genre/espèce) à un Organism et enregistre data_sources['ville_montreal'].

Données : Données ouvertes Montréal, dataset « Arbres ».
Téléchargez le CSV depuis https://donnees.montreal.ca/dataset/arbres

Les colonnes peuvent varier (ex. ESSENCE, NOM_LATIN, genre, espece). On tente d'extraire
un nom scientifique (genre + espèce) pour le matching.

Usage:
  python manage.py import_arbres_montreal --file arbres_montreal.csv [--limit 100]
"""
import csv
import re
from pathlib import Path

from django.core.management.base import BaseCommand

from botanique.models import Cultivar, Organism
from botanique.source_rules import (
    SOURCE_VILLE_MONTREAL,
    ensure_organism_genus,
    find_organism_and_cultivar,
    find_or_match_organism,
    get_unique_slug_latin,
    parse_cultivar_from_latin,
)

SOURCE_URL = "https://donnees.montreal.ca/dataset/arbres"


def extract_nom_latin(row):
    """
    Extrait un nom latin depuis une ligne CSV.
    Colonnes possibles : ESSENCE, NOM_LATIN, nom_latin, genre + espece, scientific_name, etc.
    """
    essence = (row.get("ESSENCE") or row.get("essence") or row.get("NOM_LATIN") or row.get("nom_latin") or "").strip()
    if essence:
        # Parfois "Acer saccharum" ou "Acer  saccharum"
        return re.sub(r"\s+", " ", essence)
    genre = (row.get("genre") or row.get("GENRE") or "").strip()
    espece = (row.get("espece") or row.get("ESPECE") or row.get("species") or "").strip()
    if genre and espece:
        return f"{genre} {espece}"
    if genre:
        return genre
    return ""


class Command(BaseCommand):
    help = (
        "Associe les espèces du fichier CSV (Arbres publics - Ville de Montréal) aux organismes. "
        "Remplit data_sources['ville_montreal']."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Fichier CSV téléchargé depuis Données Montréal (colonnes ESSENCE ou genre/espece).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Nombre max d'espèces uniques à traiter (0 = tout).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Afficher les noms extraits sans modifier la base.",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file"])
        if not file_path.exists():
            self.stdout.write(self.style.ERROR(f"Fichier introuvable: {file_path}"))
            return

        limit = options["limit"] or 0
        dry_run = options["dry_run"]

        seen = set()
        names = []
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f, delimiter=",")
                for row in reader:
                    nom_latin = extract_nom_latin(row)
                    if not nom_latin or len(nom_latin) < 3:
                        continue
                    key = nom_latin.lower().strip()
                    if key in seen:
                        continue
                    seen.add(key)
                    names.append(nom_latin)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Erreur lecture CSV: {e}"))
            return

        if limit > 0:
            names = names[:limit]

        self.stdout.write(self.style.SUCCESS(f"Arbres Montréal : {len(names)} essences uniques à associer."))

        if dry_run:
            for nom in names[:20]:
                self.stdout.write(f"  [DRY] {nom}")
            if len(names) > 20:
                self.stdout.write(f"  ... et {len(names) - 20} autres.")
            return

        created = 0
        updated = 0
        for nom_latin in names:
            try:
                base_latin, nom_cultivar = parse_cultivar_from_latin(nom_latin)
                defaults = {"nom_commun": nom_latin, "regne": "plante"}
                if nom_cultivar and base_latin:
                    defaults["slug_latin"] = get_unique_slug_latin(Organism, base_latin)
                    organism, _cultivar, was_created = find_organism_and_cultivar(
                        Organism,
                        Cultivar,
                        nom_latin=nom_latin,
                        nom_commun=nom_latin,
                        defaults_organism=defaults,
                        defaults_cultivar={},
                    )
                else:
                    organism, was_created = find_or_match_organism(
                        Organism,
                        nom_latin=nom_latin,
                        nom_commun=nom_latin,
                        defaults=defaults,
                    )
                ensure_organism_genus(organism)
                existing_sources = dict(organism.data_sources or {})
                existing_sources[SOURCE_VILLE_MONTREAL] = {
                    "inventaire": True,
                    "source": "Arbres publics - Ville de Montréal",
                    "url": SOURCE_URL,
                }
                organism.data_sources = existing_sources
                organism.save(update_fields=["data_sources"])
                if was_created:
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  Erreur {nom_latin}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"\nTerminé: {created} créés, {updated} mis à jour."))
