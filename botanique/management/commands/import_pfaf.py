"""
Import Plants For A Future (PFAF) — CSV officiel (latin-1, ~40 colonnes).

Licence : base PFAF payante — n'utiliser que des fichiers acquis légalement via pfaf.org.

Lit le CSV avec pandas, enrichit Organism (champs vides), crée ou met à jour OrganismPFAF.
Ordre par ligne (strict) : organism.save() → ensure_organism_genus(organism) → OrganismPFAF.

Mode --dry-run : aucune persistance (transaction annulée en fin de commande).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from django.db import transaction
from django.core.management.base import BaseCommand
from django.utils import timezone

from botanique.models import Cultivar, DataImportRun, Organism, OrganismPFAF
from botanique.pfaf_mapping import get_row_value, to_snake
from botanique.source_rules import (
    apply_fill_gaps,
    ensure_organism_genus,
    find_organism_and_cultivar,
    find_or_match_organism,
    get_unique_slug_latin,
    parse_cultivar_from_latin,
)

# Shade (colonne PFAF) → besoin_soleil (choices Organism)
SHADE_MAP = {
    'S': 'plein_soleil',
    'SN': 'soleil_partiel',
    'N': 'mi_ombre',
    'FS': 'mi_ombre',
    'FSN': 'soleil_partiel',
}

# Moisture → besoin_eau
MOISTURE_MAP = {
    'D': 'tres_faible',
    'DM': 'faible',
    'M': 'moyen',
    'MWe': 'eleve',
    'We': 'eleve',
    'WeWa': 'tres_eleve',
    'Wa': 'tres_eleve',
}

# Habit (valeur brute) → type_organisme (choices Organism)
HABIT_MAP = {
    'Tree': 'arbre_ornement',
    'Shrub': 'arbuste',
    'Perennial': 'vivace',
    'Annual': 'annuelle',
    'Biennial': 'bisannuelle',
    'Annual/Biennial': 'bisannuelle',
    'Biennial/Perennial': 'vivace',
    'Annual/Perennial': 'vivace',
    'Bulb': 'vivace',
    'Corm': 'vivace',
    'Climber': 'grimpante',
    'Perennial Climber': 'grimpante',
    'Annual Climber': 'grimpante',
    'Bamboo': 'vivace',
    'Fern': 'vivace',
}


def _norm_key_row(series: pd.Series, columns: list[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for c in columns:
        k = to_snake(str(c))
        v = series.get(c)
        if v is None or (isinstance(v, float) and (math.isnan(v) or pd.isna(v))):
            out[k] = ''
        elif pd.isna(v):
            out[k] = ''
        else:
            out[k] = v
    return out


def _parse_float(val: Any) -> Optional[float]:
    if val is None or val == '':
        return None
    if isinstance(val, (int, float)):
        if isinstance(val, float) and (math.isnan(val) or pd.isna(val)):
            return None
        return float(val)
    s = str(val).strip().replace(',', '.')
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int_rating(val: Any) -> Optional[int]:
    f = _parse_float(val)
    if f is None:
        return None
    i = int(round(f))
    if i < 0:
        return 0
    if i > 5:
        return 5
    return i


def _parse_uk_hardiness(val: Any) -> Optional[int]:
    f = _parse_float(val)
    if f is None:
        return None
    i = int(round(f))
    if i < 1:
        return 1
    if i > 10:
        return 10
    return i


def _parse_bool_na(val: Any) -> Optional[bool]:
    if val is None or val == '':
        return None
    if isinstance(val, float) and (math.isnan(val) or pd.isna(val)):
        return None
    s = str(val).strip().lower()
    if s in ('', 'nan', 'none'):
        return None
    if s in ('true', 't', 'yes', 'y', '1'):
        return True
    if s in ('false', 'f', 'no', 'n', '0'):
        return False
    return None


def _parse_nitrogen_fixer(val: Any) -> Optional[bool]:
    if val is None or val == '':
        return None
    s = str(val).strip().lower()
    if s in ('true', 't', 'yes', 'y', '1'):
        return True
    if s in ('false', 'f', 'no', 'n', '0'):
        return False
    if 'y' in s or 'yes' in s or 'oui' in s:
        return True
    return None


def _shade_to_besoin_soleil(raw: str) -> str:
    s = (raw or '').strip().upper()
    if not s:
        return ''
    return SHADE_MAP.get(s, '')


def _moisture_to_besoin_eau(raw: str) -> str:
    s = (raw or '').strip()
    if not s:
        return ''
    return MOISTURE_MAP.get(s, '')


def _habit_to_type_organisme(raw: str) -> str:
    s = (raw or '').strip()
    if not s:
        return 'vivace'
    return HABIT_MAP.get(s, 'vivace')


class Command(BaseCommand):
    help = (
        'Importe le CSV PFAF (latin-1) : enrichit Organism et OrganismPFAF. '
        'Fichier hors dépôt — passer --filepath.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--filepath',
            type=str,
            required=True,
            help='Chemin absolu vers le fichier CSV PFAF',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simule sans persister (transaction annulée en fin de commande).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Traiter uniquement les N premières lignes de données (0 = tout).',
        )
        parser.add_argument(
            '--update-existing',
            action='store_true',
            help='Met à jour OrganismPFAF même si un enregistrement existe déjà.',
        )

    def handle(self, *args, **options):
        filepath = Path(options['filepath'])
        dry_run = options['dry_run']
        limit = options['limit'] or 0
        update_existing = options['update_existing']

        if not filepath.is_file():
            self.stdout.write(self.style.ERROR(f'Fichier introuvable: {filepath}'))
            return

        def _run():
            self._execute_import(filepath, dry_run, limit, update_existing)

        if dry_run:
            with transaction.atomic():
                _run()
                transaction.set_rollback(True)
        else:
            _run()

    def _execute_import(
        self,
        filepath: Path,
        dry_run: bool,
        limit: int,
        update_existing: bool,
    ) -> None:
        try:
            df = pd.read_csv(filepath, encoding='latin-1', dtype=str, keep_default_na=False)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Lecture CSV: {e}'))
            return

        df = df.fillna('')
        n_total = len(df)
        if limit > 0:
            df = df.iloc[:limit]
        n = len(df)
        cols = list(df.columns)

        run = DataImportRun.objects.create(
            source='pfaf',
            status='running',
            trigger='gestion_donnees',
            stats={'dry_run': dry_run},
        )

        stats = {
            'created': 0,
            'enriched': 0,
            'pfaf_created': 0,
            'pfaf_updated': 0,
            'skipped': 0,
            'errors': 0,
            'pfaf_skipped_existing': 0,
            'rows': n,
            'dry_run': dry_run,
        }

        self.stdout.write(
            self.style.SUCCESS(
                f'Import PFAF — {n} ligne(s) sur {n_total} totales'
                + (' [DRY-RUN]' if dry_run else '')
            )
        )

        try:
            for idx in range(1, n + 1):
                if idx == 1 or idx % 500 == 0:
                    self.stdout.write(f'  … progression ligne {idx}/{n}')

                row_series = df.iloc[idx - 1]
                row = _norm_key_row(row_series, cols)

                try:
                    self._process_row(
                        row,
                        run,
                        update_existing,
                        stats,
                    )
                except Exception as e:
                    stats['errors'] += 1
                    if stats['errors'] <= 10:
                        self.stdout.write(
                            self.style.WARNING(f'  Erreur ligne {idx}: {e}')
                        )

            run.status = 'success'
            run.finished_at = timezone.now()
            run.stats = stats
            run.save()

            self.stdout.write(self.style.SUCCESS('\nTerminé.'))
            self.stdout.write(
                f"  Créés (organismes): {stats['created']}\n"
                f"  Enrichis (organismes existants): {stats['enriched']}\n"
                f"  OrganismPFAF créés: {stats['pfaf_created']}\n"
                f"  OrganismPFAF mis à jour: {stats['pfaf_updated']}\n"
                f"  OrganismPFAF ignorés (déjà présents, sans --update-existing): "
                f"{stats['pfaf_skipped_existing']}\n"
                f"  Ignorés (lignes): {stats['skipped']}\n"
                f"  Erreurs: {stats['errors']}"
            )
            if dry_run:
                self.stdout.write(self.style.WARNING('  [DRY-RUN] Aucune donnée persistée.'))

            if not dry_run:
                try:
                    from botanique.enrichment_score import update_enrichment_scores
                    res = update_enrichment_scores()
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Enrichissement: note globale {res['global_score_pct']}%"
                        )
                    )
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'  Recalcul enrichissement: {e}'))

        except Exception as e:
            run.status = 'failure'
            run.finished_at = timezone.now()
            run.output_snippet = str(e)[:2000]
            run.save()
            raise

    def _process_row(
        self,
        row: Dict[str, Any],
        line_no: int,
        run: DataImportRun,
        update_existing: bool,
        stats: Dict[str, Any],
    ) -> None:
        nom_latin = get_row_value(
            row,
            [
                'latin_name',
                'latinname',
                'scientific_name',
                'species',
            ],
            default='',
        )
        nom_commun = get_row_value(
            row,
            [
                'common_name',
                'commonname',
                'english_name',
            ],
            default='',
        )

        if not str(nom_latin).strip():
            stats['skipped'] += 1
            return

        nom_latin = str(nom_latin).strip()
        nom_commun = str(nom_commun).strip() if nom_commun else ''

        famille = get_row_value(row, ['family', 'famille'], default='') or ''
        shade_raw = get_row_value(row, ['shade', 'sun'], default='') or ''
        moisture_raw = get_row_value(row, ['moisture', 'water'], default='') or ''
        habit_raw = get_row_value(row, ['habit', 'growth_form', 'type'], default='') or ''

        besoin_soleil = _shade_to_besoin_soleil(str(shade_raw))
        besoin_eau = _moisture_to_besoin_eau(str(moisture_raw))
        type_organisme = _habit_to_type_organisme(str(habit_raw))

        hauteur_max = _parse_float(
            get_row_value(row, ['height', 'hauteur', 'height_m'], default=None, coerce_str=False)
        )
        largeur_max = _parse_float(
            get_row_value(row, ['width', 'largeur', 'spread', 'width_m'], default=None, coerce_str=False)
        )

        nitrogen_raw = get_row_value(
            row, ['nitrogen_fixer', 'nitrogenfixer', 'fixateur_azote'], default=''
        )
        fixateur_pfaf = _parse_nitrogen_fixer(nitrogen_raw)

        defaults_common: Dict[str, Any] = {
            'nom_commun': nom_commun or nom_latin,
            'regne': 'plante',
            'type_organisme': type_organisme,
        }
        if famille:
            defaults_common['famille'] = famille
        if besoin_soleil:
            defaults_common['besoin_soleil'] = besoin_soleil
        if besoin_eau:
            defaults_common['besoin_eau'] = besoin_eau
        if hauteur_max is not None:
            defaults_common['hauteur_max'] = hauteur_max
        if largeur_max is not None:
            defaults_common['largeur_max'] = largeur_max

        base_latin, nom_cultivar = parse_cultivar_from_latin(nom_latin)
        if nom_cultivar and base_latin:
            defaults_common['slug_latin'] = get_unique_slug_latin(Organism, base_latin)
            organism, _cultivar, was_created = find_organism_and_cultivar(
                Organism,
                Cultivar,
                nom_latin=nom_latin,
                nom_commun=nom_commun or nom_latin,
                defaults_organism=defaults_common,
                defaults_cultivar={},
            )
        else:
            organism, was_created = find_or_match_organism(
                Organism,
                nom_latin=nom_latin,
                nom_commun=nom_commun or nom_latin,
                defaults=defaults_common,
                create_missing=True,
            )

        if was_created:
            stats['created'] += 1
        else:
            before = {
                'famille': organism.famille,
                'hauteur_max': organism.hauteur_max,
                'largeur_max': organism.largeur_max,
                'besoin_soleil': organism.besoin_soleil,
                'besoin_eau': organism.besoin_eau,
                'type_organisme': organism.type_organisme,
            }
            proposed: Dict[str, Any] = {}
            if famille:
                proposed['famille'] = famille
            if besoin_soleil:
                proposed['besoin_soleil'] = besoin_soleil
            if besoin_eau:
                proposed['besoin_eau'] = besoin_eau
            if hauteur_max is not None:
                proposed['hauteur_max'] = hauteur_max
            if largeur_max is not None:
                proposed['largeur_max'] = largeur_max
            if type_organisme:
                proposed['type_organisme'] = type_organisme
            filled = apply_fill_gaps(before, proposed)
            for key, val in filled.items():
                setattr(organism, key, val)

            enriched = bool(filled)
            if fixateur_pfaf is True and not organism.fixateur_azote:
                organism.fixateur_azote = True
                enriched = True
            if enriched:
                stats['enriched'] += 1

        if was_created and fixateur_pfaf is True and not organism.fixateur_azote:
            organism.fixateur_azote = True

        organism.save()
        ensure_organism_genus(organism)

        edibility_rating = _parse_int_rating(
            get_row_value(row, ['edibilityrating', 'edibility_rating'], default=None, coerce_str=False)
        )
        medicinal_rating = _parse_int_rating(
            get_row_value(row, ['medicinalrating', 'medicinal_rating'], default=None, coerce_str=False)
        )
        edible_uses = get_row_value(row, ['edible_uses', 'edibleuses'], default='') or ''
        known_hazards = get_row_value(row, ['known_hazards', 'knownhazards'], default='') or ''
        cultivation_details = get_row_value(
            row, ['cultivation_details', 'cultivationdetails'], default=''
        ) or ''
        propagation = get_row_value(row, ['propagation'], default='') or ''
        uk_hardiness = _parse_uk_hardiness(
            get_row_value(row, ['uk_hardiness', 'ukhardiness', 'hardiness'], default=None, coerce_str=False)
        )
        pollinators = get_row_value(row, ['pollinators'], default='') or ''
        self_fertile = _parse_bool_na(
            get_row_value(row, ['self_fertile', 'selffertile', 'self-fertile'], default='')
        )
        scented = _parse_bool_na(get_row_value(row, ['scented'], default=''))

        pfaf_defaults = {
            'edibility_rating': edibility_rating,
            'medicinal_rating': medicinal_rating,
            'edible_uses': edible_uses,
            'known_hazards': known_hazards,
            'cultivation_details': cultivation_details,
            'propagation': propagation,
            'uk_hardiness': uk_hardiness,
            'habit': str(habit_raw)[:50] if habit_raw else '',
            'pollinators': str(pollinators)[:200] if pollinators else '',
            'self_fertile': self_fertile,
            'scented': scented,
            'import_run': run,
        }

        pfaf_obj = OrganismPFAF.objects.filter(organism=organism).first()
        if pfaf_obj is not None:
            if update_existing:
                for key, val in pfaf_defaults.items():
                    setattr(pfaf_obj, key, val)
                pfaf_obj.save()
                stats['pfaf_updated'] += 1
            else:
                stats['pfaf_skipped_existing'] += 1
        else:
            OrganismPFAF.objects.create(organism=organism, **pfaf_defaults)
            stats['pfaf_created'] += 1
