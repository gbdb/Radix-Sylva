"""
Radix Sylva — base botanique publique : Organism, Cultivar, compagnonnage, amendements.
Tables `species_*` conservées pour compatibilité import pg_dump / sync depuis Jardin bIOT.
Pas de tags utilisateur ni inventaire semences (restent côté BIOT).
"""
from django.conf import settings
from django.db import models

from botanique.utils import slugify_latin

# PostgreSQL full-text search (optional on SQLite)
try:
    from django.contrib.postgres.search import SearchVectorField
    from django.contrib.postgres.indexes import GinIndex
except ImportError:
    SearchVectorField = None
    GinIndex = None


class OrganismPhoto(models.Model):
    """Photo de référence pour une espèce (métadonnées licence / source)."""
    organism = models.ForeignKey(
        'botanique.Organism',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='reference_photos',
        help_text="Espèce illustrée (galerie / import Wikimedia). La photo principale est aussi pointée par Organism.photo_principale.",
    )
    image = models.ImageField(upload_to='organism_photos/%Y/%m/')
    type_photo = models.CharField(max_length=40, blank=True)
    titre = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    date_prise = models.DateField(null=True, blank=True)
    source_url = models.URLField(blank=True)
    source_author = models.CharField(max_length=200, blank=True)
    source_license = models.CharField(max_length=50, blank=True)
    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'species_organismphoto'
        verbose_name = 'Photo (organisme)'
        verbose_name_plural = 'Photos (organismes)'
        ordering = ['-date_ajout']

    def __str__(self):
        return self.titre or f'Photo #{self.pk}'


