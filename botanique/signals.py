"""Signals : search_vector sur Organism (PostgreSQL)."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from botanique.models import Organism


@receiver(post_save, sender=Organism)
def update_organism_search_vector(sender, instance, update_fields=None, **kwargs):
    if update_fields is not None and update_fields == frozenset({'search_vector'}):
        return
    from django.db import connection

    if connection.vendor != 'postgresql':
        return
    if not hasattr(Organism, 'search_vector') or not hasattr(instance, 'search_vector'):
        return
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
            WHERE id = %s
            """,
            [instance.pk],
        )
