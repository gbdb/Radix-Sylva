from django.urls import include, path
from rest_framework.routers import DefaultRouter

from botanique.api_views import (
    AmendmentViewSet,
    CultivarViewSet,
    OrganismRequestView,
    OrganismViewSet,
)
from botanique.sync_views import (
    SyncAmendmentsView,
    SyncCompanionsView,
    SyncCultivarsView,
    SyncDeletedView,
    SyncMetaView,
    SyncOrganismsView,
)

router = DefaultRouter()
router.register(r'organisms', OrganismViewSet, basename='organism')
router.register(r'cultivars', CultivarViewSet, basename='cultivar')
router.register(r'amendments', AmendmentViewSet, basename='amendment')

urlpatterns = [
    # Pas sous « organisms/<pk>/ » : le routeur DRF interpréterait « request » comme un id.
    path('organism-request/', OrganismRequestView.as_view(), name='organism-request'),
    path('sync/meta/', SyncMetaView.as_view(), name='sync-meta'),
    path('sync/amendments/', SyncAmendmentsView.as_view(), name='sync-amendments'),
    path('sync/organisms/', SyncOrganismsView.as_view(), name='sync-organisms'),
    path('sync/cultivars/', SyncCultivarsView.as_view(), name='sync-cultivars'),
    path('sync/companions/', SyncCompanionsView.as_view(), name='sync-companions'),
    path('sync/deleted/', SyncDeletedView.as_view(), name='sync-deleted'),
    path('', include(router.urls)),
]
