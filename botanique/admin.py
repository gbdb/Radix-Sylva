from django.contrib import admin

from botanique.models import (
    Amendment,
    BaseEnrichmentStats,
    CompanionRelation,
    Cultivar,
    CultivarPollinator,
    CultivarPorteGreffe,
    DataImportRun,
    Organism,
    OrganismAmendment,
    OrganismCalendrier,
    OrganismNom,
    OrganismPhoto,
    OrganismPropriete,
    OrganismUsage,
)


@admin.register(OrganismPhoto)
class OrganismPhotoAdmin(admin.ModelAdmin):
    list_display = ('id', 'organism', 'titre', 'type_photo', 'date_ajout')
    search_fields = ('titre', 'description')
    raw_id_fields = ('organism',)


class OrganismNomInline(admin.TabularInline):
    model = OrganismNom
    extra = 0


@admin.register(Organism)
class OrganismAdmin(admin.ModelAdmin):
    list_display = ('id', 'nom_commun', 'nom_latin', 'famille', 'comestible', 'date_modification')
    search_fields = ('nom_commun', 'nom_latin', 'famille')
    list_filter = ('comestible', 'type_organisme', 'regne')
    inlines = [OrganismNomInline]
    raw_id_fields = ('photo_principale',)


@admin.register(Cultivar)
class CultivarAdmin(admin.ModelAdmin):
    list_display = ('nom', 'organism', 'slug_cultivar')
    search_fields = ('nom', 'slug_cultivar')
    raw_id_fields = ('organism',)


@admin.register(DataImportRun)
class DataImportRunAdmin(admin.ModelAdmin):
    list_display = ('source', 'status', 'started_at', 'finished_at', 'user')
    list_filter = ('source', 'status')


admin.site.register(OrganismPropriete)
admin.site.register(OrganismUsage)
admin.site.register(OrganismCalendrier)
admin.site.register(CompanionRelation)
admin.site.register(CultivarPollinator)
admin.site.register(CultivarPorteGreffe)
admin.site.register(Amendment)
admin.site.register(OrganismAmendment)
admin.site.register(BaseEnrichmentStats)
