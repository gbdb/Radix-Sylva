"""
Enrichit les organismes (espèces) avec les données Botanipedia (botanipedia.org).
Utilise l'API MediaWiki : recherche par nom latin, récupère le contenu des fiches
et stocke dans data_sources['botanipedia']. Remplit description / usages_autres si vides (fill_gaps).

Usage:
  python manage.py import_botanipedia --enrich --limit 50   # Enrichir les organismes existants
  python manage.py import_botanipedia --limit 10 --delay 1  # Limite et délai entre requêtes
"""
import re
import time
import requests
from django.core.management.base import BaseCommand

from botanique.models import Organism
from botanique.source_rules import SOURCE_BOTANIPEDIA, is_empty_value

BOTANIPEDIA_API = "https://www.botanipedia.org/api.php"
BOTANIPEDIA_NS = "Botanipedia"
USER_AGENT = "JardinBiot/1.0 (Botanipedia import; Django management command)"


def _build_botanipedia_title(nom_latin: str) -> str:
    """
    Construit le titre de page Botanipedia à partir du nom latin.
    Les fiches sont dans le namespace Botanipedia avec titres en MAJUSCULES
    (ex. AMARANTHUS RETROFLEXUS, ALISMA PLANTAGO-AQUATICA).
    """
    if not nom_latin or not nom_latin.strip():
        return ""
    q = nom_latin.strip()
    q = re.sub(r"\s*\([^)]*\)", " ", q)  # retirer auteur
    q = " ".join(q.split()[:4])  # genre + espèce (+ sous-espèce / variété)
    # Normaliser : majuscules, espaces gardés (MediaWiki accepte)
    return f"{BOTANIPEDIA_NS}:{q.upper()}"


def _search_page(session: requests.Session, nom_latin: str):
    """
    Recherche une page Botanipedia par nom scientifique.
    Retourne le titre de la première page trouvée ou None.
    """
    if not nom_latin or not nom_latin.strip():
        return None
    q = nom_latin.strip()
    # Retirer auteur entre parenthèses pour la recherche
    q = re.sub(r"\s*\([^)]*\)", " ", q).strip()
    q = " ".join(q.split()[:3])  # genre + espèce (+ sous-espèce)
    try:
        r = session.get(
            BOTANIPEDIA_API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": q,
                "srlimit": 3,
                "format": "json",
            },
            timeout=15,
            headers={"User-Agent": USER_AGENT},
        )
        r.raise_for_status()
        data = r.json()
        queries = data.get("query", {})
        results = queries.get("search", [])
        if not results:
            return None
        # Prendre le premier résultat (titre = nom de la page)
        return results[0].get("title")
    except (requests.RequestException, ValueError, KeyError):
        return None


def _get_page_content(session: requests.Session, title: str) -> str:
    """Récupère le contenu wiki (texte brut) d'une page par son titre."""
    if not title:
        return ""
    try:
        r = session.get(
            BOTANIPEDIA_API,
            params={
                "action": "query",
                "prop": "revisions",
                "titles": title,
                "rvprop": "content",
                "rvslots": "main",
                "format": "json",
            },
            timeout=15,
            headers={"User-Agent": USER_AGENT},
        )
        r.raise_for_status()
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if page_id == "-1":
                continue
            revs = page.get("revisions", [])
            if not revs:
                continue
            slot = revs[0].get("slots", {}).get("main", {})
            # MediaWiki renvoie le contenu dans la clé "*" pour rvslots=main
            return slot.get("*", "") or slot.get("content", "") or ""
    except (requests.RequestException, ValueError, KeyError):
        pass
    return ""


def _extract_excerpt(wiki_text: str, max_len: int = 2000) -> str:
    """Extrait un extrait lisible (retire balises wiki, limite la taille)."""
    if not wiki_text:
        return ""
    # Enlever les balises wiki grossières
    s = re.sub(r"\[\[([^\]|]+\|)?([^\]]+)\]\]", r"\2", wiki_text)
    s = re.sub(r"\{\{[^}]+\}\}", "", s)
    s = re.sub(r"['']{2,}", "", s)
    s = re.sub(r"\n+", "\n", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 3].rsplit(" ", 1)[0] + "..."
    return s


class Command(BaseCommand):
    help = (
        "Enrichit les organismes avec Botanipedia (botanipedia.org). "
        "Recherche par nom latin, stocke le contenu dans data_sources['botanipedia']."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--enrich",
            action="store_true",
            help="Enrichir les organismes existants (priorité : sans données Botanipedia)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Nombre max d'organismes à traiter (0 = illimité).",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=1.0,
            help="Délai en secondes entre chaque requête API (défaut: 1.0).",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Afficher pour chaque organisme pourquoi il est ignoré (aucune page trouvée).",
        )

    def handle(self, *args, **options):
        enrich = options["enrich"]
        limit = options["limit"] or 0
        delay = max(0.5, options["delay"])
        verbose = options.get("verbose", False)

        qs = Organism.objects.all().order_by("id")
        if enrich:
            # Priorité : organismes sans données Botanipedia
            from django.db.models import Q
            qs = qs.filter(
                Q(data_sources__isnull=True) | ~Q(data_sources__has_key=SOURCE_BOTANIPEDIA)
            )
        qs = qs.order_by("id")
        if limit > 0:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(
            self.style.SUCCESS(f"Import Botanipedia : {total} organisme(s) à traiter.")
        )
        if total == 0:
            self.stdout.write(
                self.style.WARNING(
                    "Aucun organisme en base. Importez d'abord des espèces (VASCAN, Hydro-Québec ou USDA) depuis Paramètres > Avancé."
                )
            )
            return

        session = requests.Session()
        updated = 0
        for organism in qs:
            nom = organism.nom_latin or ""
            if not nom.strip():
                continue
            # 1) Titre construit (Botanipedia:GENUS SPECIES) — correspondance exacte au wiki
            title = _build_botanipedia_title(nom)
            content = _get_page_content(session, title)
            if not content:
                # 2) Fallback : recherche full-text (souvent vide sur ce wiki)
                title = _search_page(session, nom)
                if title:
                    content = _get_page_content(session, title)
            time.sleep(delay)
            if not content:
                if verbose:
                    self.stdout.write(
                        self.style.WARNING(f"  — {organism.nom_commun or '?'} ({nom}) → aucune page Botanipedia pour « {title} »")
                    )
                continue
            excerpt = _extract_excerpt(content)
            payload = {"title": title, "excerpt": excerpt, "raw_length": len(content)}
            sources = dict(organism.data_sources or {})
            sources[SOURCE_BOTANIPEDIA] = payload
            organism.data_sources = sources
            if is_empty_value(organism.description) and excerpt:
                organism.description = excerpt[: 5000]
            if is_empty_value(organism.usages_autres) and "usage" in content.lower():
                organism.usages_autres = excerpt[: 1500]
            organism.save(update_fields=["data_sources", "description", "usages_autres", "date_modification"])
            updated += 1
            self.stdout.write(f"  ✓ {organism.nom_commun} ({nom}) → {title}")

        self.stdout.write(
            self.style.SUCCESS(f"\nTerminé : {updated} fiche(s) enrichie(s) avec Botanipedia.")
        )
        try:
            from botanique.enrichment_score import update_enrichment_scores
            res = update_enrichment_scores()
            self.stdout.write(self.style.SUCCESS(f"  Enrichissement: note globale {res['global_score_pct']}%"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Recalcul enrichissement: {e}"))
