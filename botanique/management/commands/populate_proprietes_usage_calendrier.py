"""
Remplit les tables OrganismPropriete, OrganismUsage et OrganismCalendrier
à partir des données déjà présentes sur Organism (sol_textures, sol_ph, besoin_soleil,
parties_comestibles, usages_autres, periode_recolte) et de data_sources (hydroquebec, usda, etc.).

Extrait aussi floraison/fructification depuis fleursDescription et fruitsDescription (Hydro-Québec).

Usage:
  python manage.py populate_proprietes_usage_calendrier [--limit 0] [--dry-run]
"""
import re
from django.core.management.base import BaseCommand

from botanique.models import Organism, OrganismPropriete, OrganismUsage, OrganismCalendrier
from botanique.source_rules import SOURCE_HYDROQUEBEC, SOURCE_PFAF, SOURCE_USDA

MOIS_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}
MOIS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

# Saisons -> (mois_debut, mois_fin)
SAISON_TO_MOIS = {
    "printemps": (3, 5),
    "ete": (6, 8),
    "été": (6, 8),
    "automne": (9, 11),
    "hiver": (12, 2),
}


def parse_periode_recolte(texte):
    """
    Parse une chaîne du type "Juillet-Septembre", "Octobre", "July - September".
    Retourne (mois_debut, mois_fin) ou (None, None).
    """
    if not texte or not isinstance(texte, str):
        return None, None
    t = texte.strip().lower()
    if not t:
        return None, None
    all_months = {**MOIS_FR, **MOIS_EN}
    # Pattern: "mois1 - mois2" ou "mois1-mois2" ou "mois"
    for sep in ["-", "–", "—", " to ", " and "]:
        if sep in t:
            parts = re.split(rf"\s*{re.escape(sep)}\s*", t, 1)
            if len(parts) == 2:
                m1 = all_months.get(parts[0].strip())
                m2 = all_months.get(parts[1].strip())
                if m1 is not None and m2 is not None:
                    return m1, m2
    for name, num in all_months.items():
        if name in t:
            return num, num
    return None, None


def parse_period_from_hq_text(texte):
    """
    Parse fleursDescription ou fruitsDescription HQ pour extraire (mois_debut, mois_fin).
    Détecte: "Saison : printemps", "Saison ; automne", "en mai", "mai-juin", "de mai à juillet".
    Retourne (mois_debut, mois_fin) ou (None, None).
    """
    if not texte or not isinstance(texte, str):
        return None, None
    t = texte.strip().lower()
    if not t or "sans intérêt" in t or "sans fructification" in t:
        return None, None
    all_months = {**MOIS_FR, **MOIS_EN}

    # "Saison : printemps" ou "Saison ; printemps"
    match = re.search(r"saison\s*[;:]\s*(\w+)", t, re.IGNORECASE)
    if match:
        saison = match.group(1).lower()
        if saison in SAISON_TO_MOIS:
            return SAISON_TO_MOIS[saison]

    # "de mai à juillet", "mai-juin", "mai à septembre"
    match = re.search(r"(?:en|de)\s+(\w+)\s+(?:à|a|-|–)\s+(\w+)", t, re.IGNORECASE)
    if match:
        m1, m2 = all_months.get(match.group(1)), all_months.get(match.group(2))
        if m1 is not None and m2 is not None:
            return m1, m2
    match = re.search(r"(\w+)\s*(?:-|–|à|a)\s*(\w+)", t, re.IGNORECASE)
    if match:
        m1, m2 = all_months.get(match.group(1)), all_months.get(match.group(2))
        if m1 is not None and m2 is not None:
            return m1, m2
    # "en mai", "au mois de mai"
    match = re.search(r"(?:en|au)\s+(?:mois\s+de\s+)?(\w+)", t, re.IGNORECASE)
    if match:
        m1 = all_months.get(match.group(1))
        if m1 is not None:
            return m1, m1

    # Mois isolé dans le texte
    for name, num in all_months.items():
        if re.search(r"\b" + re.escape(name) + r"\b", t):
            return num, num
    return None, None


