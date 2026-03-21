"""
Import Plants For A Future (PFAF) — complément à Hydro-Québec.

Licence : la base PFAF est désormais payante (Standard Home 50 USD, Commercial 150 USD,
Student 30 USD pour ~7400 plantes). N'utiliser que des fichiers acquis légalement via pfaf.org.

Formats supportés (détection par extension) :
  - JSON  : liste d'objets (clés en anglais ou français, avec ou sans espaces)
  - CSV   : délimiteur auto (virgule, point-virgule, tab), en-têtes normalisés
  - SQLite: table plant_data (ou --table=...)

Utilise species.pfaf_mapping pour unifier les noms de champs (Latin Name, latin_name,
nom_latin, etc.). Par défaut --merge=fill_gaps pour préserver Hydro-Québec.
Données brutes stockées dans Organism.data_sources['pfaf'].
"""
from pathlib import Path

from django.core.management.base import BaseCommand
from botanique.models import Cultivar, Organism
from botanique.pfaf_mapping import (
    PFAF_FIELD_ALIASES,
    get_available_columns,
    get_row_value,
    load_pfaf_data,
)
from botanique.source_rules import (
    MERGE_FILL_GAPS,
    MERGE_OVERWRITE,
    SOURCE_PFAF,
    apply_fill_gaps,
    ensure_organism_genus,
    find_organism_and_cultivar,
    find_or_match_organism,
    get_unique_slug_latin,
    merge_zones_rusticite,
    parse_cultivar_from_latin,
)


