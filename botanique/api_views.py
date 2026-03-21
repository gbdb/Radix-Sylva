from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from botanique.models import Amendment, Cultivar, Organism
from botanique.serializers import (
    AmendmentSerializer,
    CultivarSerializer,
    OrganismDetailSerializer,
    OrganismListSerializer,
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
