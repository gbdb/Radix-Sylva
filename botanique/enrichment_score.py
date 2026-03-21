"""
Note d'enrichissement des fiches espèces (0-100 %).
Recalculée après import/migration ; stockée sur Organism et agrégée dans BaseEnrichmentStats.
"""
from django.utils import timezone

from botanique.models import BaseEnrichmentStats, Organism


def _filled_str(val):
    """True si chaîne non vide (après strip)."""
    if val is None:
        return False
    return bool(str(val).strip())


def _filled_list(val):
    """True si liste/JSON non vide."""
    if val is None:
        return False
    if isinstance(val, list):
        return len(val) > 0
    return False


def _filled_bool(val):
    """True si booléen défini (on compte True comme enrichissement)."""
    return val is True


def compute_organism_enrichment_score(organism: Organism) -> int:
    """
    Calcule la note d'enrichissement d'une fiche Organism (0-100).
    Basé sur les champs « enrichissants » : description, culture, usages, médias, etc.
    """
    checks = [
        # Identification (déjà requis en général)
        ("nom_commun", lambda o: _filled_str(o.nom_commun)),
        ("nom_latin", lambda o: _filled_str(o.nom_latin)),
        ("famille", lambda o: _filled_str(o.famille)),
        ("genus", lambda o: _filled_str(o.genus)),
        # Culture
        ("zone_rusticite", lambda o: _filled_list(o.zone_rusticite)),
        ("besoin_eau", lambda o: _filled_str(o.besoin_eau)),
        ("besoin_soleil", lambda o: _filled_str(o.besoin_soleil)),
        ("sol_textures", lambda o: _filled_list(o.sol_textures)),
        ("sol_ph", lambda o: _filled_list(o.sol_ph)),
        ("sol_drainage", lambda o: _filled_str(o.sol_drainage)),
        ("sol_richesse", lambda o: _filled_str(o.sol_richesse)),
        # Physique
        ("hauteur_max", lambda o: o.hauteur_max is not None),
        ("largeur_max", lambda o: o.largeur_max is not None),
        ("vitesse_croissance", lambda o: _filled_str(o.vitesse_croissance)),
        # Comestibilité / usages
        ("description", lambda o: _filled_str(o.description)),
        ("parties_comestibles", lambda o: _filled_str(o.parties_comestibles)),
        ("toxicite", lambda o: _filled_str(o.toxicite)),
        ("usages_autres", lambda o: _filled_str(o.usages_autres)),
        # Écologie
        ("indigene", lambda o: o.indigene is True),
        # Relations dérivées (existence d'au moins une entrée)
        ("has_proprietes", lambda o: o.proprietes.exists()),
        ("has_usages", lambda o: o.usages.exists()),
        ("has_calendrier", lambda o: o.calendrier.exists()),
        # Média
        ("has_photo", lambda o: o.photo_principale_id is not None or o.reference_photos.exists()),
    ]
    total = len(checks)
    filled = sum(1 for _, check in checks if check(organism))
    if total == 0:
        return 0
    return round(100 * filled / total)


def update_enrichment_scores(since=None):
    """
    Recalcule enrichment_score_pct pour tous les organismes et met à jour BaseEnrichmentStats.
    - since: réservé (ignoré pour l’instant). Recalcul complet pour une note globale cohérente.
    """
    qs = Organism.objects.all().prefetch_related("proprietes", "usages", "calendrier", "reference_photos")
    to_update = []
    sum_scores = 0
    for org in qs:
        score = compute_organism_enrichment_score(org)
        org.enrichment_score_pct = score
        to_update.append(org)
        sum_scores += score
    total_count = len(to_update)
    if to_update:
        Organism.objects.bulk_update(to_update, ["enrichment_score_pct"], batch_size=500)
    global_pct = round(sum_scores / total_count) if total_count else None
    stats = BaseEnrichmentStats.objects.first()
    if stats is None:
        stats = BaseEnrichmentStats(organism_count=0, global_score_pct=None)
    stats.organism_count = total_count
    stats.global_score_pct = global_pct
    stats.computed_at = timezone.now()
    stats.save()
    return {"updated": total_count, "total": total_count, "global_score_pct": global_pct}
