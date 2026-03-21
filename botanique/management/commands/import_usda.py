"""
Enrichit les organismes avec le TSN (Taxonomic Serial Number) ITIS/USDA.
Remplit tsn et data_sources['usda'] pour lier sans doublon.

Utilise l'API ITIS (Integrated Taxonomic Information System), utilisée par USDA Plants.
L'API ne trouve rien si le nom inclut l'auteur (ex. "Abies balsamea (Linnaeus) Miller").
On envoie donc uniquement le genre + espèce pour la recherche.
Usage:
  python manage.py import_usda --enrich --limit 50   # Enrichir les organismes existants sans tsn
  python manage.py import_usda --file noms.txt        # Fichier avec un nom latin par ligne
"""
import re
import sys
import time
from pathlib import Path

import requests
from django.core.management.base import BaseCommand

from botanique.models import Cultivar, Organism
from botanique.source_rules import (
    SOURCE_USDA,
    ensure_organism_genus,
    find_organism_and_cultivar,
    find_or_match_organism,
    get_unique_slug_latin,
    parse_cultivar_from_latin,
)

ITIS_SEARCH_URL = "https://www.itis.gov/ITISWebService/jsonservice/searchByScientificName"
USER_AGENT = "JardinBiot/1.0 (species import; Django management command)"


def _search_key_for_itis(nom_latin: str) -> str:
    """
    Clé de recherche pour ITIS : genre + espèce uniquement.
    L'API renvoie scientificNames: [null] si on envoie l'auteur (ex. "Acer platanoides Linnaeus").
    On retire les parenthèses (auteur) et on garde au plus les deux premiers mots (genre, espèce).
    """
    if not nom_latin or not nom_latin.strip():
        return ""
    s = re.sub(r"\s*\([^)]*\)", " ", nom_latin)
    s = " ".join(s.split()[:2]).strip()
    return s


def itis_search(session: requests.Session, nom_latin: str, delay: float = 0.5):
    """
    Recherche ITIS par nom scientifique. Retourne TSN (int) et données brutes ou None.
    """
    if not nom_latin or not nom_latin.strip():
        return None
    q = _search_key_for_itis(nom_latin)
    if not q:
        return None
    for attempt in range(3):
        try:
            r = session.get(
                ITIS_SEARCH_URL,
                params={"srchKey": q},
                timeout=15,
                headers={"User-Agent": USER_AGENT},
            )
            r.raise_for_status()
            data = r.json()
            if not data:
                return None
            raw_names = data.get("scientificNames")
            # ITIS peut renvoyer une liste, un seul objet ou null
            if isinstance(raw_names, list):
                names = [x for x in raw_names if isinstance(x, dict)]
            elif isinstance(raw_names, dict):
                names = [raw_names]
            else:
                names = []
            if not names:
                return None
            # Préférer Plantae et nom exact ou le premier
            for item in names:
                if not isinstance(item, dict):
                    continue
                if item.get("kingdom") == "Plantae":
                    tsn_str = item.get("tsn")
                    if tsn_str:
                        try:
                            tsn = int(tsn_str)
                            return {"tsn": tsn, "combinedName": item.get("combinedName"), "raw": item}
                        except (TypeError, ValueError):
                            continue
            first = names[0]
            if not isinstance(first, dict):
                return None
            tsn_str = first.get("tsn")
            if tsn_str:
                try:
                    tsn = int(tsn_str)
                    return {"tsn": tsn, "combinedName": first.get("combinedName"), "raw": first}
                except (TypeError, ValueError):
                    pass
            return None
        except (requests.RequestException, ValueError, KeyError) as e:
            if attempt == 2:
                raise
            time.sleep(1.0 * (attempt + 1))
    return None


class Command(BaseCommand):
    help = (
        "Enrichit les organismes avec le TSN (ITIS/USDA). "
        "Remplit tsn et data_sources['usda']. Utilisez --enrich ou --file."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--enrich",
            action="store_true",
            help="Enrichir les organismes existants sans tsn (recherche par nom_latin)",
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
            qs = Organism.objects.filter(tsn__isnull=True).exclude(nom_latin="").order_by("nom_latin")
            if limit > 0:
                qs = qs[:limit]
            names_to_process = [(o.nom_latin, o.nom_commun) for o in qs]
            self.stdout.write(self.style.SUCCESS(f"Enrichissement USDA/ITIS : {len(names_to_process)} organismes sans tsn."))
        elif file_path:
            path = Path(file_path)
            if not path.exists():
                self.stdout.write(self.style.ERROR(
                    f"Fichier introuvable : {path}. Vérifiez le chemin (ex. data/vascan/noms.txt)."
                ))
                sys.exit(1)
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            names_to_process = [(line.strip(), "") for line in lines if line.strip()]
            self.stdout.write(self.style.SUCCESS(f"Import USDA depuis {path}: {len(names_to_process)} noms."))
        else:
            self.stdout.write(self.style.ERROR(
                "Options requises : cochez « enrich » pour enrichir les organismes existants, "
                "ou fournissez un chemin de fichier dans « file » (ex. data/vascan/noms.txt)."
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

        for nom_latin, nom_commun in names_to_process:
            if not nom_latin:
                skipped += 1
                continue
            time.sleep(delay)
            try:
                result = itis_search(session, nom_latin, delay=delay)
                if not result:
                    skipped += 1
                    continue

                tsn = result["tsn"]
                combined_name = result.get("combinedName") or nom_latin

                defaults = {
                    "nom_latin": combined_name,
                    "nom_commun": nom_commun or combined_name,
                    "regne": "plante",
                }
                base_latin, nom_cultivar = parse_cultivar_from_latin(combined_name)
                if nom_cultivar and base_latin:
                    defaults["slug_latin"] = get_unique_slug_latin(Organism, base_latin)
                    organism, _cultivar, was_created = find_organism_and_cultivar(
                        Organism,
                        Cultivar,
                        nom_latin=combined_name,
                        nom_commun=nom_commun or combined_name,
                        defaults_organism=defaults,
                        defaults_cultivar={},
                        tsn=tsn,
                    )
                else:
                    organism, was_created = find_or_match_organism(
                        Organism,
                        nom_latin=combined_name,
                        nom_commun=nom_commun or combined_name,
                        defaults=defaults,
                        tsn=tsn,
                    )

                ensure_organism_genus(organism)
                existing_sources = dict(organism.data_sources or {})
                raw = result.get("raw") if isinstance(result.get("raw"), dict) else result
                existing_sources[SOURCE_USDA] = raw
                organism.data_sources = existing_sources
                organism.tsn = tsn
                organism.save(update_fields=["data_sources", "tsn"])

                if was_created:
                    created += 1
                    self.stdout.write(f"  Créé: {organism.nom_commun} ({combined_name}) tsn={tsn}")
                else:
                    updated += 1
                    self.stdout.write(f"  Mis à jour: {organism.nom_commun} tsn={tsn}")

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