class Organism(models.Model):
    """Espèce botanique (une ligne par espèce). Données stables multi-sources."""
    nom_commun = models.CharField(max_length=200, db_index=True, help_text="Nom commun principal (ex: Pommier, Basilic)")
    nom_latin = models.CharField(max_length=200, db_index=True, help_text="Nom scientifique latin (ex: Malus pumila)")
    slug_latin = models.SlugField(max_length=220, unique=True, blank=True, null=True, help_text="Clé unique dérivée du nom latin")
    tsn = models.PositiveIntegerField(null=True, blank=True, unique=True, db_index=True, help_text="Taxonomic Serial Number (ITIS/USDA)")
    vascan_id = models.PositiveIntegerField(null=True, blank=True, unique=True, db_index=True, help_text="Identifiant VASCAN")
    famille = models.CharField(max_length=100, blank=True, db_index=True, help_text="Famille botanique")
    genus = models.CharField(max_length=80, blank=True, db_index=True, help_text="Genre botanique")
    REGNE_CHOICES = [('plante', 'Plante'), ('champignon', 'Champignon'), ('mousse', 'Mousse/Bryophyte')]
    regne = models.CharField(max_length=20, choices=REGNE_CHOICES, default='plante')
    TYPE_CHOICES = [
        ('arbre_fruitier', 'Arbre fruitier'), ('arbre_noix', 'Arbre à noix'), ('arbre_ornement', "Arbre d'ornement"),
        ('arbre_bois', 'Arbre forestier/bois'), ('arbuste_fruitier', 'Arbuste fruitier'), ('arbuste_baies', 'Arbuste à baies'),
        ('arbuste', 'Arbuste'), ('vivace', 'Plante vivace'), ('annuelle', 'Plante annuelle'), ('bisannuelle', 'Plante bisannuelle'),
        ('herbe_aromatique', 'Herbe aromatique'), ('legume', 'Légume'), ('grimpante', 'Plante grimpante'), ('couvre_sol', 'Couvre-sol'),
        ('champignon_comestible', 'Champignon comestible'), ('champignon_mycorhize', 'Champignon mycorhizien'), ('mousse', 'Mousse'),
    ]
    type_organisme = models.CharField(max_length=30, choices=TYPE_CHOICES, db_index=True)
    BESOIN_EAU_CHOICES = [('tres_faible', 'Très faible'), ('faible', 'Faible'), ('moyen', 'Moyen'), ('eleve', 'Élevé'), ('tres_eleve', 'Très élevé')]
    besoin_eau = models.CharField(max_length=15, choices=BESOIN_EAU_CHOICES, default='moyen', blank=True)
    BESOIN_SOLEIL_CHOICES = [('ombre_complete', 'Ombre complète'), ('ombre', 'Ombre'), ('mi_ombre', 'Mi-ombre'), ('soleil_partiel', 'Soleil partiel'), ('plein_soleil', 'Plein soleil')]
    besoin_soleil = models.CharField(max_length=20, choices=BESOIN_SOLEIL_CHOICES, default='plein_soleil', blank=True)
    zone_rusticite = models.JSONField(default=list, blank=True, help_text="Liste de zones avec source")
    SOL_TEXTURE_CHOICES = [('argileux', 'Argileux'), ('limoneux', 'Limoneux'), ('sablonneux', 'Sablonneux'), ('loameux', 'Loameux'), ('rocailleux', 'Rocailleux'), ('tourbeux', 'Tourbeux')]
    sol_textures = models.JSONField(default=list, blank=True, help_text="Liste des textures acceptées")
    SOL_PH_CHOICES = [('tres_acide', 'Très acide (< 5.5)'), ('acide', 'Acide (5.5-6.5)'), ('neutre', 'Neutre (6.5-7.5)'), ('alcalin', 'Alcalin (> 7.5)')]
    sol_ph = models.JSONField(default=list, blank=True, help_text="pH acceptés")
    SOL_DRAINAGE_CHOICES = [('tres_draine', 'Très drainé/sec'), ('bien_draine', 'Bien drainé'), ('humide', 'Humide'), ('demarais', 'Détrempé/marécageux')]
    sol_drainage = models.CharField(max_length=20, choices=SOL_DRAINAGE_CHOICES, blank=True)
    sol_richesse = models.CharField(max_length=20, choices=[('pauvre', 'Pauvre'), ('moyen', 'Moyen'), ('riche', 'Riche/Fertile')], blank=True)
    hauteur_max = models.FloatField(null=True, blank=True, help_text="Hauteur maximale en mètres")
    largeur_max = models.FloatField(null=True, blank=True, help_text="Largeur/envergure maximale en mètres")
    vitesse_croissance = models.CharField(max_length=20, choices=[('tres_lente', 'Très lente'), ('lente', 'Lente'), ('moyenne', 'Moyenne'), ('rapide', 'Rapide'), ('tres_rapide', 'Très rapide')], blank=True)
    comestible = models.BooleanField(default=True, db_index=True, help_text="Est-ce comestible pour les humains?")
    parties_comestibles = models.TextField(blank=True, help_text="Ex: fruits, feuilles, racines")
    toxicite = models.TextField(blank=True, help_text="Parties toxiques, précautions")
    TYPE_NOIX_CHOICES = [('noyer', 'Noyer'), ('noisettier', 'Noisetier'), ('chataignier', 'Châtaignier'), ('amandier', 'Amandier'), ('pecanier', 'Pécanier'), ('pin_pignon', 'Pin à pignons'), ('caryer', 'Caryer')]
    type_noix = models.CharField(max_length=20, choices=TYPE_NOIX_CHOICES, blank=True)
    age_fructification = models.IntegerField(null=True, blank=True, help_text="Années avant première fructification")
    periode_recolte = models.CharField(max_length=100, blank=True, help_text="Ex: Juillet-Septembre")
    pollinisation = models.TextField(blank=True, help_text="Auto-fertile, besoin pollinisateur, etc.")
    distance_pollinisation_max = models.FloatField(null=True, blank=True, help_text="Distance max de pollinisation en mètres")
    production_annuelle = models.CharField(max_length=100, blank=True, help_text="Production moyenne à maturité")
    fixateur_azote = models.BooleanField(default=False, db_index=True, help_text="Fixe l'azote atmosphérique")
    accumulateur_dynamique = models.BooleanField(default=False, help_text="Accumule nutriments du sous-sol")
    mellifere = models.BooleanField(default=False, db_index=True, help_text="Attire les pollinisateurs")
    produit_juglone = models.BooleanField(default=False, help_text="Produit juglone (noyers)")
    indigene = models.BooleanField(default=False, db_index=True, help_text="Espèce indigène")
    description = models.TextField(blank=True, help_text="Description générale")
    notes = models.TextField(blank=True, help_text="Notes personnelles")
    usages_autres = models.TextField(blank=True, help_text="Usages non-comestibles")
    data_sources = models.JSONField(default=dict, blank=True, help_text="Données de sources externes")
    photo_principale = models.ForeignKey(
        'botanique.OrganismPhoto',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='organismes_photo_principale',
        help_text="Photo affichée par défaut",
    )
    enrichment_score_pct = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True, help_text="Note d'enrichissement (0-100 %)")
    date_ajout = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    search_vector = (
        SearchVectorField(null=True, blank=True)
        if SearchVectorField is not None
        else models.TextField(null=True, blank=True)
    )

    class Meta:
        db_table = 'species_espece'
        verbose_name = "Espèce"
        verbose_name_plural = "Espèces"
        ordering = ['nom_commun']
        indexes = [GinIndex(fields=['search_vector'], name='species_espece_sv_gin')] if (SearchVectorField is not None and GinIndex is not None) else []

    def __str__(self):
        if self.nom_latin:
            return f"{self.nom_commun} ({self.nom_latin})"
        return self.nom_commun

    def save(self, *args, **kwargs):
        if not self.slug_latin and self.nom_latin:
            self.slug_latin = slugify_latin(self.nom_latin)
        super().save(*args, **kwargs)

    def get_zones_by_source(self, source: str) -> list:
        if not self.zone_rusticite or not isinstance(self.zone_rusticite, list):
            return []
        return [z.get('zone') for z in self.zone_rusticite if isinstance(z, dict) and z.get('source') == source and z.get('zone')]

    def get_primary_zone(self) -> str:
        if not self.zone_rusticite or not isinstance(self.zone_rusticite, list):
            return ''
        zones = [z.get('zone') for z in self.zone_rusticite if isinstance(z, dict) and z.get('zone')]
        if not zones:
            return ''
        from botanique.source_rules import zone_rusticite_order
        zones_sorted = sorted(zones, key=zone_rusticite_order)
        return zones_sorted[0] if zones_sorted else ''


