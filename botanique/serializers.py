from rest_framework import serializers

from botanique.models import Amendment, Cultivar, Organism


class OrganismListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organism
        fields = (
            'id',
            'nom_commun',
            'nom_latin',
            'slug_latin',
            'famille',
            'genus',
            'type_organisme',
            'comestible',
            'date_modification',
        )


class OrganismDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organism
        exclude = ('search_vector',)


class CultivarSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cultivar
        fields = '__all__'


class AmendmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Amendment
        fields = '__all__'
