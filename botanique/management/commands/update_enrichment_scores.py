"""
Recalcule la note d'enrichissement (0-100 %) pour toutes les fiches Organism
et met à jour BaseEnrichmentStats. À lancer après migration ou manuellement.

Usage:
  python manage.py update_enrichment_scores
"""
from django.core.management.base import BaseCommand

from botanique.enrichment_score import update_enrichment_scores


class Command(BaseCommand):
    help = "Recalcule enrichment_score_pct pour tous les organismes et met à jour BaseEnrichmentStats."

    def handle(self, *args, **options):
        result = update_enrichment_scores()
        self.stdout.write(
            self.style.SUCCESS(
                f"Enrichissement: {result['updated']} fiches mises à jour, "
                f"note globale = {result['global_score_pct']}%"
            )
        )