class OrganismNom(models.Model):
    """Nom alternatif d'un organisme (multilingue, par source). Organism.nom_commun reste le nom principal."""
    LANGUE_CHOICES = [
        ('fr', 'Français'),
        ('en', 'Anglais'),
        ('autre', 'Autre'),
    ]
    organism = models.ForeignKey(
        'botanique.Organism',
        on_delete=models.CASCADE,
        related_name='noms',
    )
    nom = models.CharField(max_length=200)
    langue = models.CharField(max_length=10, choices=LANGUE_CHOICES)
    source = models.CharField(max_length=80)
    principal = models.BooleanField(default=False)

    class Meta:
        db_table = 'species_organismnom'
        verbose_name = "Nom (organisme)"
        verbose_name_plural = "Noms (organismes)"
        ordering = ['organism', 'langue', 'source']

    def __str__(self):
        return f"{self.nom} ({self.langue}, {self.source})"


class OrganismPropriete(models.Model):
    """Propriétés du sol et exposition pour un organisme (1-N par source)."""
    organisme = models.ForeignKey('botanique.Organism', on_delete=models.CASCADE, related_name='proprietes')
    type_sol = models.JSONField(default=list, blank=True, help_text="Liste de types: sablonneux, argileux, etc.")
    ph_min = models.FloatField(null=True, blank=True)
    ph_max = models.FloatField(null=True, blank=True)
    TOLERANCE_OMBRE_CHOICES = [('ombre_complete', 'Ombre complète'), ('ombre', 'Ombre'), ('mi_ombre', 'Mi-ombre'), ('soleil_partiel', 'Soleil partiel'), ('plein_soleil', 'Plein soleil')]
    tolerance_ombre = models.CharField(max_length=20, choices=TOLERANCE_OMBRE_CHOICES, blank=True)
    source = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = 'species_organismpropriete'
        verbose_name = "Propriété (sol / exposition)"
        verbose_name_plural = "Propriétés (sol / exposition)"
        ordering = ['organisme', 'source']

    def __str__(self):
        return f"{self.organisme.nom_commun} — {self.source or '?'}"


