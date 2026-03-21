"""
Import Pépinière ancestrale : CSV 1 colonne "TypePlante Cultivar [PorteGreffe] [Age]".
Mode cultivar_only : ne crée jamais d'Organism ; utilise ancestrale_mapping pour résoudre TypePlante → Organism.
Crée/met à jour Cultivar et CultivarPorteGreffe ; disponible_chez = liste, append idempotent.
"""
import csv
import logging
import re
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from botanique.models import Cultivar, CultivarPorteGreffe, DataImportRun, Organism
from botanique.utils import slugify_latin as _slugify_latin
from botanique.ancestrale_mapping import TYPE_PLANTE_TO_NOM_LATIN
from botanique.source_rules import get_unique_slug_cultivar

logger = logging.getLogger(__name__)

SOURCE = 'ancestrale'
# Porte-greffe reconnus (ordre pour regex)
PORTEGREFFE_PATTERN = re.compile(
    r'\b(B118|B9|MM106|MM111|M26|M7|M9|M27|Standard|Semi-nain|Nain)\b',
    re.IGNORECASE
)
AGE_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*ans?\b', re.IGNORECASE)
# Lignes à ignorer (non-plantes)
SKIP_STARTS = ('Porte-greffe', 'PROTECTEUR', 'Livre', 'Sécateur')
BLEUETIER_NAIN_CULTIVAR = 'Bleuetier'  # "Bleuetier Nain" → Nain fait partie du cultivar


def strip_leading_quote(line: str) -> str:
    s = line.strip()
    if s.startswith('"') or s.startswith('«'):
        s = s[1:].strip()
    return s


def parse_line(line: str):
    """
    Retourne (type_plante, cultivar_name, porte_greffe, age_str) ou None si ligne à ignorer.
    """
    s = strip_leading_quote(line)
    if not s:
        return None
    for skip in SKIP_STARTS:
        if s.startswith(skip):
            return None
    parts = s.split()
    if not parts:
        return None
    type_plante = parts[0]
    if type_plante not in TYPE_PLANTE_TO_NOM_LATIN:
        return None
    rest = ' '.join(parts[1:])
    if not rest:
        return (type_plante, '', None, None)

    age_str = None
    m = AGE_PATTERN.search(rest)
    if m:
        age_str = m.group(1)
        rest = AGE_PATTERN.sub('', rest).strip().strip('-,')

    porte_greffe = None
    m = PORTEGREFFE_PATTERN.search(rest)
    if m:
        token = m.group(1)
        # Cas spécial : Bleuetier Nain → Nain est le cultivar, pas le porte-greffe
        if type_plante == BLEUETIER_NAIN_CULTIVAR and token.lower() == 'nain':
            pass  # ne pas extraire
        else:
            porte_greffe = token
            rest = PORTEGREFFE_PATTERN.sub('', rest).strip().strip('-,')

    cultivar_name = ' '.join(rest.split()) if rest else ''
    return (type_plante, cultivar_name, porte_greffe, age_str)


