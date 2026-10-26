"""Note détaillée d'une offre et niveau (conception § 6).

Une note est une somme de composantes lisibles (« priorité 1 +6 », « ESN −4 »). Les deux ou
trois plus fortes accompagnent l'offre dans Telegram et dans l'onglet Veille.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from src.config import Config
from src.models import Niveau, Offre, TypeEmployeur
from src.normalisation.texte import contient, normaliser, premier_motif


@dataclass(frozen=True)
class Note:
    total: int
    composantes: list[tuple[str, int]] = field(default_factory=list)
    archivee: str | None = None        # raison d'un archivage d'office (verdict définitif du suivi)
    cible: bool = False                # entreprise « Cible » ou « Cible prioritaire » dans le suivi

    def raisons(self, n: int = 3) -> list[str]:
        """Les n composantes les plus fortes, en valeur absolue : « priorité 1 +6 »."""
        tri = sorted(self.composantes, key=lambda c: abs(c[1]), reverse=True)[:n]
        return [f"{r} {p:+d}" for r, p in tri]


def table_verdicts(lignes: list[tuple[str, str]]) -> dict[str, str]:
    """[(entreprise, verdict)] lus dans l'onglet Entreprises -> {nom normalisé: verdict normalisé}."""
    return {normaliser(e): normaliser(v) for e, v in lignes if normaliser(e) and normaliser(v)}


def verdict_de(entreprise: str, verdicts: dict[str, str]) -> str | None:
    """Verdict de l'entreprise : nom du suivi contenu (mots entiers) dans le nom de l'offre.

    « SOCOTEC » reconnaît « SOCOTEC Group ». En cas de plusieurs correspondances, le nom le plus
    long l'emporte. Les noms de moins de 3 caractères sont ignorés (trop ambigus).
    """
    n = normaliser(entreprise)
    if not n:
        return None
    trouves = [(len(nom), v) for nom, v in verdicts.items() if len(nom) >= 3 and contient(n, nom)]
    return max(trouves)[1] if trouves else None


def noter(o: Offre, config: Config, aujourdhui: date, verdicts: dict[str, str] | None = None,
          republiee: bool = False) -> Note:
    n = config.notation
    comp: list[tuple[str, int]] = []
    texte = normaliser(f"{o.titre} {o.description}")
    titre = normaliser(o.titre)

    if o.priorite:
        comp.append((f"priorité {o.priorite}", n.priorite_famille.get(o.priorite, 0)))

    reconnues = [c for c in n.competences.liste if contient(texte, c)]
    if reconnues:
        comp.append((f"compétences ({', '.join(reconnues[:4])})",
                     min(len(reconnues) * n.competences.points, n.competences.plafond)))

    x = n.niveau_experience
    if premier_motif(texte, x.signaux_junior):
        comp.append(("signal junior", x.junior))
    if o.debutant_accepte:
        comp.append(("débutant accepté", x.debutant_accepte))
    if premier_motif(titre, x.mots_confirme):
        comp.append(("« confirmé » dans le titre", x.confirme_titre))
    # « Débutant accepté » vaut déjà pour 0 an : pas de double compte.
    if (not o.debutant_accepte and o.annees_requises is not None and o.annees_requises in x.annees
            and x.annees[o.annees_requises]):
        comp.append((f"{o.annees_requises} an(s) d'expérience demandé(s)", x.annees[o.annees_requises]))

    e = n.employeur
    points_employeur = {TypeEmployeur.ESN: ("ESN", e.esn), TypeEmployeur.INTERMEDIAIRE: ("seconde main", e.intermediaire),
                        TypeEmployeur.INCONNU: ("employeur non indiqué", e.inconnu),
                        TypeEmployeur.ECOLE: ("école", e.ecole)}
    if o.type_employeur in points_employeur:
        comp.append(points_employeur[o.type_employeur])

    archivee, cible = None, False
    verdict = verdict_de(o.entreprise, verdicts or {})
    if verdict:
        s = n.suivi
        if any(verdict.startswith(d) for d in s.ecarter_definitif):
            archivee = f"suivi : {verdict}"
        elif verdict.startswith("cible prioritaire"):
            comp.append(("cible prioritaire du suivi", s.cible_prioritaire))
            cible = True
        elif verdict.startswith("cible"):
            comp.append(("cible du suivi", s.cible))
            cible = True
        elif verdict.startswith("derniere priorite"):
            comp.append(("dernière priorité du suivi", s.derniere_priorite))
        elif verdict.startswith("ecarter"):
            comp.append(("écartée dans le suivi", s.ecarter))

    sg = n.signaux
    if o.date_publication:
        try:
            age = (aujourdhui - date.fromisoformat(o.date_publication[:10])).days
        except ValueError:
            age = None
        if age is not None and age <= 1:
            comp.append(("publiée depuis un jour au plus", sg.publiee_depuis_un_jour))
        elif age is not None and age >= 5:
            comp.append((f"publiée il y a {age} jours", sg.publiee_depuis_5_jours))
    if republiee:
        comp.append(("republiée", sg.republiee))
    if o.faible_concurrence:
        comp.append(("peu candidatée", sg.peu_candidatee))
    if o.zone_preferee:
        comp.append(("zone préférée", sg.zone_preferee))
    if o.teletravail_complet:
        comp.append(("télétravail complet", sg.teletravail_complet))

    comp = [(r, p) for r, p in comp if p]
    return Note(total=sum(p for _, p in comp), composantes=comp, archivee=archivee, cible=cible)


def niveau(o: Offre, note: Note, config: Config) -> Niveau:
    s = config.notation.niveaux
    if note.archivee:
        return Niveau.ARCHIVE
    a = s.alerte
    seconde_main = o.type_employeur in (TypeEmployeur.INTERMEDIAIRE, TypeEmployeur.INCONNU)
    if (note.total >= a.note_min and o.fil is not None and str(o.fil) in a.fils
            and (not a.exige_priorite_1_ou_cible or o.priorite == 1 or note.cible)
            and not (a.exclut_seconde_main and seconde_main)):
        return Niveau.ALERTE
    if note.total >= s.resume.note_min:
        return Niveau.RESUME
    return Niveau.ARCHIVE