class OrganismUsage(models.Model):
    """Usages d'un organisme: comestible, médicinal, bois, etc."""
    organisme = models.ForeignKey('botanique.Organism', on_delete=models.CASCADE, related_name='usages')
    TYPE_USAGE_CHOICES = [
        ('comestible_fruit', 'Comestible (fruit)'), ('comestible_feuille', 'Comestible (feuille)'), ('comestible_racine', 'Comestible (racine)'),
        ('comestible_fleur', 'Comestible (fleur)'), ('comestible_autre', 'Comestible (autre)'), ('medicinal', 'Médicinal'),
        ('bois_oeuvre', 'Bois d\'œuvre'), ('artisanat', 'Artisanat'), ('ornement', 'Ornement'), ('autre', 'Autre'),
    ]
    type_usage = models.CharField(max_length=30, choices=TYPE_USAGE_CHOICES)
    parties = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    source = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = 'species_organismusage'
        verbose_name = "Usage"
        verbose_name_plural = "Usages"
        ordering = ['organisme', 'type_usage']

    def __str__(self):
        return f"{self.organisme.nom_commun} — {self.get_type_usage_display()}"


class OrganismCalendrier(models.Model):
    """Périodes typiques par espèce: floraison, fructification, récolte, semis."""
    organisme = models.ForeignKey('botanique.Organism', on_delete=models.CASCADE, related_name='calendrier')
    TYPE_PERIODE_CHOICES = [('floraison', 'Floraison'), ('fructification', 'Fructification'), ('recolte', 'Récolte'), ('semis', 'Semis'), ('taille', 'Taille'), ('autre', 'Autre')]
    type_periode = models.CharField(max_length=20, choices=TYPE_PERIODE_CHOICES)
    mois_debut = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Mois (1-12)")
    mois_fin = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Mois (1-12)")
    source = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = 'species_organismcalendrier'
        verbose_name = "Calendrier (période)"
        verbose_name_plural = "Calendrier (périodes)"
        ordering = ['organisme', 'type_periode', 'mois_debut']

    def __str__(self):
        return f"{self.organisme.nom_commun} — {self.get_type_periode_display()} ({self.mois_debut or '?'}-{self.mois_fin or '?'})"


class CompanionRelation(models.Model):
    """Relations de compagnonnage entre organismes."""
    organisme_source = models.ForeignKey('botanique.Organism', on_delete=models.CASCADE, related_name='relations_sortantes', help_text="Organisme qui produit l'effet")
    organisme_cible = models.ForeignKey('botanique.Organism', on_delete=models.CASCADE, related_name='relations_entrantes', help_text="Organisme qui reçoit l'effet")
    TYPE_RELATION_CHOICES = [
        ('compagnon_positif', '✅ Compagnon bénéfique'), ('fixateur_azote', '🌱 Fixe azote'), ('attire_pollinisateurs', '🐝 Attire pollinisateurs'),
        ('repousse_nuisibles', '🛡️ Repousse nuisibles'), ('abri', '🏠 Fournit abri'), ('coupe_vent', '💨 Coupe vent'), ('support_physique', '🪜 Support'),
        ('mycorhize', '🍄 Mycorhize'), ('accumulateur', '💎 Accumule nutriments'), ('compagnon_negatif', '❌ Compagnon néfaste'), ('allelopathie', '☠️ Allélopathie'),
        ('competition_eau', '💧 Compétition eau'), ('competition_lumiere', '☀️ Compétition lumière'), ('competition_nutriments', '🌿 Compétition nutriments'), ('hote_maladie', '🦠 Hôte maladie'),
    ]
    type_relation = models.CharField(max_length=30, choices=TYPE_RELATION_CHOICES)
    force = models.IntegerField(default=5, help_text="Intensité (1-10)")
    distance_optimale = models.FloatField(null=True, blank=True, help_text="Distance optimale en mètres")
    description = models.TextField(blank=True)
    source_info = models.CharField(max_length=200, blank=True)
    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'species_companionrelation'
        verbose_name = "Relation de compagnonnage"
        verbose_name_plural = "Relations de compagnonnage"
        unique_together = ['organisme_source', 'organisme_cible', 'type_relation']
        ordering = ['organisme_source__nom_commun']

    def __str__(self):
        symbole = "✅" if "positif" in self.type_relation or "attire" in self.type_relation or "fixateur" in self.type_relation else "⚠️"
        return f"{symbole} {self.organisme_source.nom_commun} → {self.organisme_cible.nom_commun} ({self.get_type_relation_display()})"


