"""Utilitaires partagés (slug latin) pour éviter les imports circulaires."""
import unicodedata

from django.utils.text import slugify


def slugify_latin(name: str) -> str:
    """Slug ASCII à partir d'un nom latin (accents normalisés)."""
    if not name or not isinstance(name, str):
        return ''
    n = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return slugify(n or name, allow_unicode=False) or ''
