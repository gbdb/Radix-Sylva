from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from botanique.enrichment import enrich_organism
from botanique.models import Amendment, Cultivar, Organism
from botanique.permissions import HasSyncAPIKey
from botanique.serializers import (
    AmendmentSerializer,
    CultivarSerializer,
    OrganismDetailSerializer,
    OrganismListSerializer,
)
from botanique.source_rules import ensure_organism_genus, find_or_match_organism


class OrganismRequestSerializer(serializers.Serializer):
    """Payload pour demande d'espèce (BIOT / outils internes)."""

    nom_latin = serializers.CharField(max_length=200)
    nom_commun = serializers.CharField(max_length=200, required=False, allow_blank=True)
    tsn = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    vascan_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class OrganismRequestView(APIView):
    """
    Crée ou associe un Organism (stub) puis enrichit via VASCAN uniquement.
    Protégé par la même clé que /sync/.
    URL : POST /api/v1/organism-request/ (pas organisms/request/ : « request » était pris pour un pk).
    """

    permission_classes = [HasSyncAPIKey]

    @extend_schema(
        summary='Demander une espèce (stub + enrichissement VASCAN)',
        description=(
            'Trouve ou crée un organisme, applique ensure_organism_genus, '
            "puis enrich_organism avec sources=['vascan'] et delay=0."
        ),
        request=OrganismRequestSerializer,
        tags=['organisms'],
    )
    def post(self, request):
        ser = OrganismRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        nom_latin = (ser.validated_data['nom_latin'] or '').strip()
        nom_commun = (ser.validated_data.get('nom_commun') or '').strip()
        tsn = ser.validated_data.get('tsn')
        vascan_id = ser.validated_data.get('vascan_id')

        defaults = {
            'type_organisme': 'vivace',
            'nom_commun': nom_commun or nom_latin,
        }
        organism, was_created = find_or_match_organism(
            Organism,
            nom_latin=nom_latin,
            nom_commun=nom_commun or nom_latin,
            defaults=defaults,
            tsn=tsn,
            vascan_id=vascan_id,
            create_missing=True,
        )
        ensure_organism_genus(organism)

        enrichment = enrich_organism(organism, sources=['vascan'], delay=0)
        enrichment_payload = {k: {'ok': v[0], 'message': v[1]} for k, v in enrichment.items()}

        list_ser = OrganismListSerializer(organism, context={'request': request})
        return Response(
            {
                'organism_id': organism.pk,
                'created': was_created,
                'matched_existing': not was_created,
                'enrichment': enrichment_payload,
                'organism': list_ser.data,
            },
            status=status.HTTP_200_OK,
        )


class OrganismViewSet(viewsets.ReadOnlyModelViewSet):
    """API publique lecture (Pass A)."""

    permission_classes = [AllowAny]
    queryset = Organism.objects.all().order_by('nom_commun')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return OrganismDetailSerializer
        return OrganismListSerializer


class CultivarViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    queryset = Cultivar.objects.select_related('organism').all().order_by('organism__nom_latin', 'nom')
    serializer_class = CultivarSerializer


class AmendmentViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    queryset = Amendment.objects.all().order_by('nom')
    serializer_class = AmendmentSerializer