class Cultivar(models.Model):
    """Variété / cultivar d'une espèce."""
    organism = models.ForeignKey('botanique.Organism', on_delete=models.CASCADE, related_name='cultivars', help_text="Espèce (ex: Malus pumila)")
    slug_cultivar = models.SlugField(max_length=250, unique=True, help_text="Clé unique (ex: malus-pumila-dolgo)")
    nom = models.CharField(max_length=200, help_text="Nom du cultivar (ex: Dolgo)")
    description = models.TextField(blank=True)
    couleur_fruit = models.CharField(max_length=100, blank=True)
    gout = models.CharField(max_length=200, blank=True)
    resistance_maladies = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    date_ajout = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'species_cultivar'
        verbose_name = "Cultivar"
        verbose_name_plural = "Cultivars"
        ordering = ['organism__nom_latin', 'nom']

    def __str__(self):
        return f"{self.nom} ({self.organism.nom_latin})"


class CultivarPollinator(models.Model):
    """Compagnon pollinisation au niveau cultivar."""
    cultivar = models.ForeignKey('botanique.Cultivar', on_delete=models.CASCADE, related_name='pollinator_companions')
    companion_cultivar = models.ForeignKey('botanique.Cultivar', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    companion_organism = models.ForeignKey('botanique.Organism', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    notes = models.TextField(blank=True)
    source = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'species_cultivar_pollinator'
        verbose_name = "Pollinisateur recommandé (cultivar)"
        verbose_name_plural = "Pollinisateurs recommandés (cultivars)"
        constraints = [models.CheckConstraint(check=models.Q(companion_cultivar__isnull=False) | models.Q(companion_organism__isnull=False), name='cultivar_pollinator_companion_required')]

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.companion_cultivar_id and not self.companion_organism_id:
            raise ValidationError("Au moins un de companion_cultivar ou companion_organism doit être renseigné.")

    def __str__(self):
        if self.companion_cultivar_id:
            return f"{self.cultivar.nom} ← {self.companion_cultivar.nom}"
        return f"{self.cultivar.nom} ← espèce {self.companion_organism.nom_commun}"


class CultivarPorteGreffe(models.Model):
    """Porte-greffe associé à un cultivar (vigueur, disponibilité par source)."""
    VIGUEUR_CHOICES = [
        ('nain', 'Nain'),
        ('semi_nain', 'Semi-nain'),
        ('semi_vigoureux', 'Semi-vigoureux'),
        ('vigoureux', 'Vigoureux'),
        ('standard', 'Standard'),
    ]
    cultivar = models.ForeignKey(
        'botanique.Cultivar',
        on_delete=models.CASCADE,
        related_name='porte_greffes',
    )
    nom_porte_greffe = models.CharField(max_length=100, help_text="Ex: B9, MM106")
    vigueur = models.CharField(
        max_length=20,
        choices=VIGUEUR_CHOICES,
        blank=True,
    )
    hauteur_max_m = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True)
    source = models.CharField(max_length=80)
    disponible_chez = models.JSONField(
        default=list,
        blank=True,
        help_text='Liste d\'objets ex. [{"source": "ancestrale", "age": "1.5"}]',
    )

    class Meta:
        db_table = 'species_cultivarportegreffe'
        verbose_name = "Porte-greffe (cultivar)"
        verbose_name_plural = "Porte-greffes (cultivars)"
        ordering = ['cultivar', 'nom_porte_greffe']

    def __str__(self):
        return f"{self.cultivar.nom} — {self.nom_porte_greffe}"


class Amendment(models.Model):
    """Engrais, compost, amendements du sol."""
    nom = models.CharField(max_length=200, help_text="Ex: Compost maison, Chaux dolomitique")
    TYPE_CHOICES = [('compost', 'Compost'), ('fumier', 'Fumier'), ('engrais_vert', 'Engrais vert'), ('mineraux', 'Amendement minéral'), ('organique_commercial', 'Engrais organique commercial'), ('chimique', 'Engrais chimique'), ('paillis', 'Paillis/Mulch'), ('brf', 'BRF'), ('autre', 'Autre')]
    type_amendment = models.CharField(max_length=25, choices=TYPE_CHOICES)
    azote_n = models.FloatField(null=True, blank=True, help_text="% Azote (N)")
    phosphore_p = models.FloatField(null=True, blank=True, help_text="% Phosphore (P)")
    potassium_k = models.FloatField(null=True, blank=True, help_text="% Potassium (K)")
    EFFET_PH_CHOICES = [('acidifie', 'Acidifie le sol'), ('neutre', 'Neutre'), ('alcalinise', 'Alcalinise/Chaux le sol')]
    effet_ph = models.CharField(max_length=15, choices=EFFET_PH_CHOICES, blank=True)
    bon_pour_sols = models.JSONField(default=list, blank=True)
    bon_pour_types = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True)
    dose_recommandee = models.CharField(max_length=200, blank=True)
    periode_application = models.CharField(max_length=200, blank=True)
    biologique = models.BooleanField(default=True, help_text="Accepté en agriculture biologique?")
    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'species_amendment'
        verbose_name = "Amendement"
        verbose_name_plural = "Amendements"
        ordering = ['nom']

    def __str__(self):
        npk = ""
        if self.azote_n or self.phosphore_p or self.potassium_k:
            npk = f" ({self.azote_n or 0}-{self.phosphore_p or 0}-{self.potassium_k or 0})"
        return f"{self.nom}{npk}"


