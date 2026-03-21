"""
Supprime les organismes sans clé "hydroquebec" dans data_sources (Radix Sylva).
Supprime d’abord cultivars, photos, compagnonnage, etc. liés à ces organismes.

Usage:
  python manage.py clean_organisms_keep_hq
  python manage.py clean_organisms_keep_hq --no-input
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q
from django.db.utils import OperationalError

from botanique.models import (
    CompanionRelation,
    Cultivar,
    CultivarPollinator,
    CultivarPorteGreffe,
    Organism,
    OrganismAmendment,
    OrganismCalendrier,
    OrganismNom,
    OrganismPhoto,
    OrganismPropriete,
    OrganismUsage,
)


class Command(BaseCommand):
    help = "Garde uniquement les organismes avec data_sources['hydroquebec']."

    def add_arguments(self, parser):
        parser.add_argument('--no-input', action='store_true', help='Sans confirmation')

    def handle(self, *args, **options):
        def _delete_organisms_raw_by_ids(ids: list[int], batch_size: int = 900) -> int:
            if not ids:
                return 0
            cursor = connection.connection.cursor()
            try:
                total = 0
                ph = '%s' if connection.vendor == 'postgresql' else '?'
                for i in range(0, len(ids), batch_size):
                    batch = ids[i : i + batch_size]
                    placeholders = ','.join([ph] * len(batch))
                    cursor.execute(
                        f'DELETE FROM species_espece WHERE id IN ({placeholders})',
                        batch,
                    )
                    total += len(batch)
                return total
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass

        if connection.vendor == 'postgresql':
            to_delete_qs = Organism.objects.exclude(data_sources__has_key='hydroquebec')
        else:
            pks = [
                o.pk
                for o in Organism.objects.only('pk', 'data_sources').iterator()
                if 'hydroquebec' not in (o.data_sources or {})
            ]
            to_delete_qs = Organism.objects.filter(pk__in=pks)

        to_delete_ids = list(to_delete_qs.values_list('pk', flat=True))
        total_organisms = Organism.objects.count()
        kept = total_organisms - len(to_delete_ids)

        if not to_delete_ids:
            self.stdout.write(self.style.SUCCESS('Aucun organisme à supprimer.'))
            return

        if not options['no_input']:
            msg = (
                f'Supprimer {len(to_delete_ids)} organismes (sans hydroquebec) et garder {kept} ? (oui/non): '
            )
            if input(msg).strip().lower() != 'oui':
                self.stdout.write(self.style.WARNING('Annulé.'))
                return

        counts = {}

        self.stdout.write('Détachement photo_principale…')
        Organism.objects.filter(pk__in=to_delete_ids).update(photo_principale=None)

        self.stdout.write('Suppression photos de référence…')
        counts['photos'] = OrganismPhoto.objects.filter(organism_id__in=to_delete_ids).delete()[0]

        cp_ids = list(Cultivar.objects.filter(organism_id__in=to_delete_ids).values_list('pk', flat=True))
        if cp_ids:
            counts['pollinators'] = CultivarPollinator.objects.filter(cultivar_id__in=cp_ids).delete()[0]
            counts['porte_greffes'] = CultivarPorteGreffe.objects.filter(cultivar_id__in=cp_ids).delete()[0]
        else:
            counts['pollinators'] = counts['porte_greffes'] = 0

        self.stdout.write('Suppression cultivars…')
        counts['cultivars'] = Cultivar.objects.filter(organism_id__in=to_delete_ids).delete()[0]

        self.stdout.write('Suppression relations…')
        counts['organism_amendments'] = OrganismAmendment.objects.filter(organisme_id__in=to_delete_ids).delete()[0]
        counts['companion_relations'] = CompanionRelation.objects.filter(
            Q(organisme_source_id__in=to_delete_ids) | Q(organisme_cible_id__in=to_delete_ids)
        ).delete()[0]
        counts['organism_propriete'] = OrganismPropriete.objects.filter(organisme_id__in=to_delete_ids).delete()[0]
        counts['organism_usage'] = OrganismUsage.objects.filter(organisme_id__in=to_delete_ids).delete()[0]
        counts['organism_calendrier'] = OrganismCalendrier.objects.filter(organisme_id__in=to_delete_ids).delete()[0]
        counts['organism_noms'] = OrganismNom.objects.filter(organism_id__in=to_delete_ids).delete()[0]

        self.stdout.write('Suppression organismes…')
        try:
            counts['organisms'] = Organism.objects.filter(pk__in=to_delete_ids).delete()[0]
        except OperationalError as e:
            if 'no such table' in str(e).lower():
                self.stdout.write(self.style.WARNING(f'  Fallback SQL brut: {e}'))
                counts['organisms'] = _delete_organisms_raw_by_ids(to_delete_ids)
            else:
                raise

        self.stdout.write(
            self.style.SUCCESS(
                f"Terminé. Supprimés : {counts.get('organisms', 0)} organismes. Conservés : {kept} espèces HQ."
            )
        )
