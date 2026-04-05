"""
Extrait l'âge de première fructification depuis OrganismPFAF.cultivation_details (texte PFAF)
et renseigne Organism.age_fructification lorsqu'il est vide (sauf --overwrite).

Ne modifie pas cultivation_details.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from django.core.management.base import BaseCommand
from django.utils import timezone

from botanique.models import DataImportRun, OrganismPFAF

RE_FLAGS = re.IGNORECASE

# Âge accepté (hors plage → essayer le motif suivant, pas d'écriture)
AGE_MIN = 1
AGE_MAX = 50


def _valid_age(n: int) -> bool:
    return AGE_MIN <= n <= AGE_MAX


def _compile_patterns() -> List[Tuple[re.Pattern[str], str]]:
    """Liste (regex, mode) : 'first' = groupe 1, 'min' = min(g1, g2). Ordre strict."""
    return [
        # 1
        (re.compile(r"fruits?\s+in\s+(\d+)\s+to\s+(\d+)\s+years?", RE_FLAGS), "min"),
        # 2
        (re.compile(r"fruits?\s+in\s+(\d+)\s+years?", RE_FLAGS), "first"),
        # 3
        (re.compile(r"bears?\s+fruit\s+in\s+(\d+)\s+years?", RE_FLAGS), "first"),
        # 4
        (re.compile(r"fruit(?:ing)?\s+after\s+(\d+)\s+years?", RE_FLAGS), "first"),
        # 5
        (re.compile(r"first\s+fruits?\s+at\s+(\d+)\s+years?", RE_FLAGS), "first"),
        # 6
        (re.compile(r"produces?\s+in\s+(\d+)\s+to\s+(\d+)\s+years?", RE_FLAGS), "min"),
        # 7
        (re.compile(r"(\d+)\s+to\s+(\d+)\s+years?\s+to\s+fruit", RE_FLAGS), "min"),
        # 8 (évite « 5 years to fruit » dans « 3-5 years to fruit » — le 2e chiffre suit un tiret)
        (re.compile(r"(?<![-])(\d+)\s+years?\s+(?:to|before)\s+fruits?", RE_FLAGS), "first"),
        # 9
        (re.compile(r"flowers?\s+in\s+(\d+)\s+years?", RE_FLAGS), "first"),
        # 10
        (re.compile(r"matures?\s+in\s+(\d+)\s+years?", RE_FLAGS), "first"),
        # 11
        (
            re.compile(
                r"takes\s+(\d+)\s+years?\s+(?:to|before)\s+(?:bear(?:\s+fruit)?|produce|fruit|fruiting)",
                RE_FLAGS,
            ),
            "first",
        ),
        # 12
        (
            re.compile(
                r"(\d+)\s*-\s*(\d+)\s+years?\s+(?:to|before)\s+(?:bear(?:\s+fruit)?|fruit|fruits?)",
                RE_FLAGS,
            ),
            "min",
        ),
        # 13
        (re.compile(r"after\s+(\d+)\s+years?\s+of\s+growth", RE_FLAGS), "first"),
        # 14
        (
            re.compile(
                r"(\d+)\s+years?\s+old\s+before\s+(?:it\s+)?fruits?",
                RE_FLAGS,
            ),
            "first",
        ),
    ]


PATTERNS = _compile_patterns()


def extract_age_fructification(text: str) -> Tuple[Optional[int], Optional[re.Match[str]]]:
    """
    Premier motif qui produit un entier dans [AGE_MIN, AGE_MAX] gagne.
    Retourne (valeur, match) ou (None, None).
    """
    if not (text or "").strip():
        return None, None

    for regex, mode in PATTERNS:
        m = regex.search(text)
        if not m:
            continue
        if mode == "min":
            a = int(m.group(1))
            b = int(m.group(2))
            v = min(a, b)
        else:
            v = int(m.group(1))
        if _valid_age(v):
            return v, m
    return None, None


class Command(BaseCommand):
    help = (
        "Extrait l'âge de fructification depuis OrganismPFAF.cultivation_details "
        f"et met à jour Organism.age_fructification ({AGE_MIN}–{AGE_MAX} ans)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simule sans enregistrer les mises à jour Organism.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Traiter au plus N enregistrements OrganismPFAF (0 = tout).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Mettre à jour même si age_fructification est déjà renseigné.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        limit: int = options["limit"]
        overwrite: bool = options["overwrite"]
        verbosity: int = options["verbosity"]

        qs = OrganismPFAF.objects.select_related("organism").exclude(cultivation_details="")
        if not overwrite:
            qs = qs.filter(organism__age_fructification__isnull=True)
        if limit > 0:
            qs = qs[:limit]

        stats = {
            "enriched": 0,
            "skipped": 0,
            "errors": 0,
            "processed": 0,
            "dry_run": dry_run,
            "limit": limit,
            "overwrite": overwrite,
            "enrich_command": "age_fructification",
        }

        run = DataImportRun.objects.create(
            source="pfaf",
            status="running",
            trigger="gestion_donnees",
            stats={**stats, "note": "enrich_command=age_fructification (regex cultivation_details)"},
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Enrichissement âge fructification depuis PFAF cultivation_details"
                + (" [DRY-RUN]" if dry_run else "")
            )
        )

        try:
            for pfaf in qs.iterator():
                stats["processed"] += 1
                org = pfaf.organism
                text = pfaf.cultivation_details or ""

                value, match = extract_age_fructification(text)
                if value is None:
                    stats["skipped"] += 1
                    continue

                if verbosity >= 2:
                    frag = (match.group(0) if match else "")[:200]
                    self.stdout.write(
                        f"  [{org.nom_latin}] «{frag}» → {value}"
                    )

                if dry_run:
                    stats["enriched"] += 1
                    continue

                try:
                    org.age_fructification = value
                    org.save(update_fields=["age_fructification"])
                    stats["enriched"] += 1
                except Exception as e:
                    stats["errors"] += 1
                    if stats["errors"] <= 10:
                        self.stdout.write(
                            self.style.WARNING(f"  Erreur save {org.nom_latin}: {e}")
                        )

            run.status = "success"
            run.finished_at = timezone.now()
            run.stats = stats
            run.save()

            self.stdout.write(self.style.SUCCESS("\nTerminé."))
            self.stdout.write(
                f"  Traités: {stats['processed']}\n"
                f"  Enrichis: {stats['enriched']}\n"
                f"  Ignorés (pas de match valide): {stats['skipped']}\n"
                f"  Erreurs: {stats['errors']}"
            )
            if dry_run:
                self.stdout.write(
                    self.style.WARNING("  [DRY-RUN] Aucune donnée persistée.")
                )

        except Exception as e:
            run.status = "failure"
            run.finished_at = timezone.now()
            run.output_snippet = str(e)[:2000]
            run.stats = stats
            run.save()
            raise