class OrganismAmendment(models.Model):
    """Recommandation : quel amendement pour quel organisme."""
    organisme = models.ForeignKey('botanique.Organism', on_delete=models.CASCADE, related_name='amendements_recommandes')
    amendment = models.ForeignKey('botanique.Amendment', on_delete=models.CASCADE, related_name='organismes_recommandes')
    PRIORITE_CHOICES = [(1, 'Recommandé'), (2, 'Utile'), (3, 'Optionnel'), (4, 'À éviter')]
    priorite = models.IntegerField(choices=PRIORITE_CHOICES, default=1, help_text="Niveau de recommandation")
    dose_specifique = models.CharField(max_length=200, blank=True)
    moment_application = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'species_organismamendment'
        verbose_name = "Recommandation Organisme-Amendement"
        verbose_name_plural = "Recommandations Organisme-Amendement"
        unique_together = ['organisme', 'amendment']
        ordering = ['organisme__nom_commun', 'priorite']

    def __str__(self):
        return f"{self.organisme.nom_commun} ← {self.amendment.nom} ({self.get_priorite_display()})"


class BaseEnrichmentStats(models.Model):
    """Singleton : note d'enrichissement globale de la base."""
    global_score_pct = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Note moyenne (0-100 %).")
    organism_count = models.PositiveIntegerField(default=0, help_text="Nombre d'organismes au moment du calcul.")
    last_updated = models.DateTimeField(auto_now=True, help_text="Dernière mise à jour des stats.")
    computed_at = models.DateTimeField(null=True, blank=True, help_text="Date/heure du dernier recalcul.")

    class Meta:
        verbose_name = "Stats enrichissement (base)"
        verbose_name_plural = "Stats enrichissement (base)"
        db_table = "species_base_enrichment_stats"

    def __str__(self):
        return f"Enrichissement base: {self.global_score_pct}% ({self.organism_count} espèces)"


