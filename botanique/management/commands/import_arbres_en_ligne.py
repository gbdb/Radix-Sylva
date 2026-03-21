"""
Import Arbres en ligne : CSV 3 colonnes (nom_fr, nom_latin, nom_en).
Mode create_only : crée Organism uniquement si slug_latin absent ; sinon skip.
Toujours crée/met à jour OrganismNom (FR + EN) avec source="arbres_en_ligne".
"""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.utils import timezone

from botanique.models import Organism, OrganismNom
from botanique.utils import slugify_latin as _slugify_latin
from botanique.models import DataImportRun


SOURCE = 'arbres_en_ligne'
CSV_HEADERS = ('Version francaise', 'Traduction latin', 'Traduction Anglais')


class Command(BaseCommand):
    help = "Importe les noms depuis le CSV Arbres en ligne (create_only + OrganismNom FR/EN)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            required=True,
            help='Chemin vers le CSV (colonnes: Version francaise, Traduction latin, Traduction Anglais)',
        )

    def handle(self, *args, **options):
        file_path = Path(options['file'])
        if not file_path.exists():
            self.stdout.write(self.style.ERROR(f'Fichier introuvable: {file_path}'))
            return

        run = DataImportRun.objects.create(
            source='import_arbres_en_ligne',
            status='running',
            trigger='gestion_donnees',
            stats={},
        )
        created_org = 0
        skipped_org = 0
        noms_created = 0
        noms_updated = 0

        try:
            # Résolution en mémoire : slugs existants
            existing_slugs = set(
                Organism.objects.values_list('slug_latin', flat=True).exclude(slug_latin__isnull=True)
            )
            existing_slugs.discard('')

            rows = []
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    nom_fr = (row.get(CSV_HEADERS[0]) or '').strip()
                    nom_latin = (row.get(CSV_HEADERS[1]) or '').strip()
                    nom_en = (row.get(CSV_HEADERS[2]) or '').strip()
                    if not nom_latin:
                        continue
                    slug = _slugify_latin(nom_latin)
                    if not slug:
                        continue
                    rows.append({
                        'nom_fr': nom_fr,
                        'nom_latin': nom_latin,
                        'nom_en': nom_en,
                        'slug': slug,
                    })

            organisms_to_create = []
            for r in rows:
                if r['slug'] not in existing_slugs:
                    organisms_to_create.append(Organism(
                        nom_commun=r['nom_fr'] or r['nom_latin'],
                        nom_latin=r['nom_latin'],
                        slug_latin=r['slug'],
                        type_organisme='arbre_ornement',
                        regne='plante',
                    ))
                    existing_slugs.add(r['slug'])
                    created_org += 1
                else:
                    skipped_org += 1

            if organisms_to_create:
                Organism.objects.bulk_create(organisms_to_create)

            # Mapping slug → id pour tous les organismes concernés
            all_slugs = [r['slug'] for r in rows]
            slug_to_id = dict(Organism.objects.filter(slug_latin__in=all_slugs).values_list('slug_latin', 'id'))

            # OrganismNom existants pour (organism_id, langue, source)
            organism_ids = list(slug_to_id.values())
            existing_noms = {
                (o.organism_id, o.langue): o
                for o in OrganismNom.objects.filter(organism_id__in=organism_ids, source=SOURCE)
            }

            noms_to_create = []
            noms_to_update = []
            for r in rows:
                oid = slug_to_id.get(r['slug'])
                if not oid:
                    continue
                for langue, nom in (('fr', r['nom_fr']), ('en', r['nom_en'])):
                    if not nom:
                        continue
                    key = (oid, langue)
                    if key in existing_noms:
                        obj = existing_noms[key]
                        obj.nom = nom
                        noms_to_update.append(obj)
                    else:
                        noms_to_create.append(OrganismNom(
                            organism_id=oid,
                            nom=nom,
                            langue=langue,
                            source=SOURCE,
                            principal=False,
                        ))

            if noms_to_create:
                OrganismNom.objects.bulk_create(noms_to_create)
                noms_created = len(noms_to_create)
            if noms_to_update:
                OrganismNom.objects.bulk_update(noms_to_update, ['nom'])
                noms_updated = len(noms_to_update)

            # Recalcul search_vector (bulk_create ne déclenche pas le signal)
            call_command('rebuild_search_vectors')

            run.status = 'success'
            run.finished_at = timezone.now()
            run.stats = {
                'organisms_created': created_org,
                'organisms_skipped': skipped_org,
                'noms_created': noms_created,
                'noms_updated': noms_updated,
            }
            run.save()
            self.stdout.write(self.style.SUCCESS(
                f"Créés: {created_org} organismes, {noms_created} noms ; mis à jour: {noms_updated} noms ; ignorés: {skipped_org} organismes."
            ))
        except Exception as e:
            run.status = 'failure'
            run.finished_at = timezone.now()
            run.output_snippet = str(e)[:2000]
            run.save()
            raise
