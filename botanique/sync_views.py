"""
Endpoints bulk read-only pour synchroniser le cache botanique Jardin bIOT.
"""
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from botanique.models import Amendment, CompanionRelation, Cultivar, Organism
from botanique.permissions import HasSyncAPIKey
from botanique.sync_payload import (
    amendment_to_sync_dict,
    companion_to_sync_dict,
    cultivar_to_sync_dict,
    organism_to_sync_dict,
)


class SyncPageNumberPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


def _parse_since_param(since_raw: str | None):
    if not since_raw:
        return None
    dt = parse_datetime(since_raw)
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


@extend_schema(
    summary='Méta sync',
    description='Horodatage serveur et version de schéma pour le filigrane client.',
    tags=['sync'],
)
class SyncMetaView(APIView):
    permission_classes = [HasSyncAPIKey]

    def get(self, request):
        return Response(
            {
                'server_time': timezone.now().isoformat(),
                'schema_version': 1,
            }
        )


def _paginated_sync(request, qs, to_dict, since_dt, date_field: str):
    if since_dt is not None:
        qs = qs.filter(**{f'{date_field}__gt': since_dt})
    paginator = SyncPageNumberPagination()
    page = paginator.paginate_queryset(qs, request)
    if page is not None:
        return paginator.get_paginated_response([to_dict(x) for x in page])
    return Response({'count': qs.count(), 'results': [to_dict(x) for x in qs]})


@extend_schema(
    summary='Sync amendements',
    parameters=[
        OpenApiParameter('since', str, description='ISO 8601 — filtre date_ajout > since'),
        OpenApiParameter('page', int),
        OpenApiParameter('page_size', int),
    ],
    tags=['sync'],
)
class SyncAmendmentsView(APIView):
    permission_classes = [HasSyncAPIKey]

    def get(self, request):
        since_dt = _parse_since_param(request.query_params.get('since'))
        qs = Amendment.objects.all().order_by('id')
        return _paginated_sync(request, qs, amendment_to_sync_dict, since_dt, 'date_ajout')


@extend_schema(
    summary='Sync organismes (avec noms, propriétés, usages, calendrier, amendements)',
    parameters=[
        OpenApiParameter('since', str, description='ISO 8601 — filtre date_modification > since'),
        OpenApiParameter(
            'organism_id',
            int,
            description='Si défini : un seul organisme (pk), ignore since — sync ciblée (ex. Jardin bIOT après organism-request).',
        ),
        OpenApiParameter('page', int),
        OpenApiParameter('page_size', int),
    ],
    tags=['sync'],
)
class SyncOrganismsView(APIView):
    permission_classes = [HasSyncAPIKey]

    def get(self, request):
        organism_id_raw = request.query_params.get('organism_id')
        base_qs = (
            Organism.objects.select_related('pfaf', 'photo_principale')
            .prefetch_related(
                'noms',
                'proprietes',
                'usages',
                'calendrier',
                'amendements_recommandes',
            )
            .order_by('id')
        )
        if organism_id_raw is not None and organism_id_raw != '':
            try:
                organism_id = int(organism_id_raw)
            except (TypeError, ValueError):
                return Response({'detail': 'organism_id invalide'}, status=400)
            qs = base_qs.filter(pk=organism_id)
            return _paginated_sync(request, qs, organism_to_sync_dict, None, 'date_modification')

        since_dt = _parse_since_param(request.query_params.get('since'))
        qs = base_qs.all()
        return _paginated_sync(request, qs, organism_to_sync_dict, since_dt, 'date_modification')


@extend_schema(
    summary='Sync cultivars (porte-greffes, pollinisateurs)',
    parameters=[
        OpenApiParameter('since', str, description='ISO 8601 — filtre date_modification > since'),
        OpenApiParameter('page', int),
        OpenApiParameter('page_size', int),
    ],
    tags=['sync'],
)
class SyncCultivarsView(APIView):
    permission_classes = [HasSyncAPIKey]

    def get(self, request):
        since_dt = _parse_since_param(request.query_params.get('since'))
        qs = (
            Cultivar.objects.select_related('organism')
            .prefetch_related('porte_greffes', 'pollinator_companions')
            .all()
            .order_by('id')
        )
        return _paginated_sync(request, qs, cultivar_to_sync_dict, since_dt, 'date_modification')


@extend_schema(
    summary='Sync relations de compagnonnage',
    parameters=[
        OpenApiParameter(
            'since',
            str,
            description='ISO 8601 — filtre date_ajout > since (nouvelles relations seulement)',
        ),
        OpenApiParameter('page', int),
        OpenApiParameter('page_size', int),
    ],
    tags=['sync'],
)
class SyncCompanionsView(APIView):
    permission_classes = [HasSyncAPIKey]

    def get(self, request):
        since_dt = _parse_since_param(request.query_params.get('since'))
        qs = CompanionRelation.objects.all().order_by('id')
        return _paginated_sync(request, qs, companion_to_sync_dict, since_dt, 'date_ajout')


@extend_schema(
    summary='Suppressions (tombstones) — réservé',
    description='V1 : listes vides. Suppressions côté Radix à gérer plus tard.',
    tags=['sync'],
)
class SyncDeletedView(APIView):
    permission_classes = [HasSyncAPIKey]

    def get(self, request):
        return Response(
            {
                'organisms': [],
                'cultivars': [],
                'amendments': [],
                'companions': [],
            }
        )
