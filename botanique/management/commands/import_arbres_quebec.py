"""
Importe la présence des espèces dans l'inventaire « Arbres répertoriés » (Ville de Québec).
Ne crée pas d'arbres individuels : associe chaque espèce (NOM_LATIN, NOM_FRANCAIS) à un Organism
et enregistre data_sources['ville_quebec'].

Données : Données Québec, jeu « Arbres répertoriés » (vque_26), CSV avec NOM_LATIN, NOM_FRANCAIS.
Téléchargez le CSV depuis https://donneesquebec.ca/recherche/dataset/vque_26

Usage:
  python manage.py import_arbres_quebec --file arbres_quebec.csv [--limit 100]
"""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from botanique.models import Cultivar, Organism
from botanique.source_rules import (
    SOURCE_VILLE_QUEBEC,
    ensure_organism_genus,
    find_organism_and_cultivar,
    find_or_match_organism,
    get_unique_slug_latin,
    parse_cultivar_from_latin,
)

SOURCE_URL = "https://donneesquebec.ca/recherche/dataset/vque_26"


class Command(BaseCommand):
    help = (
        "Associe les espèces du fichier CSV (Arbres répertoriés - Ville de Québec) aux organismes. "
        "Remplit data_sources['ville_quebec']."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Fichier CSV téléchargé depuis Données Québec (colonnes NOM_LATIN, NOM_FRANCAIS).",
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
            help="Afficher les paires (nom_latin, nom_francais) sans modifier la base.",
        )

    def _normalize_header(self, name):
        return (name or "").strip().upper().replace(" ", "_")

    def handle(self, *args, **options):
        file_path = Path(options["file"])
        if not file_path.exists():
            self.stdout.write(self.style.ERROR(f"Fichier introuvable: {file_path}"))
            return

        limit = options["limit"] or 0
        dry_run = options["dry_run"]

        # Lire le CSV et extraire les paires uniques (nom_latin, nom_francais)
        seen = set()
        pairs = []
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f, delimiter=",")
                for row in reader:
                    nom_latin = (row.get("NOM_LATIN") or row.get("nom_latin") or "").strip()
                    nom_francais = (row.get("NOM_FRANCAIS") or row.get("nom_francais") or "").strip()
                    if not nom_latin:
                        continue
                    key = (nom_latin.lower(), (nom_francais or "").lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    pairs.append((nom_latin, nom_francais or nom_latin))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Erreur lecture CSV: {e}"))
            return

        if limit > 0:
            pairs = pairs[:limit]

        self.stdout.write(self.style.SUCCESS(f"Arbres Québec : {len(pairs)} espèces uniques à associer."))

        if dry_run:
            for nom_latin, nom_francais in pairs[:20]:
                self.stdout.write(f"  [DRY] {nom_latin} | {nom_francais}")
            if len(pairs) > 20:
                self.stdout.write(f"  ... et {len(pairs) - 20} autres.")
            return

        created = 0
        updated = 0
        for nom_latin, nom_francais in pairs:
            try:
                base_latin, nom_cultivar = parse_cultivar_from_latin(nom_latin)
                defaults = {"nom_commun": nom_francais, "regne": "plante"}
                if nom_cultivar and base_latin:
                    defaults["slug_latin"] = get_unique_slug_latin(Organism, base_latin)
                    organism, _cultivar, was_created = find_organism_and_cultivar(
                        Organism,
                        Cultivar,
                        nom_latin=nom_latin,
                        nom_commun=nom_francais,
                        defaults_organism=defaults,
                        defaults_cultivar={},
                    )
                else:
                    organism, was_created = find_or_match_organism(
                        Organism,
                        nom_latin=nom_latin,
                        nom_commun=nom_francais,
                        defaults=defaults,
                    )
                ensure_organism_genus(organism)
                existing_sources = dict(organism.data_sources or {})
                existing_sources[SOURCE_VILLE_QUEBEC] = {
                    "inventaire": True,
                    "source": "Arbres répertoriés - Ville de Québec",
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
