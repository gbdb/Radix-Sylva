"""
Vide les données botaniques Radix Sylva (développement / reset).
Ne supprime pas les comptes utilisateurs ni la table Amendment globale.

Usage:
  python manage.py wipe_species
  python manage.py wipe_species --no-input
"""
from django.core.management.base import BaseCommand

from botanique.models import (
    BaseEnrichmentStats,
    CompanionRelation,
    Cultivar,
    CultivarPollinator,
    CultivarPorteGreffe,
    DataImportRun,
    Organism,
    OrganismAmendment,
    OrganismCalendrier,
    OrganismNom,
    OrganismPhoto,
    OrganismPropriete,
    OrganismUsage,
)


class Command(BaseCommand):
    help = (
        "Supprime organismes, cultivars, compagnonnage, photos espèce, exécutions d'import, etc. "
        "(Radix Sylva uniquement — pas de spécimens ni jardins)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-input',
            action='store_true',
            help='Ne pas demander de confirmation',
        )

    def handle(self, *args, **options):
        if not options['no_input']:
            if (
                input('Vider toute la base botanique Radix Sylva ? (oui/non): ').strip().lower()
                != 'oui'
            ):
                self.stdout.write(self.style.WARNING('Annulé.'))
                return

        counts = {}

        self.stdout.write('Détachement photo_principale…')
        Organism.objects.all().update(photo_principale=None)

        self.stdout.write('Suppression porte-greffes / pollinisateurs cultivars…')
        counts['porte_greffes'] = CultivarPorteGreffe.objects.count()
        CultivarPorteGreffe.objects.all().delete()
        counts['pollinators'] = CultivarPollinator.objects.count()
        CultivarPollinator.objects.all().delete()

        self.stdout.write('Suppression cultivars…')
        counts['cultivars'] = Cultivar.objects.count()
        Cultivar.objects.all().delete()

        self.stdout.write('Suppression compagnonnage et liens organisme…')
        counts['companions'] = CompanionRelation.objects.count()
        CompanionRelation.objects.all().delete()
        counts['org_amendments'] = OrganismAmendment.objects.count()
        OrganismAmendment.objects.all().delete()
        counts['org_nom'] = OrganismNom.objects.count()
        OrganismNom.objects.all().delete()
        counts['org_prop'] = OrganismPropriete.objects.count()
        OrganismPropriete.objects.all().delete()
        counts['org_usage'] = OrganismUsage.objects.count()
        OrganismUsage.objects.all().delete()
        counts['org_cal'] = OrganismCalendrier.objects.count()
        OrganismCalendrier.objects.all().delete()

        self.stdout.write('Suppression photos espèce…')
        counts['photos'] = OrganismPhoto.objects.count()
        OrganismPhoto.objects.all().delete()

        self.stdout.write('Suppression organismes…')
        counts['organisms'] = Organism.objects.count()
        Organism.objects.all().delete()

        self.stdout.write('Suppression historique imports…')
        counts['import_runs'] = DataImportRun.objects.count()
        DataImportRun.objects.all().delete()

        self.stdout.write('Réinitialisation stats enrichissement…')
        BaseEnrichmentStats.objects.all().delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Terminé. Organismes: {counts.get('organisms', 0)}, "
                f"cultivars: {counts.get('cultivars', 0)}, photos: {counts.get('photos', 0)}."
            )
        )
