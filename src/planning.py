"""Planification d'un passage (conception § 2).

Le workflow se déclenche toutes les heures, souvent en retard. Ce module décide, en heure
de Paris, ce qui est dû. La règle n'est jamais « est-il 8h pile ? » mais « le dernier succès
date-t-il d'assez longtemps, et sommes-nous dans la plage autorisée ? » : un passage en
retard ou sauté ne fait rien perdre.

`taches_dues` est une fonction pure : l'heure, l'historique et les compteurs sont passés en
argument, ce qui la rend testable sans horloge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import Config


@dataclass(frozen=True)
class Plan:
    sources: list[str]
    resume_quotidien: bool = False
    bilan_hebdomadaire: bool = False
    alertes_en_attente: bool = False      # premier passage du matin : envoyer les alertes de la nuit
    hors_plage: bool = False
    raisons: dict[str, str] = field(default_factory=dict)


def _local(utc_naif: datetime, fuseau: ZoneInfo) -> datetime:
    return utc_naif.replace(tzinfo=UTC).astimezone(fuseau)


def taches_dues(maintenant_utc: datetime, derniers_succes: dict[str, datetime],
                derniers_envois: dict[tuple[str, str | None], datetime],
                requetes_adzuna_mois: int, config: Config) -> Plan:
    """Toutes les dates sont en UTC sans fuseau, comme dans la base."""
    p = config.planning
    fuseau = ZoneInfo(p.fuseau)
    local = _local(maintenant_utc, fuseau)
    raisons: dict[str, str] = {}

    if not (p.plage.debut <= local.hour < p.plage.fin):
        return Plan(sources=[], hors_plage=True, raisons={"plage": f"{local:%H:%M} hors de la plage"})

    sources = []
    for nom, actif in config.sources.actives.items():
        if not actif:
            continue
        tache = p.taches.get(nom)
        if tache is None:
            raisons[nom] = "pas de rythme défini"
            continue
        dernier = derniers_succes.get(nom)
        if dernier is not None and maintenant_utc - dernier < timedelta(minutes=tache.intervalle_minutes):
            raisons[nom] = f"dernier succès il y a {int((maintenant_utc - dernier).total_seconds() // 60)} min"
            continue
        if nom == "adzuna" and requetes_adzuna_mois >= p.quotas.adzuna_mensuel:
            raisons[nom] = f"quota mensuel atteint ({requetes_adzuna_mois})"
            continue
        sources.append(nom)

    def deja_envoye_depuis(type_envoi: str, borne_locale: datetime) -> bool:
        dates = [d for (t, _), d in derniers_envois.items() if t == type_envoi]
        return any(_local(d, fuseau) >= borne_locale for d in dates)

    debut_jour = local.replace(hour=0, minute=0, second=0, microsecond=0)
    resume = local.hour >= p.envois.resume_quotidien_heure and not deja_envoye_depuis("resume", debut_jour)

    b = p.envois.bilan_hebdomadaire
    debut_semaine = debut_jour - timedelta(days=local.weekday())
    bilan_du = local.weekday() > b.jour or (local.weekday() == b.jour and local.hour >= b.heure)
    bilan = bilan_du and not deja_envoye_depuis("bilan", debut_semaine)

    # Alertes retenues pendant la nuit : le premier passage du jour les envoie.
    alertes = not deja_envoye_depuis("matin", debut_jour)

    return Plan(sources=sources, resume_quotidien=resume, bilan_hebdomadaire=bilan,
                alertes_en_attente=alertes, raisons=raisons)
