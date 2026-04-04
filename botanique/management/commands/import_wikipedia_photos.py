"""
Import métadonnées photo depuis l’API REST Wikipedia (page/summary) par nom_latin.
Ne télécharge pas les fichiers : source_url = URL directe de l’image ; champ image laissé vide.
"""
from __future__ import annotations

import re
import time
from urllib.parse import quote

import requests
from django.core.management.base import BaseCommand
from django.utils import timezone

from botanique.models import DataImportRun, Organism, OrganismPhoto

USER_AGENT = 'RadixSylva/1.0 (radix.jardinbiot.ca; botanical database)'
REQUEST_DELAY_SEC = 0.5
SUMMARY_TIMEOUT = 5

SOURCE_AUTHOR = 'Wikipedia contributors'
SOURCE_LICENSE = 'CC BY-SA 3.0'
TYPE_REFERENCE = 'reference'


def wiki_lang_order(primary: str) -> list[str]:
    p = (primary or 'en').strip().lower()
    if p == 'en':
        return ['en', 'fr']
    if p == 'fr':
        return ['fr', 'en']
    return [p]


def latin_to_wiki_title(nom_latin: str) -> str:
    return nom_latin.strip().replace(' ', '_')


def strip_botanical_author(nom_latin: str) -> str:
    s = nom_latin.strip()
    s = re.sub(r'\s+[A-Z][a-z0-9.\-()]*(?:\s+[a-z.\-()]+)*\s*$', '', s)
    return s.strip()


def title_variants(nom_latin: str) -> list[str]:
    if not nom_latin or not nom_latin.strip():
        return []
    full = latin_to_wiki_title(nom_latin)
    stripped = latin_to_wiki_title(strip_botanical_author(nom_latin))
    if not stripped:
        return [full] if full else []
    if stripped == full:
        return [full]
    return [full, stripped]


def parse_summary_payload(data: dict) -> tuple[str, str, str] | None:
    """Retourne (image_url, titre_wiki, article_url) ou None."""
    if not isinstance(data, dict):
        return None
    if data.get('type') == 'disambiguation':
        return None
    orig = data.get('originalimage') or {}
    thumb = data.get('thumbnail') or {}
    image_url = orig.get('source') or thumb.get('source')
    if not image_url:
        return None
    titre = (data.get('title') or '').strip()
    content_urls = data.get('content_urls') or {}
    desktop = (content_urls.get('desktop') or {})
    article_url = (desktop.get('page') or '').strip()
    return image_url, titre, article_url