class Command(BaseCommand):
    help = "Importe cultivars et porte-greffes depuis le CSV Pépinière ancestrale."

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            required=True,
            help='Chemin vers le CSV (1 colonne par ligne: TypePlante Cultivar [PorteGreffe] [Age])',
        )

    def handle(self, *args, **options):
        file_path = Path(options['file'])
        if not file_path.exists():
            self.stdout.write(self.style.ERROR(f'Fichier introuvable: {file_path}'))
            return

        run = DataImportRun.objects.create(
            source='import_ancestrale',
            status='running',
            trigger='gestion_donnees',
            stats={},
        )
        cultivars_created = 0
        cultivars_skipped = 0
        porte_greffes_created = 0
        porte_greffes_updated = 0
        warnings_count = 0

        try:
            # Résolution en mémoire : slug_latin → Organism
            nom_latin_to_organism = {}
            for nom_latin in TYPE_PLANTE_TO_NOM_LATIN.values():
                slug = _slugify_latin(nom_latin)
                if slug:
                    org = Organism.objects.filter(slug_latin=slug).first()
                    if org:
                        nom_latin_to_organism[nom_latin] = org
                    # else: type plante sans organisme en base → warning plus bas

            # (organism_id, nom_cultivar) → Cultivar
            existing_cultivars = {}
            for c in Cultivar.objects.select_related('organism').all():
                existing_cultivars[(c.organism_id, c.nom)] = c

            # (cultivar_id, nom_porte_greffe) → CultivarPorteGreffe
            existing_pg = {}
            for pg in CultivarPorteGreffe.objects.select_related('cultivar').all():
                existing_pg[(pg.cultivar_id, pg.nom_porte_greffe)] = pg

            cultivars_to_create = []
            seen_cultivar_key = set()
            pg_to_create = []
            pg_to_update = []

            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    parsed = parse_line(line)
                    if parsed is None:
                        continue
                    type_plante, cultivar_name, porte_greffe, age_str = parsed
                    nom_latin = TYPE_PLANTE_TO_NOM_LATIN.get(type_plante)
                    organism = nom_latin_to_organism.get(nom_latin) if nom_latin else None
                    if not organism:
                        logger.warning("TypePlante %s (→ %s) sans Organism en base, ligne ignorée.", type_plante, nom_latin)
                        warnings_count += 1
                        continue
                    if not cultivar_name:
                        cultivar_name = type_plante  # fallback

                    key_c = (organism.id, cultivar_name)
                    if key_c in seen_cultivar_key:
                        cultivar = existing_cultivars.get(key_c)
                    else:
                        cultivar = existing_cultivars.get(key_c)
                        if not cultivar:
                            slug_c = get_unique_slug_cultivar(Cultivar, organism, cultivar_name)
                            cultivar = Cultivar(organism=organism, slug_cultivar=slug_c, nom=cultivar_name)
                            cultivars_to_create.append(cultivar)
                            existing_cultivars[key_c] = cultivar
                            cultivars_created += 1
                        seen_cultivar_key.add(key_c)

                    if porte_greffe or age_str:
                        if cultivars_to_create and cultivar in cultivars_to_create:
                            pass  # on attachera le PG après bulk_create quand on aura les ids
                        else:
                            cid = cultivar.pk
                            if not cid:
                                continue
                            key_pg = (cid, porte_greffe or '')
                            if key_pg in existing_pg:
                                pg_obj = existing_pg[key_pg]
                                entry = {"source": SOURCE, "age": age_str or ''}
                                if isinstance(pg_obj.disponible_chez, list) and entry not in pg_obj.disponible_chez:
                                    pg_obj.disponible_chez = list(pg_obj.disponible_chez) + [entry]
                                    pg_to_update.append(pg_obj)
                                    porte_greffes_updated += 1
                            else:
                                entry = {"source": SOURCE, "age": age_str or ''}
                                new_pg = CultivarPorteGreffe(
                                    cultivar=cultivar,
                                    nom_porte_greffe=porte_greffe or 'Standard',
                                    source=SOURCE,
                                    disponible_chez=[entry],
                                )
                                pg_to_create.append(new_pg)
                                existing_pg[key_pg] = new_pg
                                porte_greffes_created += 1

            if cultivars_to_create:
                Cultivar.objects.bulk_create(cultivars_to_create)
                for c in cultivars_to_create:
                    if c.pk:
                        existing_cultivars[(c.organism_id, c.nom)] = c
                for cultivar, pg_name, age_str in pending_pg:
                    if not cultivar.pk:
                        continue
                    key_pg = (cultivar.pk, pg_name)
                    entry = {"source": SOURCE, "age": age_str}
                    if key_pg in existing_pg:
                        pg_obj = existing_pg[key_pg]
                        if isinstance(pg_obj.disponible_chez, list) and entry not in pg_obj.disponible_chez:
                            pg_obj.disponible_chez = list(pg_obj.disponible_chez) + [entry]
                            pg_to_update.append(pg_obj)
                            porte_greffes_updated += 1
                    else:
                        new_pg = CultivarPorteGreffe(
                            cultivar=cultivar,
                            nom_porte_greffe=pg_name,
                            source=SOURCE,
                            disponible_chez=[entry],
                        )
                        pg_to_create.append(new_pg)
                        existing_pg[key_pg] = new_pg
                        porte_greffes_created += 1

            if pg_to_create:
                CultivarPorteGreffe.objects.bulk_create(pg_to_create)
            if pg_to_update:
                CultivarPorteGreffe.objects.bulk_update(pg_to_update, ['disponible_chez'])

            run.status = 'success'
            run.finished_at = timezone.now()
            run.stats = {
                'cultivars_created': cultivars_created,
                'cultivars_skipped': cultivars_skipped,
                'porte_greffes_created': porte_greffes_created,
                'porte_greffes_updated': porte_greffes_updated,
                'warnings': warnings_count,
            }
            run.save()
            self.stdout.write(self.style.SUCCESS(
                f"Cultivars créés: {cultivars_created} ; porte-greffes créés: {porte_greffes_created}, mis à jour: {porte_greffes_updated}. Warnings: {warnings_count}."
            ))
        except Exception as e:
            run.status = 'failure'
            run.finished_at = timezone.now()
            run.output_snippet = str(e)[:2000]
            run.save()
            raise