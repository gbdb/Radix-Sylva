"""
Remplit le champ genus des Organism à partir du nom latin (premier mot après nettoyage).

Usage:
  python manage.py populate_genus           # Uniquement les organismes dont genus est vide
  python manage.py populate_genus --all     # Tous les organismes avec nom_latin
  python manage.py populate_genus --dry-run # Affiche sans modifier
"""
from django.core.management.base import BaseCommand

from botanique.models import Organism
from botanique.source_rules import get_genus_from_nom_latin


class Command(BaseCommand):
    help = "Remplit organism.genus à partir de nom_latin (extraction scientifique du genre)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Mettre à jour tous les organismes avec nom_latin (pas seulement genus vide).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Afficher les mises à jour sans écrire en base.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        update_all = options['all']

        qs = Organism.objects.filter(nom_latin__isnull=False).exclude(nom_latin='')
        if not update_all:
            qs = qs.filter(genus__in=('', None))

        total = qs.count()
        updated = 0
        for organism in qs.iterator():
            genus = get_genus_from_nom_latin(organism.nom_latin or '')
            if not genus:
                continue
            if organism.genus == genus:
                continue
            if dry_run:
                self.stdout.write(
                    f"  {organism.nom_latin!r} → genus={genus!r} (actuel: {organism.genus!r})"
                )
                updated += 1
                continue
            organism.genus = genus
            organism.save(update_fields=['genus'])
            updated += 1

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Dry-run : {updated} organisme(s) seraient mis à jour (sur {total} éligible(s))."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Terminé : {updated} organisme(s) mis à jour."))
