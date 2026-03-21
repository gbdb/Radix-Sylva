"""
Importe ou enrichit les organismes avec les données VASCAN (Canadensys).
Remplit vascan_id et data_sources['vascan'] pour lier sans doublon.

VASCAN ne liste pas les cultivars (ex. Acer palmatum 'Bloodgood'). On envoie donc
d'abord le nom complet, puis en secours le genre + espèce pour obtenir au moins le
vascan_id de l'espèce.
Usage:
  python manage.py import_vascan --enrich --limit 50   # Enrichir les organismes existants sans vascan_id
  python manage.py import_vascan --file noms.txt        # Fichier avec un nom latin par ligne
"""
import re
import sys
import time
from pathlib import Path

import requests
from django.core.management.base import BaseCommand

from botanique.models import Organism
from botanique.source_rules import SOURCE_VASCAN, find_or_match_organism

VASCAN_SEARCH_URL = "http://data.canadensys.net/vascan/api/0.1/search.json"
USER_AGENT = "JardinBiot/1.0 (species import; Django management command)"


def _search_key_for_vascan(nom_latin: str) -> str:
    """
    Clé de recherche pour VASCAN : genre + espèce uniquement.
    VASCAN ne renvoie rien pour les cultivars (ex. Acer palmatum 'Bloodgood') ni
    pour les noms avec auteur. On retire parenthèses et tout après, et on garde
    au plus les deux premiers mots (genre, espèce).
    """
    if not nom_latin or not nom_latin.strip():
        return ""
    s = re.sub(r"\s*\([^)]*\)", " ", nom_latin.strip())
    s = " ".join(s.split()[:2]).strip()
    return s


def vascan_search(session: requests.Session, nom_latin: str, delay: float = 0.5):
    """
    Recherche VASCAN par nom scientifique.
    Essaie d'abord le nom complet, puis en secours le genre+espèce (sans auteur/cultivar).
    Retourne le premier match avec taxonID et données brutes, ou None.
    """
    if not nom_latin or not nom_latin.strip():
        return None
    full_q = nom_latin.strip()
    search_keys = [full_q]
    key_species = _search_key_for_vascan(nom_latin)
    if key_species and key_species != full_q:
        search_keys.append(key_species)
    for q in search_keys:
        for attempt in range(3):
            try:
                r = session.get(
                    VASCAN_SEARCH_URL,
                    params={"q": q},
                    timeout=15,
                    headers={"User-Agent": USER_AGENT},
                )
                r.raise_for_status()
                data = r.json()
                results = data.get("results") or []
                if not results:
                    break
                first = results[0]
                matches = first.get("matches") or []
                if not matches:
                    break
                match = matches[0]
                taxon_id = match.get("taxonID")
                if taxon_id is None:
                    break
                return {
                    "taxonID": taxon_id,
                    "scientificName": match.get("scientificName"),
                    "canonicalName": match.get("canonicalName"),
                    "vernacularNames": match.get("vernacularNames", []),
                    "distribution": match.get("distribution", []),
                    "taxonomicAssertions": match.get("taxonomicAssertions", []),
                    "raw": match,
                }
            except (requests.RequestException, ValueError, KeyError):
                if attempt == 2:
                    raise
                time.sleep(1.0 * (attempt + 1))
    return None