class Command(BaseCommand):
    help = (
        'Enrichit OrganismPhoto depuis Wikipedia REST (summary) : URL d’image et métadonnées, '
        'sans téléchargement de fichier.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simuler sans écrire en base.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Traiter au plus N organismes (0 = tous).',
        )
        parser.add_argument(
            '--overwrite',
            action='store_true',
            help='Inclure les organismes qui ont déjà une photo_principale et la remplacer.',
        )
        parser.add_argument(
            '--lang',
            type=str,
            default='en',
            help='Langue Wikipedia primaire (défaut: en). Fallback: fr si en, en si fr.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']
        overwrite = options['overwrite']
        primary_lang = options['lang']

        if overwrite:
            qs = Organism.objects.all().order_by('id')
        else:
            qs = Organism.objects.filter(photo_principale__isnull=True).order_by('id')
        if limit > 0:
            qs = qs[:limit]

        organisms = list(qs)
        n = len(organisms)
        langs = wiki_lang_order(primary_lang)

        stats = {
            'created': 0,
            'principale_set': 0,
            'skipped': 0,
            'skipped_no_latin': 0,
            'skipped_has_principale': 0,
            'skipped_no_wikipedia_image': 0,
            'errors': 0,
            'fallback_mediawiki': 0,
            'dry_run': dry_run,
            'limit': limit,
            'overwrite': overwrite,
            'lang': primary_lang,
        }
        verbosity = int(options.get('verbosity', 1))
        debug_skip = verbosity >= 2

        run = DataImportRun.objects.create(
            source='wikipedia',
            status='running',
            trigger='gestion_donnees',
            stats=dict(stats),
        )

        session = requests.Session()
        session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': 'application/json',
        })

        self.stdout.write(
            self.style.SUCCESS(
                f'Import Wikipedia photos — {n} organisme(s)'
                + (' [DRY-RUN]' if dry_run else '')
            )
        )

        try:
            for idx, organism in enumerate(organisms, start=1):
                if idx == 1 or idx % 100 == 0:
                    self.stdout.write(f'  … progression {idx}/{n}')

                nom_latin = (organism.nom_latin or '').strip()
                if not nom_latin:
                    stats['skipped'] += 1
                    stats['skipped_no_latin'] += 1
                    if debug_skip:
                        self.stdout.write(
                            f'  [skip] id={organism.pk} raison=nom_latin_vide '
                            f'photo_principale_id={repr(organism.photo_principale_id)} overwrite={overwrite}'
                        )
                    continue

                # Sans --overwrite : défense en profondeur si une photo principale existe encore (anormal
                # car le queryset filtre photo_principale__isnull=True, sauf si queryset modifié ailleurs).
                if (not overwrite) and (organism.photo_principale_id is not None):
                    stats['skipped'] += 1
                    stats['skipped_has_principale'] += 1
                    if debug_skip:
                        self.stdout.write(
                            f'  [skip] id={organism.pk} raison=photo_principale_deja_definie '
                            f'photo_principale_id={organism.photo_principale_id}'
                        )
                    continue

                resolved = self._resolve_image_for_organism(
                    session, nom_latin, langs, stats
                )
                if not resolved:
                    stats['skipped'] += 1
                    stats['skipped_no_wikipedia_image'] += 1
                    if debug_skip:
                        self.stdout.write(
                            f'  [skip] id={organism.pk} raison=pas_d_image_wikipedia '
                            f'nom_latin={nom_latin!r} photo_principale_id={repr(organism.photo_principale_id)}'
                        )
                    continue

                image_url, titre_wiki, article_url = resolved
                titre = titre_wiki[:200] if titre_wiki else ''
                source_url = image_url[:200] if image_url else ''
                source_author = SOURCE_AUTHOR[:200] if SOURCE_AUTHOR else ''
                desc_parts = []
                if article_url:
                    desc_parts.append(f'Article: {article_url}')
                description = '\n'.join(desc_parts)

                if dry_run:
                    stats['created'] += 1
                    stats['principale_set'] += 1
                    continue

                photo = OrganismPhoto.objects.create(
                    organism=organism,
                    type_photo=TYPE_REFERENCE,
                    titre=titre,
                    description=description,
                    source_url=source_url,
                    source_author=source_author,
                    source_license=SOURCE_LICENSE,
                )
                stats['created'] += 1

                organism.photo_principale = photo
                organism.save(update_fields=['photo_principale'])
                stats['principale_set'] += 1

            run.status = 'success'
            run.finished_at = timezone.now()
            run.stats = stats
            run.save()

            self.stdout.write(self.style.SUCCESS('\nTerminé.'))
            self.stdout.write(
                f"  OrganismPhoto créés: {stats['created']}\n"
                f"  photo_principale assignée: {stats['principale_set']}\n"
                f"  Ignorés (total): {stats['skipped']}\n"
                f"    — sans nom latin: {stats['skipped_no_latin']}\n"
                f"    — déjà photo_principale (anormal si queryset filtré): {stats['skipped_has_principale']}\n"
                f"    — pas d’image Wikipedia: {stats['skipped_no_wikipedia_image']}\n"
                f"  Erreurs (requêtes): {stats['errors']}\n"
                f"  Fallback MediaWiki (pageimages): {stats['fallback_mediawiki']}"
            )
            if dry_run:
                self.stdout.write(self.style.WARNING('  [DRY-RUN] Aucune donnée persistée.'))

        except Exception as e:
            run.status = 'failure'
            run.finished_at = timezone.now()
            run.output_snippet = str(e)[:2000]
            run.stats = stats
            run.save()
            raise

    def _resolve_image_for_organism(
        self,
        session: requests.Session,
        nom_latin: str,
        langs: list[str],
        stats: dict,
    ) -> tuple[str, str, str] | None:
        """Retourne (image_url, titre, article_url) ou None."""
        titles = title_variants(nom_latin)
        if not titles:
            return None

        for lang in langs:
            for title in titles:
                data = self._fetch_summary(session, lang, title, stats)
                time.sleep(REQUEST_DELAY_SEC)
                if not data:
                    continue
                if data.get('type') == 'disambiguation':
                    continue
                parsed = parse_summary_payload(data)
                if parsed:
                    return parsed
                mw = self._fetch_pageimages_fallback(session, lang, title, stats)
                time.sleep(REQUEST_DELAY_SEC)
                if mw:
                    stats['fallback_mediawiki'] += 1
                    return mw
        return None

    def _fetch_summary(
        self,
        session: requests.Session,
        lang: str,
        title: str,
        stats: dict,
    ) -> dict | None:
        encoded = quote(title, safe='/')
        url = f'https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}'
        try:
            r = session.get(url, timeout=SUMMARY_TIMEOUT)
            if r.status_code != 200:
                return None
            try:
                return r.json()
            except ValueError:
                stats['errors'] += 1
                return None
        except Exception:
            stats['errors'] += 1
            return None

    def _fetch_pageimages_fallback(
        self,
        session: requests.Session,
        lang: str,
        title: str,
        stats: dict,
    ) -> tuple[str, str, str] | None:
        """MediaWiki query pageimages si le summary REST n’a pas d’image."""
        api_url = f'https://{lang}.wikipedia.org/w/api.php'
        params = {
            'action': 'query',
            'titles': title,
            'prop': 'pageimages',
            'piprop': 'original|thumbnail',
            'pithumbsize': 500,
            'format': 'json',
            'formatversion': 2,
        }
        try:
            r = session.get(api_url, params=params, timeout=SUMMARY_TIMEOUT)
            if r.status_code != 200:
                return None
            try:
                payload = r.json()
            except ValueError:
                stats['errors'] += 1
                return None
        except Exception:
            stats['errors'] += 1
            return None

        try:
            pages = payload.get('query', {}).get('pages') or []
            if not pages:
                return None
            page = pages[0]
            if page.get('missing'):
                return None
            image_url = (page.get('original') or {}).get('source') or (
                page.get('thumbnail') or {}
            ).get('source')
            if not image_url:
                return None
            titre = (page.get('title') or title).strip()
            path = quote(title, safe='/')
            article_url = f'https://{lang}.wikipedia.org/wiki/{path}'
            return image_url, titre, article_url
        except Exception:
            stats['errors'] += 1
            return None
