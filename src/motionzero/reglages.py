"""Registre des réglages de l'accueil (plan-accueil.md, étape 1). Sans Qt : testable.

Un réglage = une entrée de REGLAGES + son texte dans tile_text + son effet dans la boucle principale
(app_ecoute). L'interface les place seule dans leur groupe.
"""
import logging
import os
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from . import parametres as _p   # tous les choix dans parametres.json (26/11)
LECTURE_FILE = _p.LECTURE         # « oui » : rappels, messages et réponses lus
SECTION_FILE = _p.SECTION         # dernière section ouverte de l'accueil
SECTIONS = ("maintenant", "reglages", "conso")

GROUPES = ("Entrées", "Voix et sons", "Dépannage")


@dataclass(frozen=True)
class Reglage:
    id: str
    groupe: str
    titre: str
    danger: bool = False


REGLAGES = (
    Reglage("souris", "Entrées", "Souris"),
    Reglage("camera", "Entrées", "Caméra"),
    Reglage("conversation", "Voix et sons", "Mode conversation"),
    Reglage("voix_basse", "Voix et sons", "Voix basse"),
    Reglage("volume", "Voix et sons", "Volume d'Iris"),
    Reglage("lecture", "Voix et sons", "Lecture à voix haute"),
    Reglage("son", "Dépannage", "Son"),
)
IDS = tuple(r.id for r in REGLAGES)


def par_groupe():
    """[(groupe, [Reglage, ...]), ...] dans l'ordre fixe des groupes, groupes vides omis."""
    return [(g, [r for r in REGLAGES if r.groupe == g]) for g in GROUPES if any(r.groupe == g for r in REGLAGES)]


def tile_text(rid, value):
    """(valeur affichée, note, ton) d'une carte. ton : ok | alerte | neutre. Pur : testable."""
    if rid == "souris":
        return ("À la tête", "clic : passer à la main", "neutre") if value == "tete" else \
               ("À la main", "clic : passer à la tête", "neutre")
    if rid == "camera":                 # value : True = coupée
        return ("Coupée", "clic : la rallumer", "alerte") if value else \
               ("Allumée", "clic : la rendre à Discord", "ok")
    if rid == "conversation":
        return ("Coché", "mot noyé dans une phrase ignoré", "ok") if value else \
               ("Décoché", "tout mot reconnu agit", "alerte")
    if rid == "voix_basse":
        return {"oui": ("Toujours", "clic : jamais", "neutre"),
                "non": ("Jamais", "clic : le soir", "neutre")}.get(
            value, ("Le soir", "22 h - 7 h · clic : toujours", "neutre"))
    if rid == "volume":
        try:
            return (f"{round(float(value) * 100)} %", "30 · 50 · 70 · 100", "neutre")
        except (TypeError, ValueError):
            return ("?", "30 · 50 · 70 · 100", "neutre")
    if rid == "lecture":
        return ("Activée", "rappels et messages Discord lus", "ok") if value else \
               ("Désactivée", "rien n'est lu à voix haute", "neutre")
    if rid == "son":                    # value : True = réparation en cours
        return ("En cours…", "micro et sortie rouverts", "neutre") if value else \
               ("Réparer", "rouvre micro et sortie", "neutre")
    return ("?", "", "neutre")


def read_flag(path, default=False):
    """« oui » / « non » enregistré ; défaut si absent ou illisible."""
    return {"oui": True, "non": False}.get(path.read(), default)


def write_flag(path, on):
    path.write("oui" if on else "non")


def read_section(path=SECTION_FILE):
    v = path.read()
    return v if v in SECTIONS else SECTIONS[0]


def write_section(name, path=SECTION_FILE):
    path.write(name)