class Command(BaseCommand):
    help = (
        "Importe ou enrichit les organismes avec VASCAN (Canadensys). "
        "Remplit vascan_id et data_sources['vascan']. Utilisez --enrich pour les organismes existants ou --file pour une liste de noms."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--enrich",
            action="store_true",
            help="Enrichir les organismes existants sans vascan_id (recherche par nom_latin)",
        )
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            help="Fichier avec un nom scientifique latin par ligne (sans --enrich)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Nombre max d'organismes à traiter (0 = illimité). Avec --enrich uniquement.",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=0.5,
            help="Délai en secondes entre chaque appel API (défaut: 0.5)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Afficher ce qui serait fait sans modifier la base",
        )

    def handle(self, *args, **options):
        enrich = options["enrich"]
        file_path = options.get("file")
        limit = options["limit"] or 0
        delay = max(0.3, options["delay"])
        dry_run = options["dry_run"]

        if enrich:
            qs = Organism.objects.filter(vascan_id__isnull=True).exclude(nom_latin="").order_by("nom_latin")
            if limit > 0:
                qs = qs[:limit]
            names_to_process = [(o.nom_latin, o.nom_commun) for o in qs]
            self.stdout.write(self.style.SUCCESS(f"Enrichissement VASCAN : {len(names_to_process)} organismes sans vascan_id."))
        elif file_path:
            path = Path(file_path)
            if not path.exists():
                self.stdout.write(self.style.ERROR(f"Fichier introuvable: {path}"))
                return
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            # Un nom par ligne ; si tab-delimited (export VASCAN), prendre la première colonne
            names_to_process = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                nom_latin = line.split("\t")[0].strip() if "\t" in line else line
                if nom_latin:
                    names_to_process.append((nom_latin, ""))
            self.stdout.write(self.style.SUCCESS(f"Import VASCAN depuis {path}: {len(names_to_process)} noms (création d'espèces)."))
        else:
            self.stdout.write(self.style.ERROR(
                "Options requises : cochez « enrich » pour enrichir les organismes existants, "
                "ou fournissez un chemin de fichier dans « file » (un nom latin par ligne)."
            ))
            sys.exit(1)

        if dry_run:
            self.stdout.write(self.style.WARNING("Mode dry-run : aucune modification."))
            for nom_latin, _ in names_to_process[:10]:
                self.stdout.write(f"  [DRY] {nom_latin}")
            if len(names_to_process) > 10:
                self.stdout.write(f"  ... et {len(names_to_process) - 10} autres.")
            return

        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

        created = 0
        updated = 0
        skipped = 0
        errors = 0

        for i, (nom_latin, nom_commun) in enumerate(names_to_process):
            if not nom_latin:
                skipped += 1
                continue
            time.sleep(delay)
            try:
                result = vascan_search(session, nom_latin, delay=delay)
                if not result:
                    skipped += 1
                    continue

                taxon_id = result["taxonID"]
                scientific_name = result.get("scientificName") or result.get("canonicalName") or nom_latin
                # Nom français préféré si disponible
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
                common_name = fr_name or nom_commun or scientific_name

                defaults = {
                    "nom_latin": scientific_name,
                    "nom_commun": common_name,
                    "regne": "plante",
                    "indigene": False,
                }
                # Distribution: détecter indigène (native) au Québec
                for d in result.get("distribution") or []:
                    if d.get("locationID") == "ISO 3166-2:CA-QC" and d.get("occurrenceStatus") in ("native", "present"):
                        defaults["indigene"] = True
                        break

                organism, was_created = find_or_match_organism(
                    Organism,
                    nom_latin=scientific_name,
                    nom_commun=common_name,
                    defaults=defaults,
                    vascan_id=taxon_id,
                )

                existing_sources = dict(organism.data_sources or {})
                existing_sources[SOURCE_VASCAN] = result.get("raw", result)
                organism.data_sources = existing_sources
                organism.vascan_id = taxon_id
                if defaults.get("indigene") is True:
                    organism.indigene = True
                organism.save(update_fields=["data_sources", "vascan_id", "indigene"])

                if was_created:
                    created += 1
                    self.stdout.write(f"  Créé: {common_name} ({scientific_name}) vascan_id={taxon_id}")
                else:
                    updated += 1
                    self.stdout.write(f"  Mis à jour: {organism.nom_commun} vascan_id={taxon_id}")

            except Exception as e:
                errors += 1
                self.stdout.write(self.style.WARNING(f"  Erreur {nom_latin}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"\nTerminé: {created} créés, {updated} mis à jour, {skipped} ignorés, {errors} erreurs."))
        try:
            from botanique.enrichment_score import update_enrichment_scores
            res = update_enrichment_scores()
            self.stdout.write(self.style.SUCCESS(f"  Enrichissement: note globale {res['global_score_pct']}%"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Recalcul enrichissement: {e}"))
