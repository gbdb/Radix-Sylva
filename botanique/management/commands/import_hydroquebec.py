import json
import re
import shutil
import ssl
import subprocess
import time
import warnings
from pathlib import Path

import requests
from urllib3.exceptions import InsecureRequestWarning
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from django.core.management.base import BaseCommand

try:
    import certifi
except ImportError:
    certifi = None
from botanique.models import Cultivar, Organism
from botanique.source_rules import (
    MERGE_FILL_GAPS,
    MERGE_OVERWRITE,
    SOURCE_HYDROQUEBEC,
    apply_fill_gaps,
    ensure_organism_genus,
    find_organism_and_cultivar,
    find_or_match_organism,
    get_unique_slug_latin,
    merge_zones_rusticite,
    parse_cultivar_from_latin,
)


class TLS12Adapter(HTTPAdapter):
    """Adaptateur forçant TLS 1.2+ et utilisant certifi pour les certificats."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        if certifi:
            ctx.load_verify_locations(certifi.where())
        else:
            ctx.load_default_certs()
        if hasattr(ssl, 'TLSVersion'):
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)


class Command(BaseCommand):
    help = (
        'Importe les arbres et arbustes depuis Hydro-Québec. '
        'Si l\'API bloque Python (SSL), utilisez --file avec un JSON enregistré depuis le navigateur.'
    )

    # Corrections optionnelles de noms (fautes de frappe connues dans la source HQ)
    NOM_LATIN_CORRECTIONS = {}

    def _clean_import_names(self, nom_latin: str, nom_commun: str):
        """
        Nettoie les noms issus de l'API : trim, normalisation des espaces,
        application des corrections optionnelles (NOM_LATIN_CORRECTIONS).
        """
        nom_latin = (nom_latin or '').strip()
        nom_commun = (nom_commun or '').strip()
        nom_latin = re.sub(r'\s+', ' ', nom_latin).strip()
        nom_commun = re.sub(r'\s+', ' ', nom_commun).strip()
        for wrong, right in self.NOM_LATIN_CORRECTIONS.items():
            if wrong and nom_latin:
                nom_latin = nom_latin.replace(wrong, right)
        return nom_latin, nom_commun

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Nombre max d\'arbres à importer (défaut: 50). Mettre 0 pour tout importer.'
        )
        parser.add_argument(
            '--file',
            type=str,
            default=None,
            help=(
                'Fichier JSON local. Avec --enrich-from-api: fusionne les données complètes. '
                'Préférez l\'URL partiel pour des fruits/feuilles/fleurs: '
                '.../rechercher/partiel/0/500'
            )
        )
        parser.add_argument(
            '--merge',
            type=str,
            choices=[MERGE_OVERWRITE, MERGE_FILL_GAPS],
            default=MERGE_OVERWRITE,
            help=(
                f'{MERGE_OVERWRITE}: écraser les champs (défaut). '
                f'{MERGE_FILL_GAPS}: ne remplir que les champs vides (préserve PFAF/manuel).'
            )
        )
        parser.add_argument(
            '--fetch-details',
            action='store_true',
            help=(
                'Pour les fiches où fruits/feuilles/fleurs sont vides, récupérer la fiche détail '
                'via l\'API pour compléter. Plus lent (1 requête par fiche incomplète).'
            )
        )
        parser.add_argument(
            '--enrich-from-api',
            action='store_true',
            help=(
                'Avec --file : récupérer les données complètes via l\'API partiel et fusionner. '
                'Résout les champs vides (fruits, feuilles, fleurs) présents dans le JSON "tous".'
            )
        )
        parser.add_argument(
            '--insecure',
            action='store_true',
            help=(
                'Désactiver la vérification SSL (à utiliser uniquement si erreur SSL persistante). '
                'Préférez d\'abord: pip install --upgrade certifi'
            )
        )
        parser.add_argument(
            '--curl',
            action='store_true',
            help=(
                'Utiliser curl au lieu de Python pour récupérer les données (contourne les erreurs SSL). '
                'Recommandé si l\'API échoue avec SSLV3_ALERT_HANDSHAKE_FAILURE.'
            )
        )
        parser.add_argument(
            '--output',
            type=str,
            default=None,
            metavar='FICHIER',
            help=(
                'Sauvegarder le JSON récupéré dans ce fichier sans importer en base. '
                'Exemple: --limit 0 --output arbres_hq.json puis --file arbres_hq.json pour importer.'
            )
        )

    def handle(self, *args, **options):
        limit = options['limit']
        file_path = options.get('file')
        output_path = options.get('output')
        # Téléchargement complet : avec --output et sans --file, forcer limit=0 (tout récupérer)
        if output_path and not file_path and limit != 0:
            limit = 0
            self.stdout.write(self.style.NOTICE('--output sans --file : limite ignorée (téléchargement complet).'))
        merge_mode = options.get('merge', MERGE_OVERWRITE)
        fetch_details = options.get('fetch_details', False)
        enrich_from_api = options.get('enrich_from_api', False)
        
        insecure = options.get('insecure', False)
        use_curl = options.get('curl', False)
        if insecure:
            self.stdout.write(self.style.WARNING('⚠️ Mode --insecure : vérification SSL désactivée'))
            warnings.filterwarnings('ignore', category=InsecureRequestWarning)

        if limit == 0:
            self.stdout.write(self.style.SUCCESS('🌳 Début de l\'import Hydro-Québec (tout)...'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'🌳 Début de l\'import Hydro-Québec (max {limit} arbres)...'
            ))
        
        # Charger les données : fichier local ou API
        if file_path:
            arbres = self._charger_fichier(file_path)
            # Enrichir avec l'API partiel si demandé (données complètes vs "tous" qui a des nulls)
            if arbres and enrich_from_api:
                arbres = self._enrich_from_partiel(arbres, insecure=insecure)
        else:
            if use_curl:
                arbres = self._charger_api_via_curl(limit)
            else:
                arbres = self._charger_api(limit, insecure=insecure)
            if arbres is None:
                return  # Erreur déjà affichée
        
        if not arbres:
            self.stdout.write(self.style.WARNING('Aucun arbre à importer.'))
            return
        
        # Limiter le nombre (0 = tout importer)
        if limit > 0:
            arbres = arbres[:limit]
        self.stdout.write(self.style.SUCCESS(f'✅ {len(arbres)} arbres à traiter.'))

        # Mode téléchargement seul : sauvegarder le JSON et quitter sans importer
        output_path = options.get('output')
        if output_path:
            out = Path(output_path).resolve()
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
                with open(out, 'w', encoding='utf-8') as f:
                    json.dump(arbres, f, ensure_ascii=False, indent=2)
                self.stdout.write(self.style.SUCCESS(
                    f'✅ {len(arbres)} espèces sauvegardées dans {out}. '
                    f'Pour importer plus tard : python manage.py import_hydroquebec --file {out}'
                ))
            except OSError as e:
                self.stdout.write(self.style.ERROR(f'❌ Impossible d\'écrire {out}: {e}'))
            return

        session = None
        if fetch_details:
            session = requests.Session()
            if not insecure:
                session.mount('https://', TLS12Adapter())
            session.headers.update({
                'User-Agent': (
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'application/json',
            })

        created = 0
        updated = 0
        skipped = 0

        for arbre in arbres:
            try:
                # Lire et nettoyer les noms (trim, espaces, corrections optionnelles)
                nom_latin, nom_francais = self._clean_import_names(
                    arbre.get('nomLatin') or '',
                    arbre.get('nomFrancais') or '',
                )

                if not nom_latin or not nom_francais:
                    skipped += 1
                    continue

                # Compléter avec la fiche détail si champs descriptifs manquants
                numero_fiche = arbre.get('numeroFiche')
                if fetch_details and numero_fiche and self._manque_donnees_descriptives(arbre):
                    detail = self._fetch_fiche_detail(session, numero_fiche, insecure=insecure)
                    if detail:
                        arbre = self._fusionner_fiche_detail(arbre, detail)
                        if detail.get('fruitsDescription'):
                            self.stdout.write(f'     📥 Fiche {numero_fiche}: fruits récupérés')

                formes = arbre.get('formes', [])
                fruits_description = arbre.get('fruitsDescription') or ''
                nom_latin_raw = arbre.get('nomLatin') or ''
                type_organisme = self._determiner_type(formes, fruits_description, nom_latin_raw)

                # L'API peut renvoyer null: on force listes/chaînes vides pour éviter NOT NULL en base
                famille = arbre.get('famille') or ''
                zone_rusticite_raw = arbre.get('zoneRusticite') or ''
                description = self._creer_description(arbre) or ''
                sol_textures = arbre.get('solTextures') if arbre.get('solTextures') is not None else []
                sol_ph = arbre.get('solPhs') if arbre.get('solPhs') is not None else []
                toxicite = self._extraire_toxicite_fruits(arbre.get('fruitsDescription'))
                parties_comestibles = self._deriver_parties_comestibles(
                    arbre.get('fruitsDescription'), toxicite
                )
                hq_payload = {
                    'numeroFiche': arbre.get('numeroFiche'),
                    'plantationDistanceMinimum': arbre.get('plantationDistanceMinimum'),
                    'remarques': arbre.get('remarquesFicheDeBase') or '',
                    'usages': arbre.get('usages') or '',
                    'maladies': arbre.get('maladies') or '',
                    'insectes': arbre.get('insectes') or '',
                    'feuillesDescription': arbre.get('feuillesDescription') or '',
                    'fleursDescription': arbre.get('fleursDescription') or '',
                    'fruitsDescription': arbre.get('fruitsDescription') or '',
                }
                usages_hq = arbre.get('usages') or ''

                # Détecter cultivar dans le nom latin : si oui, rattacher à l'espèce + Cultivar
                base_latin, nom_cultivar = parse_cultivar_from_latin(nom_latin)
                if nom_cultivar and base_latin:
                    slug_latin_espece = get_unique_slug_latin(Organism, base_latin)
                    defaults_organism = {
                        'nom_commun': nom_francais,
                        'famille': famille,
                        'regne': 'plante',
                        'type_organisme': type_organisme,
                        'slug_latin': slug_latin_espece,
                        'besoin_eau': self._convertir_humidite(
                            arbre.get('solHumidites') or []
                        ),
                        'besoin_soleil': self._convertir_exposition(
                            arbre.get('expositionsLumiere') or []
                        ),
                        'sol_textures': sol_textures,
                        'sol_ph': sol_ph,
                        'hauteur_max': arbre.get('hauteur'),
                        'largeur_max': arbre.get('largeur'),
                        'vitesse_croissance': self._convertir_croissance(
                            arbre.get('croissance') or ''
                        ),
                        'description': description,
                    }
                    if usages_hq:
                        defaults_organism['usages_autres'] = usages_hq
                    if toxicite:
                        defaults_organism['toxicite'] = toxicite
                    if parties_comestibles:
                        defaults_organism['parties_comestibles'] = parties_comestibles
                    cultivar_notes = (arbre.get('remarquesFicheDeBase') or '').strip()
                    if arbre.get('fruitsDescription') and cultivar_notes:
                        cultivar_notes = (arbre.get('fruitsDescription') or '')[:500] + '\n\n' + cultivar_notes
                    elif arbre.get('fruitsDescription'):
                        cultivar_notes = (arbre.get('fruitsDescription') or '')[:500]
                    defaults_cultivar = {}
                    if cultivar_notes:
                        defaults_cultivar['description'] = cultivar_notes[: 2000]
                    organism, _cultivar, est_nouveau = find_organism_and_cultivar(
                        Organism,
                        Cultivar,
                        nom_latin=nom_latin,
                        nom_commun=nom_francais,
                        defaults_organism=defaults_organism,
                        defaults_cultivar=defaults_cultivar,
                    )
                else:
                    slug_latin_unique = get_unique_slug_latin(Organism, nom_latin)
                    defaults = {
                        'nom_commun': nom_francais,
                        'famille': famille,
                        'regne': 'plante',
                        'type_organisme': type_organisme,
                        'slug_latin': slug_latin_unique,
                        'besoin_eau': self._convertir_humidite(
                            arbre.get('solHumidites') or []
                        ),
                        'besoin_soleil': self._convertir_exposition(
                            arbre.get('expositionsLumiere') or []
                        ),
                        'sol_textures': sol_textures,
                        'sol_ph': sol_ph,
                        'hauteur_max': arbre.get('hauteur'),
                        'largeur_max': arbre.get('largeur'),
                        'vitesse_croissance': self._convertir_croissance(
                            arbre.get('croissance') or ''
                        ),
                        'description': description,
                    }
                    if usages_hq:
                        defaults['usages_autres'] = usages_hq
                    if toxicite:
                        defaults['toxicite'] = toxicite
                    if parties_comestibles:
                        defaults['parties_comestibles'] = parties_comestibles
                    organism, est_nouveau = find_or_match_organism(
                        Organism,
                        nom_latin=nom_latin,
                        nom_commun=nom_francais,
                        defaults=defaults
                    )
                
                ensure_organism_genus(organism)
                
                # Gérer les zones de rusticité (format JSONField avec source)
                current_zones = list(organism.zone_rusticite or [])
                if zone_rusticite_raw:
                    updated_zones = merge_zones_rusticite(
                        current_zones,
                        zone_rusticite_raw,
                        SOURCE_HYDROQUEBEC
                    )
                else:
                    updated_zones = current_zones
                
                # Préparer les mises à jour selon le mode de merge
                update_fields = {}
                
                if merge_mode == MERGE_FILL_GAPS:
                    # Ne mettre à jour que les champs vides
                    current = {k: getattr(organism, k, None) for k in [
                        'type_organisme', 'famille', 'besoin_eau', 'besoin_soleil', 'sol_textures',
                        'sol_ph', 'hauteur_max', 'largeur_max', 'vitesse_croissance',
                        'description', 'toxicite', 'parties_comestibles', 'usages_autres'
                    ]}
                    defaults_to_apply = {
                        'type_organisme': type_organisme,
                        'famille': famille,
                        'besoin_eau': self._convertir_humidite(arbre.get('solHumidites') or []),
                        'besoin_soleil': self._convertir_exposition(arbre.get('expositionsLumiere') or []),
                        'sol_textures': sol_textures,
                        'sol_ph': sol_ph,
                        'hauteur_max': arbre.get('hauteur'),
                        'largeur_max': arbre.get('largeur'),
                        'vitesse_croissance': self._convertir_croissance(arbre.get('croissance') or ''),
                        'description': description,
                    }
                    if usages_hq:
                        defaults_to_apply['usages_autres'] = usages_hq
                    if toxicite:
                        defaults_to_apply['toxicite'] = toxicite
                    if parties_comestibles:
                        defaults_to_apply['parties_comestibles'] = parties_comestibles
                    filtered = apply_fill_gaps(current, defaults_to_apply)
                    update_fields.update(filtered)
                else:
                    # Mode overwrite: mettre à jour tous les champs (dont type_organisme)
                    update_fields.update({
                        'type_organisme': type_organisme,
                        'famille': famille,
                        'besoin_eau': self._convertir_humidite(arbre.get('solHumidites') or []),
                        'besoin_soleil': self._convertir_exposition(arbre.get('expositionsLumiere') or []),
                        'sol_textures': sol_textures,
                        'sol_ph': sol_ph,
                        'hauteur_max': arbre.get('hauteur'),
                        'largeur_max': arbre.get('largeur'),
                        'vitesse_croissance': self._convertir_croissance(arbre.get('croissance') or ''),
                        'description': description,
                        'toxicite': toxicite or '',
                        'parties_comestibles': parties_comestibles or '',
                        'usages_autres': usages_hq or '',
                    })
                
                # Toujours mettre à jour les zones (merge intelligent)
                update_fields['zone_rusticite'] = updated_zones
                
                # Fusionner data_sources
                existing_sources = dict(organism.data_sources or {})
                existing_sources[SOURCE_HYDROQUEBEC] = hq_payload
                update_fields['data_sources'] = existing_sources
                
                # Appliquer les mises à jour
                for key, value in update_fields.items():
                    setattr(organism, key, value)
                organism.save()

                if est_nouveau:
                    created += 1
                    self.stdout.write(f'  ✅ Créé: {nom_francais}')
                else:
                    updated += 1
                    self.stdout.write(f'  🔄 Mis à jour: {nom_francais}')

            except Exception as e:
                skipped += 1
                nom_francais = arbre.get('nomFrancais', '?')
                self.stdout.write(
                    self.style.WARNING(f'  ⚠️ Erreur: {nom_francais} - {str(e)}')
                )

        self.stdout.write(self.style.SUCCESS(f'\n🎉 Import terminé!'))
        self.stdout.write(f'  ✅ Créés: {created}')
        self.stdout.write(f'  🔄 Mis à jour: {updated}')
        self.stdout.write(f'  ⚠️ Ignorés: {skipped}')
        # Recalcul des notes d'enrichissement
        try:
            from botanique.enrichment_score import update_enrichment_scores
            res = update_enrichment_scores()
            self.stdout.write(self.style.SUCCESS(f'  📊 Enrichissement: note globale {res["global_score_pct"]}%'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  ⚠️ Recalcul enrichissement: {e}'))
        # Résumé par type pour vérifier la classification
        from django.db.models import Count
        type_counts = Organism.objects.values('type_organisme').annotate(n=Count('id')).order_by('-n')
        fruit_noix = sum(t['n'] for t in type_counts if t['type_organisme'] in (
            'arbre_fruitier', 'arbuste_fruitier', 'arbuste_baies', 'arbre_noix'
        ))
        if fruit_noix > 0:
            self.stdout.write(self.style.SUCCESS(f'\n📊 Espèces fruitières/noix: {fruit_noix}'))

    def _enrich_from_partiel(self, arbres, insecure=False):
        """
        Fusionne les données de l'API partiel (complètes) dans arbres chargé depuis --file.
        Construit un lookup par numeroFiche puis remplit les champs vides.
        """
        lookup = {}
        try:
            session = requests.Session()
            if not insecure:
                session.mount('https://', TLS12Adapter())
            session.headers.update({
                'User-Agent': (
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'application/json',
            })
            verify = not insecure
            chunk_size = 500
            index = 0
            while True:
                url = f'https://arbres.hydroquebec.com/public/api/v1.0.0/arbres/fr/rechercher/partiel/{index}/{chunk_size}'
                response = session.get(url, timeout=120, verify=verify)
                response.raise_for_status()
                chunk = response.json()
                if not chunk:
                    break
                for a in chunk:
                    nf = a.get('numeroFiche')
                    if nf:
                        lookup[str(nf)] = a
                index += len(chunk)
        except Exception:
            self.stdout.write(self.style.WARNING('⚠️ Enrichissement API échoué, utilisation du fichier seul.'))
            return arbres

        merged_count = 0
        # Index par espèce de base (ex. "Cotoneaster dammeri") pour héritage cultivar → espèce
        species_lookup = {}
        for nf, a in lookup.items():
            if a.get('feuillesDescription') or a.get('fruitsDescription'):
                lat = (a.get('nomLatin') or '')
                base = lat.split("'")[0].split('(')[0].strip()
                if base and base not in species_lookup:
                    species_lookup[base] = a

        for arbre in arbres:
            nf = arbre.get('numeroFiche')
            full = lookup.get(str(nf)) if nf else None
            if not full:
                # Fallback : hériter d'un cultivar de la même espèce (ex. dammeri ← Coral Beauty)
                lat = (arbre.get('nomLatin') or '')
                base = lat.split("'")[0].split('(')[0].strip()
                full = species_lookup.get(base)
            if not full:
                continue
            for key in ('feuillesDescription', 'fleursDescription', 'fruitsDescription'):
                if not arbre.get(key) and full.get(key):
                    arbre[key] = full[key]
                    merged_count += 1
            # Autres champs utiles
            for key in ('famille', 'hauteur', 'largeur', 'croissance', 'solTextures', 'solPhs',
                       'expositionsLumiere', 'solHumidites', 'formes', 'usages'):
                if not arbre.get(key) and full.get(key):
                    arbre[key] = full[key]

        if merged_count:
            self.stdout.write(self.style.SUCCESS(f'✅ Enrichi {merged_count} champs depuis l\'API partiel.'))
        return arbres

    def _charger_fichier(self, file_path):
        """Charge la liste d'arbres depuis un fichier JSON (enregistré depuis le navigateur)."""
        path = Path(file_path)
        if not path.exists():
            self.stdout.write(self.style.ERROR(f'❌ Fichier introuvable: {path}'))
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            self.stdout.write(self.style.ERROR(f'❌ Fichier JSON invalide: {e}'))
            return []
        if not isinstance(data, list):
            self.stdout.write(self.style.ERROR('❌ Le JSON doit être une liste d\'objets (arbres).'))
            return []
        return data

    # Pause entre chaque bloc API (évite "Connection reset by peer")
    _CURL_DELAY_BETWEEN_CHUNKS = 2.5

    def _charger_api(self, limit, insecure=False):
        """
        Charge les arbres depuis l'API partiel (données complètes).
        Pause automatique entre les blocs.
        """
        try:
            self.stdout.write('📡 Connexion à l\'API Hydro-Québec (partiel)...')
            session = requests.Session()
            if not insecure:
                session.mount('https://', TLS12Adapter())
            session.headers.update({
                'User-Agent': (
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'application/json',
            })
            verify = not insecure
            arbres = []
            chunk_size = 500
            index = 0
            first_chunk = True
            while True:
                if not first_chunk:
                    time.sleep(self._CURL_DELAY_BETWEEN_CHUNKS)
                first_chunk = False
                url = f'https://arbres.hydroquebec.com/public/api/v1.0.0/arbres/fr/rechercher/partiel/{index}/{chunk_size}'
                response = session.get(url, timeout=120, verify=verify)
                response.raise_for_status()
                chunk = response.json()
                if not chunk:
                    break
                arbres.extend(chunk)
                if limit > 0 and len(arbres) >= limit:
                    arbres = arbres[:limit]
                    break
                index += len(chunk)
            return arbres
        except requests.exceptions.SSLError as e:
            self.stdout.write(self.style.ERROR(
                f'❌ Erreur SSL: {e}\n'
                '   Solutions:\n'
                '   1. python manage.py import_hydroquebec --curl --limit 50  (recommandé)\n'
                '   2. python manage.py import_hydroquebec --insecure --limit 50\n'
                '   3. --file=arbres.json (enregistrez depuis le navigateur)\n'
                '      URL: https://arbres.hydroquebec.com/public/api/v1.0.0/arbres/fr/rechercher/partiel/0/500'
            ))
            return None
        except requests.exceptions.RequestException as e:
            if arbres:
                self.stdout.write(self.style.WARNING(
                    f'⚠️ Connexion interrompue après {len(arbres)} espèces. Ces espèces seront importées.'
                ))
                return arbres
            self.stdout.write(self.style.ERROR(
                f'❌ Erreur de connexion à l\'API: {e}\n'
                '   Solutions : --curl --limit 500 ou --file=arbres.json'
            ))
            return None

    def _charger_api_via_curl(self, limit):
        """
        Charge les arbres via curl. Pagination par blocs de 500.
        Pause automatique entre les blocs pour limiter les coupures de connexion.
        """
        if not shutil.which('curl'):
            self.stdout.write(self.style.ERROR(
                '❌ curl introuvable. Installez curl ou utilisez --file=arbres.json'
            ))
            return None
        try:
            self.stdout.write('📡 Connexion à l\'API Hydro-Québec via curl (1700+ espèces attendues)...')
            arbres = []
            chunk_size = 500
            index = 0
            first_chunk = True
            while True:
                if not first_chunk:
                    time.sleep(self._CURL_DELAY_BETWEEN_CHUNKS)
                first_chunk = False
                url = f'https://arbres.hydroquebec.com/public/api/v1.0.0/arbres/fr/rechercher/partiel/{index}/{chunk_size}'
                result = subprocess.run(
                    ['curl', '-sS', '-L', '-H', 'Accept: application/json', url],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    err = (result.stderr or result.stdout or '').strip()
                    if arbres:
                        self.stdout.write(self.style.WARNING(
                            f'⚠️ Connexion interrompue après {len(arbres)} espèces.\n'
                            f'   Détail: {err}\n'
                            f'   Les {len(arbres)} espèces déjà récupérées seront importées. '
                            f'Pour tout récupérer : relancez l\'import, utilisez une limite de 500, '
                            f'ou --file avec un JSON téléchargé depuis le navigateur.'
                        ))
                        return arbres
                    self.stdout.write(self.style.ERROR(
                        f'❌ Connexion à l\'API Hydro-Québec impossible.\n'
                        f'   Détail: {err}\n'
                        f'   Causes possibles : réseau instable, pare-feu, ou serveur surchargé.\n'
                        f'   Solutions : utilisez « Avec limite » 500 dans Paramètres, '
                        f'ou téléchargez le JSON (URL partiel/0/500) et --file=arbres.json'
                    ))
                    return None
                raw = (result.stdout or '').strip()
                if not raw:
                    break
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    if arbres:
                        self.stdout.write(self.style.WARNING(
                            f'⚠️ Réponse invalide après le bloc {index}. Les {len(arbres)} espèces déjà récupérées seront importées.'
                        ))
                        return arbres
                    self.stdout.write(self.style.ERROR('❌ Réponse serveur invalide (pas du JSON).'))
                    return None
                if not chunk:
                    break
                arbres.extend(chunk)
                self.stdout.write(f'   📥 Bloc {index}-{index + len(chunk)}: {len(chunk)} espèces (total: {len(arbres)})')
                if limit > 0 and len(arbres) >= limit:
                    arbres = arbres[:limit]
                    break
                index += len(chunk)
            self.stdout.write(self.style.SUCCESS(f'   ✅ {len(arbres)} espèces récupérées depuis l\'API'))
            return arbres
        except subprocess.TimeoutExpired:
            if arbres:
                self.stdout.write(self.style.WARNING(
                    f'⚠️ Délai dépassé après {len(arbres)} espèces. Ces espèces seront tout de même importées.'
                ))
                return arbres
            self.stdout.write(self.style.ERROR(
                '❌ Délai de connexion dépassé (timeout). Réessayez ou utilisez une limite de 500.'
            ))
            return None
        except json.JSONDecodeError as e:
            self.stdout.write(self.style.ERROR(f'❌ Réponse JSON invalide: {e}'))
            return None

    def _determiner_type(self, formes, fruits_description='', nom_latin=''):
        """
        Détermine le type d'organisme selon les formes, fruitsDescription et le genre (nom latin).
        Détecte arbre_fruitier, arbuste_fruitier, arbuste_baies, arbre_noix.
        """
        fd = (fruits_description or '').lower()
        nl = (nom_latin or '').lower()

        # Termes comestibles (exclure toxiques)
        not_toxic = 'toxique' not in fd and 'potentiellement toxique' not in fd
        has_fruits_comestibles = not_toxic and (
            'baie' in fd or 'fruit' in fd or 'drupe' in fd
            or 'pomme' in fd or 'poire' in fd or 'cerise' in fd or 'prune' in fd
            or 'pêche' in fd or 'abricot' in fd
            or ('comestible' in fd and ('baie' in fd or 'fruit' in fd))
        )
        has_noix = not_toxic and (
            'noix' in fd or 'noisette' in fd or 'châtaigne' in fd or 'amande' in fd
            or 'caryer' in fd or 'pignon' in fd or 'pécan' in fd
        )

        # Fallback par genre (Malus, Pyrus, Prunus, Vaccinium, Juglans, Corylus, etc.)
        if not has_fruits_comestibles and not has_noix:
            if any(g in nl for g in ('malus', 'pyrus', 'prunus', 'vaccinium', 'ribes', 'sambucus')):
                has_fruits_comestibles = True
            if any(g in nl for g in ('juglans', 'corylus', 'carya', 'castanea')):
                has_noix = True

        forme_str = ' '.join(f if isinstance(f, str) else '' for f in (formes or [])).lower()
        # "Shrub" peut apparaître en anglais dans certaines fiches
        if 'shrub' in forme_str and 'arbuste' not in forme_str:
            forme_str += ' arbuste'

        if not formes or not forme_str.strip():
            # Pas de forme : utiliser fruits/noix + genre pour deviner arbre vs arbuste
            if has_noix:
                return 'arbre_noix'
            if has_fruits_comestibles:
                # Malus, Pyrus, Prunus = arbres ; Vaccinium, Ribes, Sambucus = arbustes
                if any(g in nl for g in ('malus', 'pyrus', 'prunus')):
                    return 'arbre_fruitier'
                return 'arbuste_baies'
            return 'arbre_ornement'

        if 'grand arbre' in forme_str or 'moyen arbre' in forme_str:
            if has_noix:
                return 'arbre_noix'
            return 'arbre_fruitier' if has_fruits_comestibles else 'arbre_ornement'
        elif 'petit arbre' in forme_str or 'arbrisseau' in forme_str:
            if has_noix:
                return 'arbre_noix'
            return 'arbuste_fruitier' if has_fruits_comestibles else 'arbuste'
        elif 'arbuste' in forme_str:
            if has_noix:
                return 'arbre_noix'
            return 'arbuste_baies' if has_fruits_comestibles else 'arbuste'
        elif 'grimpant' in forme_str:
            return 'grimpante'
        else:
            if has_noix:
                return 'arbre_noix'
            return 'arbre_fruitier' if has_fruits_comestibles else 'arbre_ornement'
    
    def _convertir_humidite(self, humidites):
        """Convertit les humidités HQ en besoin eau"""
        if not humidites:
            return 'moyen'
        
        humidite_str = ' '.join(humidites).lower()
        
        if 'élevée' in humidite_str or 'humide' in humidite_str:
            return 'eleve'
        elif 'faible' in humidite_str or 'sec' in humidite_str:
            return 'faible'
        else:
            return 'moyen'
    
    def _convertir_exposition(self, expositions):
        """Convertit les expositions HQ en besoin soleil"""
        if not expositions:
            return 'plein_soleil'
        
        expo_str = ' '.join(expositions).lower()
        
        if 'soleil' in expo_str:
            return 'plein_soleil'
        elif 'mi-ombre' in expo_str:
            return 'mi_ombre'
        elif 'ombre' in expo_str:
            return 'ombre'
        else:
            return 'plein_soleil'
    
    def _convertir_croissance(self, croissance):
        """Convertit la vitesse de croissance"""
        if not croissance:
            return ''
        
        croissance = croissance.lower()
        
        if 'lente' in croissance:
            return 'lente'
        elif 'rapide' in croissance:
            return 'rapide'
        elif 'moyenne' in croissance:
            return 'moyenne'
        else:
            return ''
    
    def _manque_donnees_descriptives(self, arbre):
        """Vérifie si la fiche manque de données descriptives (fruits, feuilles, fleurs)."""
        return not (
            arbre.get('fruitsDescription')
            and arbre.get('feuillesDescription')
            and arbre.get('fleursDescription')
        )

    def _fetch_fiche_detail(self, session, numero_fiche, insecure=False):
        """Récupère la fiche détail via l'API (/rechercher/arbre/{id}). Retourne None en cas d'erreur."""
        if not session or not numero_fiche:
            return None
        # Doc officielle: https://donnees.hydroquebec.com/explore/dataset/repertoire-arbres/
        url = f'https://arbres.hydroquebec.com/public/api/v1.0.0/arbres/fr/rechercher/arbre/{numero_fiche}'
        try:
            response = session.get(url, timeout=15, verify=not insecure)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    def _fusionner_fiche_detail(self, arbre, detail):
        """Fusionne les données de la fiche détail dans arbre (ne remplit que les champs vides)."""
        merged = dict(arbre)
        for key in ('feuillesDescription', 'fleursDescription', 'fruitsDescription'):
            if not merged.get(key) and detail.get(key):
                merged[key] = detail[key]
        return merged

    def _deriver_parties_comestibles(self, fruits_description, toxicite):
        """
        Dérive parties_comestibles à partir de fruitsDescription.
        Pour les fruits toxiques : indique leur présence tout en renvoyant vers toxicité.
        """
        if not fruits_description or not isinstance(fruits_description, str):
            return ''
        fd = fruits_description.lower()
        if 'baie' in fd or 'fruit' in fd or 'drupe' in fd or 'cône' in fd:
            if toxicite:
                return 'Fruits (baies) — non comestibles, toxiques. Voir toxicité.'
            return 'Fruits (baies)'
        return ''

    def _extraire_toxicite_fruits(self, fruits_description):
        """Extrait une notice de toxicité si fruitsDescription mentionne des fruits toxiques."""
        if not fruits_description or not isinstance(fruits_description, str):
            return ''
        fd = fruits_description.lower()
        if 'toxique' in fd or 'potentiellement toxique' in fd:
            # Extraire la phrase pertinente (ex. "baies potentiellement toxiques")
            parts = []
            for seg in fruits_description.split('\n\n'):
                seg = seg.strip()
                if seg and ('toxique' in seg.lower() or 'potentiellement' in seg.lower()):
                    parts.append(seg)
            return ' '.join(parts) if parts else ''
        return ''

    def _creer_description(self, arbre):
        """Crée une description à partir des données HQ"""
        parts = []
        
        if arbre.get('feuillesDescription'):
            parts.append(f"Feuilles: {arbre['feuillesDescription']}")
        
        if arbre.get('fleursDescription'):
            parts.append(f"Fleurs: {arbre['fleursDescription']}")
        
        if arbre.get('fruitsDescription'):
            parts.append(f"Fruits: {arbre['fruitsDescription']}")
        
        if arbre.get('remarquesFicheComplete'):
            parts.append(f"Remarques: {arbre['remarquesFicheComplete']}")
        
        return '\n\n'.join(parts)