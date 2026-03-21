"""
Importe des photos d'espèces depuis Wikidata et Wikimedia Commons.
Télécharge et stocke localement avec attribution (source_url, source_author, source_license).

Objectifs par espèce : au moins 1 photo de feuille, fleur, fruit (si applicable), racines (si dispo).
"""
import re
import time
from pathlib import Path

import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from botanique.models import Organism, OrganismPhoto


# Mapping type_photo ↔ termes de recherche Commons (en anglais, plus de résultats)
PHOTO_TYPE_SEARCHES = [
    ('feuillage_ete', ['leaf', 'leaves', 'feuille', 'foliage']),
    ('reproduction_fleurs', ['flower', 'flowers', 'fleur', 'bloom', 'blossom']),
    ('reproduction_fruits_mur', ['fruit', 'fruits', 'fruiting']),
    ('racines', ['root', 'roots', 'racine', 'root system']),
]

WIKIDATA_API = 'https://www.wikidata.org/w/api.php'
COMMONS_API = 'https://commons.wikimedia.org/w/api.php'
USER_AGENT = 'RadixSylva/1.0 (botanical species photos; Django management command)'


def normalize_latin_for_search(nom_latin: str) -> str:
    """Extrait le nom de base (espèce) pour la recherche, sans cultivar."""
    if not nom_latin or not isinstance(nom_latin, str):
        return ''
    # Enlever les cultivars 'Dolgo', variétés 'var. x', etc.
    s = nom_latin.strip()
    s = re.sub(r"\s*['\"].*$", '', s)  # 'Dolgo', "Coral Beauty"
    s = re.sub(r'\s+var\.\s+.*$', '', s, flags=re.I)
    s = re.sub(r'\s+subsp\.\s+.*$', '', s, flags=re.I)
    return s.strip()


