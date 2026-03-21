"""
Détecte et fusionne les doublons d'organismes (Radix Sylva — pas de spécimens / favoris BIOT).

Critères de regroupement : même nom latin normalisé (sans auteur) + même nom commun.

Usage:
  python manage.py merge_organism_duplicates --dry-run
  python manage.py merge_organism_duplicates
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from botanique.models import (
    CompanionRelation,
    Cultivar,
    Organism,
    OrganismAmendment,
    OrganismCalendrier,
    OrganismPhoto,
    OrganismPropriete,
    OrganismUsage,
)
from botanique.source_rules import latin_name_without_author, normalize_latin_name


def canonical_key(org):
    lat = (org.nom_latin or '').strip()
    commun = (org.nom_commun or '').strip().lower()
    if not lat:
        return ('nom', None, commun or None)
    base = latin_name_without_author(lat)
    norm = normalize_latin_name(base) or base.lower()
    return ('nom', norm, commun or None)


def choose_kept(group):
    def score(o):
        s = 0
        if o.vascan_id is not None:
            s += 1000
        if o.tsn is not None:
            s += 500
        s += len(o.data_sources or {}) * 10
        s += len(o.zone_rusticite or []) * 5
        if o.description:
            s += 1
        if o.famille:
            s += 1
        s += o.reference_photos.count() * 5
        return s

    return max(group, key=score)


def merge_into_kept(kept, duplicates, stdout):
    for org in duplicates:
        if org.id == kept.id:
            continue
        OrganismPhoto.objects.filter(organism=org).update(organism=kept)
        Cultivar.objects.filter(organism=org).update(organism=kept)
        OrganismPropriete.objects.filter(organisme=org).update(organisme=kept)
        OrganismUsage.objects.filter(organisme=org).update(organisme=kept)
        OrganismCalendrier.objects.filter(organisme=org).update(organisme=kept)
        OrganismAmendment.objects.filter(organisme=org).update(organisme=kept)
        for rel in CompanionRelation.objects.filter(organisme_source=org):
            if CompanionRelation.objects.filter(
                organisme_source=kept,
                organisme_cible=rel.organisme_cible,
                type_relation=rel.type_relation,
            ).exists():
                rel.delete()
            else:
                rel.organisme_source = kept
                rel.save()
        for rel in CompanionRelation.objects.filter(organisme_cible=org):
            if CompanionRelation.objects.filter(
                organisme_source=rel.organisme_source,
                organisme_cible=kept,
                type_relation=rel.type_relation,
            ).exists():
                rel.delete()
            else:
                rel.organisme_cible = kept
                rel.save()
        if not kept.photo_principale_id and org.photo_principale_id:
            kept.photo_principale = org.photo_principale
        merged_sources = dict(kept.data_sources or {})
        for k, v in (org.data_sources or {}).items():
            if k not in merged_sources:
                merged_sources[k] = v
        kept.data_sources = merged_sources
        kept_zones = list(kept.zone_rusticite or [])
        for z in org.zone_rusticite or []:
            if isinstance(z, dict) and z.get('zone'):
                src = z.get('source', '')
                if not any(isinstance(x, dict) and x.get('source') == src for x in kept_zones):
                    kept_zones.append(z)
        kept.zone_rusticite = kept_zones
        if (not kept.nom_latin or len(kept.nom_latin) < len(org.nom_latin or '')) and org.nom_latin:
            kept.nom_latin = org.nom_latin
        if (not kept.nom_commun or len(kept.nom_commun) < len(org.nom_commun or '')) and org.nom_commun:
            kept.nom_commun = org.nom_commun
        if org.vascan_id and not kept.vascan_id:
            kept.vascan_id = org.vascan_id
        if org.tsn and not kept.tsn:
            kept.tsn = org.tsn
        kept.save()
        stdout.write(f'    Fusionné id={org.id} ({org.nom_commun}) → id={kept.id}')
        org.delete()


class Command(BaseCommand):
    help = 'Détecte et fusionne les doublons d’organismes (Radix Sylva).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Sans modification')
        parser.add_argument('--no-input', action='store_true', help='Sans confirmation')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        no_input = options['no_input']

        groups = defaultdict(list)
        for org in Organism.objects.all().order_by('id'):
            key = canonical_key(org)
            if key[0] == 'nom' and (key[1] is None or (isinstance(key[1], str) and not key[1].strip())):
                continue
            groups[key].append(org)

        duplicates_groups = [(k, v) for k, v in groups.items() if len(v) > 1]
        if not duplicates_groups:
            self.stdout.write(self.style.SUCCESS('Aucun doublon détecté.'))
            return

        self.stdout.write(
            self.style.WARNING(
                f'{len(duplicates_groups)} groupe(s) de doublons '
                f'({sum(len(g) - 1 for _, g in duplicates_groups)} fusions possibles).'
            )
        )
        for key, group in duplicates_groups:
            kept = choose_kept(group)
            others = [o for o in group if o.id != kept.id]
            self.stdout.write(f'\n  Clé {key}: garde id={kept.id} « {kept.nom_commun} » ({kept.nom_latin})')
            for o in others:
                self.stdout.write(f'    → fusionner id={o.id} « {o.nom_commun} » ({o.nom_latin})')

        if dry_run:
            self.stdout.write(self.style.WARNING('\nMode dry-run : aucune modification.'))
            return

        if not no_input:
            if input('\nFusionner ces doublons ? (oui/non): ').strip().lower() != 'oui':
                self.stdout.write('Annulé.')
                return

        with transaction.atomic():
            merged_count = 0
            for key, group in duplicates_groups:
                kept = choose_kept(group)
                others = [o for o in group if o.id != kept.id]
                merge_into_kept(kept, [kept] + others, self.stdout)
                merged_count += len(others)

        self.stdout.write(self.style.SUCCESS(f'\nTerminé : {merged_count} organisme(s) fusionné(s).'))
        try:
            from botanique.enrichment_score import update_enrichment_scores

            res = update_enrichment_scores()
            self.stdout.write(self.style.SUCCESS(f"  Enrichissement: note globale {res['global_score_pct']}%"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  Recalcul enrichissement: {e}'))