class DataImportRun(models.Model):
    """Historique des imports / enrichissements (tables alignées Jardin bIOT)."""

    SOURCE_CHOICES = [
        ('pfaf', 'PFAF'),
        ('seeds', 'Semences (CSV/JSON)'),
        ('import_vascan', 'Import VASCAN'),
        ('import_usda', 'Import USDA'),
        ('import_hydroquebec', 'Import Hydro-Québec'),
        ('import_botanipedia', 'Import Botanipedia'),
        ('import_arbres_en_ligne', 'Import Arbres en ligne'),
        ('import_arbres_montreal', 'Import Arbres Montréal'),
        ('import_arbres_quebec', 'Import Arbres Québec'),
        ('import_ancestrale', 'Import Pépinière ancestrale'),
        ('import_topic', 'Import TOPIC Canada'),
        ('import_usda_chars', 'Import USDA PLANTS (caractéristiques)'),
        ('import_wikidata', 'Import Wikidata'),
        ('import_wikimedia_photos', 'Import Wikimedia photos'),
        ('merge_organism_duplicates', 'Merge doublons'),
        ('populate_genus', 'Populate genus'),
        ('populate_proprietes_usage_calendrier', 'Populate propriétés/usages/calendrier'),
        ('rebuild_search_vectors', 'Rebuild search vectors'),
        ('update_enrichment_scores', 'Update enrichment scores'),
        ('backup_restore', 'Backup / Restore'),
        ('clean_organisms_keep_hq', 'Clean (garde Hydro-Québec)'),
        ('wipe_species', 'Wipe species'),
        ('wipe_db_and_media', 'Wipe DB and media'),
    ]
    STATUS_CHOICES = [
        ('running', 'En cours'),
        ('success', 'Succès'),
        ('failure', 'Échec'),
    ]
    TRIGGER_CHOICES = [
        ('admin_import', 'Admin (import)'),
        ('gestion_donnees', 'Gestion des données'),
        ('api', 'API'),
    ]

    source = models.CharField(
        max_length=80,
        choices=SOURCE_CHOICES,
        db_index=True,
        help_text="Type d'import ou commande exécutée",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='running',
        db_index=True,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    stats = models.JSONField(default=dict, blank=True, help_text="Résumé: created, updated, errors, etc.")
    output_snippet = models.TextField(
        blank=True,
        help_text="Derniers caractères de la sortie (stdout/err) pour débogage",
    )
    trigger = models.CharField(
        max_length=30,
        choices=TRIGGER_CHOICES,
        default='gestion_donnees',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='radix_data_import_runs',
    )

    class Meta:
        db_table = 'species_dataimportrun'
        verbose_name = "Exécution d'import"
        verbose_name_plural = "Exécutions d'import"
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['source', '-started_at']),
        ]

    def __str__(self):
        return f"{self.get_source_display()} — {self.started_at:%Y-%m-%d %H:%M} ({self.get_status_display()})"


class OrganismPFAF(models.Model):
    """Données détaillées importées depuis Plants For A Future (PFAF), liées 1:1 à Organism."""
    organism = models.OneToOneField(
        'Organism', on_delete=models.CASCADE, related_name='pfaf'
    )
    edibility_rating = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Note comestibilité PFAF (0-5)"
    )
    medicinal_rating = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Note médicinale PFAF (0-5)"
    )
    edible_uses = models.TextField(
        blank=True, help_text="Usages comestibles selon PFAF"
    )
    known_hazards = models.TextField(
        blank=True, help_text="Dangers et toxicité selon PFAF"
    )
    cultivation_details = models.TextField(
        blank=True, help_text="Détails de culture selon PFAF"
    )
    propagation = models.TextField(
        blank=True, help_text="Propagation selon PFAF"
    )
    uk_hardiness = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Rusticité PFAF échelle UK (1-10)"
    )
    habit = models.CharField(
        max_length=50, blank=True,
        help_text="Port de la plante selon PFAF (Tree, Shrub, Perennial...)"
    )
    pollinators = models.CharField(
        max_length=200, blank=True, help_text="Pollinisateurs selon PFAF"
    )
    self_fertile = models.BooleanField(
        null=True, blank=True, help_text="Auto-fertile selon PFAF"
    )
    scented = models.BooleanField(
        null=True, blank=True, help_text="Plante parfumée selon PFAF"
    )
    import_run = models.ForeignKey(
        'DataImportRun', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='pfaf_records'
    )
    date_import = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'species_organismpfaf'
        verbose_name = "Données PFAF"
        verbose_name_plural = "Données PFAF"

    def __str__(self):
        return f"PFAF — {self.organism.nom_latin}"
