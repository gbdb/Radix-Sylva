"""
Recalcule search_vector pour tous les Organism (PostgreSQL uniquement).
À appeler après bulk_create/bulk_update car le signal post_save ne se déclenche pas.
"""
from django.db import connection
from django.core.management.base import BaseCommand

from botanique.models import Organism


class Command(BaseCommand):
    help = "Recalcule le champ search_vector pour tous les organismes (PostgreSQL)."

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            self.stdout.write(self.style.WARNING(
                "search_vector n'est géré que sur PostgreSQL. Ignoré."
            ))
            return
        # Inclut nom_commun, nom_latin, description, usages_autres + noms (OrganismNom) en une requête
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE species_espece SET search_vector =
                    setweight(to_tsvector('simple', coalesce(nom_commun, '')), 'A')
                    || setweight(to_tsvector('simple', coalesce(nom_latin, '')), 'A')
                    || setweight(to_tsvector('simple', coalesce(description, '')), 'B')
                    || setweight(to_tsvector('simple', coalesce(usages_autres, '')), 'C')
                    || coalesce(
                        (SELECT setweight(to_tsvector('simple', coalesce(string_agg(nom, ' '), '')), 'B')
                         FROM species_organismnom WHERE organism_id = species_espece.id),
                        to_tsvector('')
                    )
                """
            )
            updated = cursor.rowcount
        self.stdout.write(self.style.SUCCESS(f"search_vector mis à jour pour {updated} organisme(s)."))