class Command(BaseCommand):
    help = (
        'Importe des plantes depuis un fichier PFAF (JSON, CSV ou SQLite). '
        'Base PFAF payante (50–150 USD) — n\'utiliser que des fichiers acquis via pfaf.org. '
        'Par défaut merge=fill_gaps pour préserver les données Hydro-Québec.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default=None,
            help='Fichier à importer: .json, .csv ou .sqlite/.db',
        )
        parser.add_argument(
            '--db',
            type=str,
            default=None,
            help='Alias pour --file (même chose). Base SQLite pfaf-data possible.',
        )
        parser.add_argument(
            '--table',
            type=str,
            default='plant_data',
            help='Nom de la table SQLite (défaut: plant_data).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Nombre max à importer (0 = tout).',
        )
        parser.add_argument(
            '--merge',
            type=str,
            choices=[MERGE_OVERWRITE, MERGE_FILL_GAPS],
            default=MERGE_FILL_GAPS,
            help=f'{MERGE_OVERWRITE}: écraser. {MERGE_FILL_GAPS}: ne remplir que les vides (défaut).',
        )

    def handle(self, *args, **options):
        file_path = options.get('file') or options.get('db')
        if not file_path:
            self.stdout.write(
                self.style.ERROR('❌ Indiquez --file=chemin ou --db=chemin (ex: --file=pfaf.json)')
            )
            return

        limit = options['limit']
        merge_mode = options['merge']
        path = Path(file_path)

        try:
            data = load_pfaf_data(path, db_table=options['table'])
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'❌ Fichier introuvable: {path}'))
            return
        except ValueError as e:
            self.stdout.write(self.style.ERROR(f'❌ {e}'))
            return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Erreur de chargement: {e}'))
            return

        if not data:
            self.stdout.write(self.style.WARNING('⚠️ Aucune donnée trouvée dans le fichier.'))
            return

        if limit > 0:
            data = data[:limit]

        self.stdout.write(self.style.SUCCESS(
            f'🌿 Import PFAF (merge={merge_mode}, {len(data)} entrées)'
        ))

        # Validation: vérifier les colonnes disponibles et critiques
        validation_passed = True
        if data:
            available_cols = get_available_columns(data)
            self.stdout.write(f'\n🔍 Colonnes disponibles dans le fichier ({len(available_cols)}):')
            self.stdout.write(f'   {", ".join(available_cols[:20])}{"..." if len(available_cols) > 20 else ""}')
            
            # Vérifier si les colonnes critiques sont trouvées
            first_row = data[0]
            nom_latin_found = get_row_value(first_row, PFAF_FIELD_ALIASES['latin_name'], default=None)
            nom_commun_found = get_row_value(first_row, PFAF_FIELD_ALIASES['common_name'], default=None)
            
            self.stdout.write(f'\n🔍 Test sur la première ligne:')
            if nom_latin_found:
                self.stdout.write(self.style.SUCCESS(f'   ✓ nom_latin trouvé: "{nom_latin_found}"'))
            else:
                self.stdout.write(self.style.WARNING(
                    f'   ✗ nom_latin non trouvé (colonnes testées: {", ".join(PFAF_FIELD_ALIASES["latin_name"][:5])}...)'
                ))
            if nom_commun_found:
                self.stdout.write(self.style.SUCCESS(f'   ✓ nom_commun trouvé: "{nom_commun_found}"'))
            else:
                self.stdout.write(self.style.WARNING(
                    f'   ✗ nom_commun non trouvé (colonnes testées: {", ".join(PFAF_FIELD_ALIASES["common_name"][:5])}...)'
                ))
            
            if not nom_latin_found and not nom_commun_found:
                validation_passed = False
                self.stdout.write(self.style.ERROR(
                    '\n⚠️ ATTENTION: ni nom_latin ni nom_commun trouvés dans la première ligne!'
                ))
                self.stdout.write(self.style.WARNING(
                    '   Les enregistrements seront ignorés si cette condition persiste.'
                ))
                # Suggérer des colonnes similaires
                similar_latin = [c for c in available_cols if 'latin' in c or 'scientific' in c or 'species' in c or 'binomial' in c]
                similar_common = [c for c in available_cols if 'common' in c or 'name' in c or 'vernacular' in c or 'english' in c]
                if similar_latin:
                    self.stdout.write(self.style.WARNING(
                        f'   Colonnes similaires à "latin_name": {", ".join(similar_latin)}'
                    ))
                if similar_common:
                    self.stdout.write(self.style.WARNING(
                        f'   Colonnes similaires à "common_name": {", ".join(similar_common)}'
                    ))
        
        # Demander confirmation si validation échoue
        if not validation_passed:
            self.stdout.write(self.style.WARNING(
                '\n⚠️ La validation a détecté des problèmes. L\'import continuera mais beaucoup d\'enregistrements pourraient être ignorés.'
            ))

        created = 0
        updated = 0
        skipped = 0
        skipped_empty_names = 0
        skipped_errors = 0

        for idx, row in enumerate(data, 1):
            try:
                nom_latin = get_row_value(row, PFAF_FIELD_ALIASES['latin_name'], default='')
                nom_commun = get_row_value(row, PFAF_FIELD_ALIASES['common_name'], default='')
                
                # Si ni nom_latin ni nom_commun, on ne peut pas importer
                if not nom_latin and not nom_commun:
                    skipped += 1
                    skipped_empty_names += 1
                    # Afficher les détails seulement pour les premières lignes ignorées
                    if skipped_empty_names <= 3:
                        available_cols = list(row.keys())
                        self.stdout.write(
                            self.style.WARNING(
                                f'  ⚠️ Ignoré ligne {idx}: nom_latin et nom_commun vides\n'
                                f'     Colonnes disponibles: {", ".join(available_cols[:10])}{"..." if len(available_cols) > 10 else ""}'
                            )
                        )
                    continue

                famille = get_row_value(row, PFAF_FIELD_ALIASES['family'], default='')
                description = self._description_from_row(row)
                zone_raw = self._zone_from_row(row)
                besoin_soleil = self._sun_from_row(row)
                besoin_eau = self._water_from_row(row)
                hauteur_raw = get_row_value(row, PFAF_FIELD_ALIASES['height'], default=None, coerce_str=False)
                hauteur_max = None
                if hauteur_raw is not None:
                    try:
                        if isinstance(hauteur_raw, str):
                            hauteur_raw = hauteur_raw.replace(',', '.')
                        hauteur_max = float(hauteur_raw)
                    except (TypeError, ValueError):
                        pass

                # Détecter cultivar dans le nom latin : si oui, rattacher à l'espèce + Cultivar
                base_latin, nom_cultivar = parse_cultivar_from_latin(nom_latin or '')
                defaults_common = {
                    'nom_commun': nom_commun or nom_latin,
                    'famille': famille,
                    'regne': 'plante',
                    'type_organisme': self._type_from_row(row),
                    'besoin_soleil': besoin_soleil,
                    'besoin_eau': besoin_eau,
                    'hauteur_max': hauteur_max,
                    'description': description,
                    'parties_comestibles': get_row_value(
                        row, PFAF_FIELD_ALIASES['edible_parts'], default=''
                    ),
                    'usages_autres': get_row_value(
                        row, PFAF_FIELD_ALIASES['uses'], default=''
                    ),
                    'toxicite': get_row_value(
                        row, PFAF_FIELD_ALIASES['toxicite'], default=''
                    ),
                }
                if nom_cultivar and base_latin:
                    defaults_common['slug_latin'] = get_unique_slug_latin(Organism, base_latin)
                    organism, _cultivar, est_nouveau = find_organism_and_cultivar(
                        Organism,
                        Cultivar,
                        nom_latin=nom_latin or '',
                        nom_commun=nom_commun or nom_latin or '',
                        defaults_organism=defaults_common,
                        defaults_cultivar={},
                    )
                else:
                    organism, est_nouveau = find_or_match_organism(
                        Organism,
                        nom_latin=nom_latin or '',
                        nom_commun=nom_commun or nom_latin,
                        defaults=defaults_common,
                    )
                
                ensure_organism_genus(organism)
                
                # Gérer fixateur_azote
                fixateur = get_row_value(
                    row, PFAF_FIELD_ALIASES['fixateur_azote'], default=''
                ).lower()
                if fixateur and ('y' in fixateur or 'yes' in fixateur or 'oui' in fixateur or '1' in fixateur):
                    if not organism.fixateur_azote:
                        organism.fixateur_azote = True
                
                # Gérer les zones de rusticité (format JSONField avec source)
                current_zones = list(organism.zone_rusticite or [])
                if zone_raw:
                    updated_zones = merge_zones_rusticite(
                        current_zones,
                        zone_raw,
                        SOURCE_PFAF
                    )
                else:
                    updated_zones = current_zones
                
                # Préparer les mises à jour selon le mode de merge
                update_fields = {}
                
                if merge_mode == MERGE_FILL_GAPS:
                    # Ne mettre à jour que les champs vides
                    current = {k: getattr(organism, k, None) for k in [
                        'famille', 'besoin_eau', 'besoin_soleil', 'hauteur_max',
                        'description', 'parties_comestibles', 'usages_autres', 'toxicite'
                    ]}
                    defaults_to_apply = {
                        'famille': famille,
                        'besoin_soleil': besoin_soleil,
                        'besoin_eau': besoin_eau,
                        'hauteur_max': hauteur_max,
                        'description': description,
                        'parties_comestibles': get_row_value(
                            row, PFAF_FIELD_ALIASES['edible_parts'], default=''
                        ),
                        'usages_autres': get_row_value(
                            row, PFAF_FIELD_ALIASES['uses'], default=''
                        ),
                        'toxicite': get_row_value(
                            row, PFAF_FIELD_ALIASES['toxicite'], default=''
                        ),
                    }
                    filtered = apply_fill_gaps(current, defaults_to_apply)
                    update_fields.update(filtered)
                else:
                    # Mode overwrite: mettre à jour tous les champs
                    update_fields.update({
                        'famille': famille,
                        'besoin_soleil': besoin_soleil,
                        'besoin_eau': besoin_eau,
                        'hauteur_max': hauteur_max,
                        'description': description,
                        'parties_comestibles': get_row_value(
                            row, PFAF_FIELD_ALIASES['edible_parts'], default=''
                        ),
                        'usages_autres': get_row_value(
                            row, PFAF_FIELD_ALIASES['uses'], default=''
                        ),
                        'toxicite': get_row_value(
                            row, PFAF_FIELD_ALIASES['toxicite'], default=''
                        ),
                    })
                
                # Toujours mettre à jour les zones (merge intelligent)
                update_fields['zone_rusticite'] = updated_zones
                
                # Fusionner data_sources
                pfaf_payload = self._serializable_payload(row)
                existing_sources = dict(organism.data_sources or {})
                existing_sources[SOURCE_PFAF] = pfaf_payload
                update_fields['data_sources'] = existing_sources
                
                # Appliquer les mises à jour
                for key, value in update_fields.items():
                    setattr(organism, key, value)
                organism.save()
                if est_nouveau:
                    created += 1
                    self.stdout.write(f'  ✅ Créé: {nom_commun}')
                else:
                    updated += 1
                    self.stdout.write(f'  🔄 Mis à jour: {nom_commun}')
            except Exception as e:
                skipped += 1
                skipped_errors += 1
                nom_latin = get_row_value(row, PFAF_FIELD_ALIASES['latin_name'], default='?')
                # Afficher les détails seulement pour les premières erreurs
                if skipped_errors <= 5:
                    self.stdout.write(
                        self.style.WARNING(f'  ⚠️ Erreur ligne {idx}: {nom_latin} - {e}')
                    )

        self.stdout.write(self.style.SUCCESS(f'\n🎉 Import PFAF terminé.'))
        self.stdout.write(f'  ✅ Créés: {created}')
        self.stdout.write(f'  🔄 Mis à jour: {updated}')
        self.stdout.write(f'  ⚠️ Ignorés: {skipped} ({skipped_empty_names} noms vides, {skipped_errors} erreurs)')
        try:
            from botanique.enrichment_score import update_enrichment_scores
            res = update_enrichment_scores()
            self.stdout.write(self.style.SUCCESS(f'  📊 Enrichissement: note globale {res["global_score_pct"]}%'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  ⚠️ Recalcul enrichissement: {e}'))

    def _serializable_payload(self, row: dict) -> dict:
        """Construit un dict JSON-serialisable pour data_sources['pfaf']."""
        out = {}
        for k, v in row.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                out[k] = v
            else:
                out[k] = str(v)
        return out

    def _description_from_row(self, row: dict) -> str:
        parts = []
        for key in PFAF_FIELD_ALIASES['description'] + PFAF_FIELD_ALIASES['habitat']:
            v = get_row_value(row, [key], default='')
            if v:
                parts.append(v)
        return '\n\n'.join(parts) if parts else ''

    def _zone_from_row(self, row: dict) -> str:
        z = get_row_value(row, PFAF_FIELD_ALIASES['zone_rusticite'], default='', coerce_str=False)
        if z is None:
            return ''
        if isinstance(z, (int, float)):
            return str(int(z))
        return str(z).strip() if z else ''

    def _sun_from_row(self, row: dict) -> str:
        sun = get_row_value(row, PFAF_FIELD_ALIASES['sun'], default='').lower()
        if not sun:
            return ''
        if 'shade' in sun and 'sun' not in sun and 'partial' not in sun:
            return 'ombre'
        if 'partial' in sun or 'semi' in sun or 'mi-ombre' in sun or 'light shade' in sun:
            return 'mi_ombre'
        if 'full' in sun or 'sun' in sun or 'soleil' in sun or 'no shade' in sun:
            return 'plein_soleil'
        return ''

    def _water_from_row(self, row: dict) -> str:
        w = get_row_value(row, PFAF_FIELD_ALIASES['water'], default='').lower()
        if not w:
            return ''
        if 'dry' in w or 'low' in w or 'faible' in w:
            return 'faible'
        if 'wet' in w or 'high' in w or 'eleve' in w or 'moist' in w:
            return 'eleve'
        return 'moyen'

    def _type_from_row(self, row: dict) -> str:
        t = get_row_value(row, PFAF_FIELD_ALIASES['habit'], default='').lower()
        if 'tree' in t or 'arbre' in t:
            return 'arbre_ornement'
        if 'shrub' in t or 'arbuste' in t:
            return 'arbuste'
        if 'perennial' in t or 'vivace' in t:
            return 'vivace'
        if 'annual' in t or 'annuelle' in t:
            return 'annuelle'
        if 'climber' in t or 'grimpant' in t or 'vine' in t:
            return 'grimpante'
        return 'vivace'
