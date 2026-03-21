"""Permissions API Radix Sylva."""
from django.conf import settings
from rest_framework.permissions import BasePermission


class HasSyncAPIKey(BasePermission):
    """
    Si RADIX_SYLVA_SYNC_API_KEYS est vide : accès libre (dev).
    Sinon : en-tête X-Radix-Sync-Key doit correspondre à une clé configurée.
    """

    message = 'Clé sync manquante ou invalide (X-Radix-Sync-Key).'

    def has_permission(self, request, view):
        keys = getattr(settings, 'RADIX_SYLVA_SYNC_API_KEYS', None) or []
        if not keys:
            return True
        provided = request.headers.get('X-Radix-Sync-Key', '')
        return provided in keys