class Command(BaseCommand):
    help = (
        "Remplit OrganismPropriete, OrganismUsage, OrganismCalendrier "
        "à partir des champs Organism et data_sources."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Nombre max d'organismes à traiter (0 = tout).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Afficher ce qui serait créé sans écrire en base.",
        )

    def handle(self, *args, **options):
        limit = options["limit"] or 0
        dry_run = options["dry_run"]

        qs = Organism.objects.all().order_by("id")
        if limit > 0:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(self.style.SUCCESS(f"Peuplement : {total} organismes à traiter."))

        if dry_run:
            self.stdout.write(self.style.WARNING("Mode dry-run : aucune modification."))

        n_proprietes = 0
        n_usages = 0
        n_calendrier = 0

        for organism in qs:
            sources = organism.data_sources or {}
            # Déterminer la source (HQ > USDA > PFAF > première dispo > derived)
            source_propriete = None
            if SOURCE_HYDROQUEBEC in sources:
                source_propriete = SOURCE_HYDROQUEBEC
            elif SOURCE_USDA in sources:
                source_propriete = SOURCE_USDA
            elif SOURCE_PFAF in sources:
                source_propriete = SOURCE_PFAF
            elif sources:
                source_propriete = next(iter(sources.keys()), "derived")
            else:
                source_propriete = "derived"

            if source_propriete and (organism.sol_textures or organism.sol_ph or organism.besoin_soleil):
                if not dry_run and not OrganismPropriete.objects.filter(organisme=organism, source=source_propriete).exists():
                    OrganismPropriete.objects.create(
                        organisme=organism,
                        type_sol=organism.sol_textures or [],
                        ph_min=None,
                        ph_max=None,
                        tolerance_ombre=organism.besoin_soleil or "",
                        source=source_propriete,
                    )
                    n_proprietes += 1
                elif dry_run:
                    n_proprietes += 1

            if organism.parties_comestibles or organism.usages_autres:
                if not dry_run:
                    if organism.parties_comestibles and not OrganismUsage.objects.filter(
                        organisme=organism, type_usage="comestible_autre", source=source_propriete
                    ).exists():
                        OrganismUsage.objects.create(
                            organisme=organism,
                            type_usage="comestible_autre",
                            parties=organism.parties_comestibles[:200],
                            description=organism.parties_comestibles,
                            source=source_propriete,
                        )
                        n_usages += 1
                    if organism.usages_autres and not OrganismUsage.objects.filter(
                        organisme=organism, type_usage="autre", source=source_propriete
                    ).exists():
                        OrganismUsage.objects.create(
                            organisme=organism,
                            type_usage="medicinal" if "médicinal" in (organism.usages_autres or "").lower() else "autre",
                            description=(organism.usages_autres or "")[:500],
                            source=source_propriete,
                        )
                        n_usages += 1
                else:
                    n_usages += 1

            if organism.periode_recolte:
                mois_debut, mois_fin = parse_periode_recolte(organism.periode_recolte)
                if mois_debut is not None and not dry_run:
                    if not OrganismCalendrier.objects.filter(
                        organisme=organism, type_periode="recolte", source=source_propriete
                    ).exists():
                        OrganismCalendrier.objects.create(
                            organisme=organism,
                            type_periode="recolte",
                            mois_debut=mois_debut,
                            mois_fin=mois_fin or mois_debut,
                            source=source_propriete,
                        )
                        n_calendrier += 1
                elif dry_run and mois_debut:
                    n_calendrier += 1

            # Phase 1B: extraire floraison/fructification depuis fleursDescription et fruitsDescription (HQ)
            hq = sources.get(SOURCE_HYDROQUEBEC) or {}
            fleurs = hq.get("fleursDescription") or ""
            fruits = hq.get("fruitsDescription") or ""
            for type_periode, texte in [("floraison", fleurs), ("fructification", fruits)]:
                mois_debut, mois_fin = parse_period_from_hq_text(texte)
                if mois_debut is not None and not dry_run:
                    if not OrganismCalendrier.objects.filter(
                        organisme=organism, type_periode=type_periode, source=SOURCE_HYDROQUEBEC
                    ).exists():
                        OrganismCalendrier.objects.create(
                            organisme=organism,
                            type_periode=type_periode,
                            mois_debut=mois_debut,
                            mois_fin=mois_fin or mois_debut,
                            source=SOURCE_HYDROQUEBEC,
                        )
                        n_calendrier += 1
                elif dry_run and mois_debut:
                    n_calendrier += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nTerminé: {n_proprietes} propriétés, {n_usages} usages, {n_calendrier} calendrier."
            )
        )
        try:
            from botanique.enrichment_score import update_enrichment_scores
            res = update_enrichment_scores()
            self.stdout.write(self.style.SUCCESS(f"  Enrichissement: note globale {res['global_score_pct']}%"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Recalcul enrichissement: {e}"))