def wikidata_search_species(session: requests.Session, nom_latin: str) -> str | None:
    """Recherche l'entité Wikidata pour une espèce. Retourne l'ID (ex: Q16521) ou None."""
    base_name = normalize_latin_for_search(nom_latin)
    if not base_name:
        return None
    params = {
        'action': 'wbsearchentities',
        'search': base_name,
        'language': 'fr',
        'limit': 5,
        'format': 'json',
    }
    try:
        r = session.get(WIKIDATA_API, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        entities = data.get('search', [])
        for e in entities:
            eid = e.get('id')
            desc = (e.get('description') or '').lower()
            # Préférer les items "espèce" ou "taxon"
            if eid and ('espèce' in desc or 'species' in desc or 'taxon' in desc):
                return eid
            if eid:
                return eid  # fallback: premier résultat
        return entities[0]['id'] if entities else None
    except Exception:
        return None


def wikidata_get_image(session: requests.Session, entity_id: str) -> dict | None:
    """
    Récupère l'image principale (P18) d'une entité Wikidata.
    Retourne {'filename': str, 'url': str, 'author': str, 'license': str} ou None.
    """
    params = {
        'action': 'wbgetentities',
        'ids': entity_id,
        'props': 'claims',
        'format': 'json',
    }
    try:
        r = session.get(WIKIDATA_API, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        entities = data.get('entities', {})
        ent = entities.get(entity_id)
        if not ent:
            return None
        claims = ent.get('claims', {})
        p18 = claims.get('P18', [])
        if not p18:
            return None
        filename = p18[0].get('mainsnak', {}).get('datavalue', {}).get('value', '')
        if not filename:
            return None
        # Obtenir URL et métadonnées via Commons
        return commons_get_image_info(session, filename, entity_id)
    except Exception:
        return None


def commons_search_images(
    session: requests.Session,
    nom_latin: str,
    search_terms: list[str],
    limit: int = 3,
) -> list[dict]:
    """
    Recherche des images sur Commons par nom scientifique + termes.
    Retourne liste de {'filename': str, 'url': str, 'author': str, 'license': str, 'page_url': str}.
    """
    base_name = normalize_latin_for_search(nom_latin)
    if not base_name:
        return []
    results = []
    for term in search_terms[:2]:  # max 2 termes par type
        query = f'{base_name} {term}'
        params = {
            'action': 'query',
            'list': 'search',
            'srsearch': query,
            'srnamespace': 6,  # File namespace
            'srlimit': limit,
            'format': 'json',
        }
        try:
            r = session.get(COMMONS_API, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            for item in data.get('query', {}).get('search', []):
                title = item.get('title', '')
                if not title.startswith('File:'):
                    continue
                filename = title[5:]  # remove "File:"
                info = commons_get_image_info(session, filename, None)
                if info:
                    info['page_url'] = f'https://commons.wikimedia.org/wiki/{title.replace(" ", "_")}'
                    results.append(info)
                    if len(results) >= limit:
                        return results
        except Exception:
            continue
    return results


def commons_get_image_info(
    session: requests.Session,
    filename: str,
    wikidata_id: str | None,
) -> dict | None:
    """
    Récupère l'URL et les métadonnées d'une image Commons.
    filename: "Apple blossom.jpg" (sans "File:")
    """
    title = f'File:{filename}' if not filename.startswith('File:') else filename
    params = {
        'action': 'query',
        'titles': title,
        'prop': 'imageinfo',
        'iiprop': 'url|extmetadata',
        'iiurlwidth': 800,
        'format': 'json',
    }
    try:
        r = session.get(COMMONS_API, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        pages = data.get('query', {}).get('pages', {})
        page = next((p for p in pages.values() if p.get('imageinfo')), None)
        if not page or not page.get('imageinfo'):
            return None
        ii = page['imageinfo'][0]
        url = ii.get('thumburl') or ii.get('url')
        if not url:
            return None
        ext = ii.get('extmetadata', {})
        author = ''
        license_code = ''
        if ext:
            artist = ext.get('Artist', {}).get('value', '')
            if artist:
                author = re.sub(r'<[^>]+>', '', artist).strip()
            license_code = ext.get('LicenseShortName', {}).get('value', '') or ext.get('License', {}).get('value', '')
        page_url = f'https://commons.wikimedia.org/wiki/{title.replace(" ", "_")}'
        return {
            'filename': filename,
            'url': url,
            'author': author[:200] if author else 'Wikimedia Commons',
            'license': license_code[:50] if license_code else 'CC-BY-SA',
            'page_url': page_url,
        }
    except Exception:
        return None


def download_image(session: requests.Session, url: str) -> bytes | None:
    """Télécharge une image et retourne les octets."""
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def save_photo_to_organism(
    organism: Organism,
    image_bytes: bytes,
    filename: str,
    type_photo: str,
    source_url: str,
    source_author: str,
    source_license: str,
) -> OrganismPhoto | None:
    """Crée un OrganismPhoto lié à l'espèce et enregistre l'image."""
    if OrganismPhoto.objects.filter(organism=organism, type_photo=type_photo).exists():
        return None
    ext = Path(filename).suffix or '.jpg'
    if ext.lower() not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
        ext = '.jpg'
    safe_name = re.sub(r'[^\w\-.]', '_', filename)[:100] + ext
    try:
        photo = OrganismPhoto(
            organism=organism,
            type_photo=type_photo,
            titre=f'{organism.nom_commun} - {type_photo}',
            source_url=source_url,
            source_author=source_author,
            source_license=source_license,
        )
        photo.image.save(safe_name, ContentFile(image_bytes), save=True)
        return photo
    except Exception:
        return None


class Command(BaseCommand):
    help = (
        'Importe des photos d\'espèces depuis Wikidata et Wikimedia Commons. '
        'Télécharge et stocke localement avec attribution.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Nombre max d\'espèces à traiter (0 = toutes)',
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            default=True,
            help='Ignorer les espèces qui ont déjà des photos (défaut: True)',
        )
        parser.add_argument(
            '--no-skip',
            action='store_true',
            help='Traiter toutes les espèces, même celles qui ont déjà des photos',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.0,
            help='Délai en secondes entre les requêtes API (défaut: 1.0)',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        skip_existing = options['skip_existing'] and not options['no_skip']
        delay = max(0.5, options['delay'])

        session = requests.Session()
        session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': 'application/json',
        })

        qs = Organism.objects.filter(regne='plante').order_by('nom_latin')
        if skip_existing:
            # Exclure les organismes qui ont déjà au moins 3 photos (feuille, fleur, fruit)
            from django.db.models import Count
            qs = qs.annotate(photo_count=Count('reference_photos')).filter(photo_count__lt=3)
        if limit > 0:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(self.style.SUCCESS(f'🌿 Import photos Wikimedia — {total} espèces à traiter'))

        created = 0
        skipped = 0
        errors = 0

        for organism in qs:
            nom_latin = organism.nom_latin or ''
            if not nom_latin.strip():
                skipped += 1
                continue

            time.sleep(delay)
            added = 0

            # 1. Wikidata : image principale (port_general)
            wd_id = wikidata_search_species(session, nom_latin)
            if wd_id:
                time.sleep(delay)
                img_info = wikidata_get_image(session, wd_id)
                if img_info:
                    page_url = img_info.get('page_url', f'https://www.wikidata.org/wiki/{wd_id}')
                    img_bytes = download_image(session, img_info['url'])
                    if img_bytes and not OrganismPhoto.objects.filter(organism=organism, type_photo='port_general').exists():
                        time.sleep(0.3)
                        attr = f"{img_info.get('author', 'Wikidata')} — {img_info.get('license', '')}"
                        photo = save_photo_to_organism(
                            organism, img_bytes, img_info['filename'],
                            'port_general', page_url, attr, img_info.get('license', ''),
                        )
                        if photo:
                            added += 1
                            created += 1
                            self.stdout.write(f'  📷 {organism.nom_commun}: port_general (Wikidata)')

            # 2. Commons : feuille, fleur, fruit, racines
            for type_photo, search_terms in PHOTO_TYPE_SEARCHES:
                if OrganismPhoto.objects.filter(organism=organism, type_photo=type_photo).exists():
                    continue
                time.sleep(delay)
                images = commons_search_images(session, nom_latin, search_terms, limit=1)
                if not images:
                    continue
                img_info = images[0]
                img_bytes = download_image(session, img_info['url'])
                if img_bytes:
                    time.sleep(0.3)
                    attr = f"{img_info.get('author', 'Wikimedia Commons')} — {img_info.get('license', '')}"
                    photo = save_photo_to_organism(
                        organism, img_bytes, img_info['filename'],
                        type_photo, img_info.get('page_url', ''), attr, img_info.get('license', ''),
                    )
                    if photo:
                        added += 1
                        created += 1
                        self.stdout.write(f'  📷 {organism.nom_commun}: {type_photo}')

            if added == 0 and not wd_id:
                errors += 1

        self.stdout.write(self.style.SUCCESS(f'\n✅ Import terminé: {created} photos créées, {skipped} ignorées'))
