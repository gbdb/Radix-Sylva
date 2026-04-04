"""
Sérialisation JSON des enregistrements pour l’API /sync/ (cache Jardin bIOT).
Les fichiers image OrganismPhoto ne sont pas poussés ; une URL externe peut être transmise
via photo_principale_url lorsque OrganismPhoto.source_url est renseigné.
"""
from __future__ import annotations

from botanique.models import (
    Amendment,
    CompanionRelation,
    Cultivar,
    CultivarPollinator,
    CultivarPorteGreffe,
    Organism,
    OrganismAmendment,
    OrganismCalendrier,
    OrganismNom,
    OrganismPFAF,
    OrganismPropriete,
    OrganismUsage,
)

# Champs scalaires Organism (hors id, photo_principale, search_vector).
ORGANISM_SYNC_FIELDS = (
    'nom_commun',
    'nom_latin',
    'slug_latin',
    'tsn',
    'vascan_id',
    'famille',
    'genus',
    'regne',
    'type_organisme',
    'besoin_eau',
    'besoin_soleil',
    'zone_rusticite',
    'sol_textures',
    'sol_ph',
    'sol_drainage',
    'sol_richesse',
    'hauteur_max',
    'largeur_max',
    'vitesse_croissance',
    'comestible',
    'parties_comestibles',
    'toxicite',
    'type_noix',
    'age_fructification',
    'periode_recolte',
    'pollinisation',
    'distance_pollinisation_max',
    'production_annuelle',
    'fixateur_azote',
    'accumulateur_dynamique',
    'mellifere',
    'produit_juglone',
    'indigene',
    'description',
    'notes',
    'usages_autres',
    'data_sources',
    'enrichment_score_pct',
)


def _iso(dt):
    if dt is None:
        return None
    return dt.isoformat() if hasattr(dt, 'isoformat') else dt


def amendment_to_sync_dict(a: Amendment) -> dict:
    return {
        'id': a.id,
        'nom': a.nom,
        'type_amendment': a.type_amendment,
        'azote_n': a.azote_n,
        'phosphore_p': a.phosphore_p,
        'potassium_k': a.potassium_k,
        'effet_ph': a.effet_ph,
        'bon_pour_sols': a.bon_pour_sols,
        'bon_pour_types': a.bon_pour_types,
        'description': a.description,
        'dose_recommandee': a.dose_recommandee,
        'periode_application': a.periode_application,
        'biologique': a.biologique,
        'date_ajout': _iso(a.date_ajout),
    }


def organism_nom_to_dict(n: OrganismNom) -> dict:
    return {
        'nom': n.nom,
        'langue': n.langue,
        'source': n.source,
        'principal': n.principal,
    }


def organism_propriete_to_dict(p: OrganismPropriete) -> dict:
    return {
        'type_sol': p.type_sol,
        'ph_min': p.ph_min,
        'ph_max': p.ph_max,
        'tolerance_ombre': p.tolerance_ombre,
        'source': p.source,
    }


def organism_usage_to_dict(u: OrganismUsage) -> dict:
    return {
        'type_usage': u.type_usage,
        'parties': u.parties,
        'description': u.description,
        'source': u.source,
    }


def organism_calendrier_to_dict(c: OrganismCalendrier) -> dict:
    return {
        'type_periode': c.type_periode,
        'mois_debut': c.mois_debut,
        'mois_fin': c.mois_fin,
        'source': c.source,
    }


def organism_amendment_to_dict(oa: OrganismAmendment) -> dict:
    return {
        'amendment_id': oa.amendment_id,
        'priorite': oa.priorite,
        'dose_specifique': oa.dose_specifique,
        'moment_application': oa.moment_application,
        'notes': oa.notes,
    }


def organism_pfaf_to_sync_dict(p: OrganismPFAF) -> dict:
    return {
        'edibility_rating': p.edibility_rating,
        'medicinal_rating': p.medicinal_rating,
        'edible_uses': p.edible_uses,
        'known_hazards': p.known_hazards,
        'cultivation_details': p.cultivation_details,
        'propagation': p.propagation,
        'uk_hardiness': p.uk_hardiness,
        'habit': p.habit,
        'pollinators': p.pollinators,
        'self_fertile': p.self_fertile,
        'scented': p.scented,
        'import_run_id': p.import_run_id,
        'date_import': _iso(p.date_import),
        'date_modification': _iso(p.date_modification),
    }


def organism_to_sync_dict(o: Organism) -> dict:
    d = {'id': o.id}
    for f in ORGANISM_SYNC_FIELDS:
        d[f] = getattr(o, f)
    d['date_ajout'] = _iso(o.date_ajout)
    d['date_modification'] = _iso(o.date_modification)
    d['noms'] = [organism_nom_to_dict(n) for n in o.noms.all()]
    d['proprietes'] = [organism_propriete_to_dict(p) for p in o.proprietes.all()]
    d['usages'] = [organism_usage_to_dict(u) for u in o.usages.all()]
    d['calendrier'] = [organism_calendrier_to_dict(c) for c in o.calendrier.all()]
    d['amendements_recommandes'] = [
        organism_amendment_to_dict(x) for x in o.amendements_recommandes.all()
    ]
    try:
        pfaf_data = organism_pfaf_to_sync_dict(o.pfaf)
    except OrganismPFAF.DoesNotExist:
        pfaf_data = None
    d['pfaf'] = pfaf_data
    if o.photo_principale and o.photo_principale.source_url:
        d['photo_principale_url'] = o.photo_principale.source_url
    else:
        d['photo_principale_url'] = None
    return d


def porte_greffe_to_dict(pg: CultivarPorteGreffe) -> dict:
    return {
        'nom_porte_greffe': pg.nom_porte_greffe,
        'vigueur': pg.vigueur,
        'hauteur_max_m': pg.hauteur_max_m,
        'notes': pg.notes,
        'source': pg.source,
        'disponible_chez': pg.disponible_chez,
    }


def pollinator_to_dict(p: CultivarPollinator) -> dict:
    return {
        'companion_cultivar_id': p.companion_cultivar_id,
        'companion_organism_id': p.companion_organism_id,
        'notes': p.notes,
        'source': p.source,
    }


def cultivar_to_sync_dict(c: Cultivar) -> dict:
    return {
        'id': c.id,
        'organism_id': c.organism_id,
        'slug_cultivar': c.slug_cultivar,
        'nom': c.nom,
        'description': c.description,
        'couleur_fruit': c.couleur_fruit,
        'gout': c.gout,
        'resistance_maladies': c.resistance_maladies,
        'notes': c.notes,
        'date_ajout': _iso(c.date_ajout),
        'date_modification': _iso(c.date_modification),
        'porte_greffes': [porte_greffe_to_dict(pg) for pg in c.porte_greffes.all()],
        'pollinators': [pollinator_to_dict(p) for p in c.pollinator_companions.all()],
    }


def companion_to_sync_dict(r: CompanionRelation) -> dict:
    return {
        'id': r.id,
        'organisme_source_id': r.organisme_source_id,
        'organisme_cible_id': r.organisme_cible_id,
        'type_relation': r.type_relation,
        'force': r.force,
        'distance_optimale': r.distance_optimale,
        'description': r.description,
        'source_info': r.source_info,
        'date_ajout': _iso(r.date_ajout),
    }
