"""Choix de l'utilisateur gardés d'un démarrage à l'autre, tous dans un seul fichier : parametres.json (non versionné).

Chaque réglage est un Param (une clé du fichier). Remplace les 7 petits fichiers .txt d'un seul choix chacun
(26/11) : ils sont repris une fois au démarrage (migrate), puis supprimés.
"""
import json
import logging
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILE = os.path.join(ROOT, "parametres.json")
_lock = threading.Lock()          # l'accueil (fil Qt) et la boucle principale écrivent tous deux
_log = logging.getLogger("motionzero")

# clé -> ancien fichier d'un seul choix
LEGACY = {"pointeur": "pointeur.txt", "quota": "quota.txt", "conversation": "conversation.txt",
          "voix_basse": "voix_basse.txt", "volume": "volume_iris.txt", "lecture": "lecture.txt",
          "accueil_section": "accueil_section.txt"}


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)             # jamais de fichier à moitié écrit si Iris s'arrête pendant l'écriture


class Param:
    """Un réglage : une clé de parametres.json."""

    def __init__(self, key, file=None):
        self.key, self.file = key, file or FILE

    def read(self):
        """Valeur enregistrée (texte), ou None si absente ou fichier illisible."""
        with _lock:
            v = _load(self.file).get(self.key)
        return None if v is None else str(v)

    def write(self, value):
        """Enregistre ; False (avertissement au journal, jamais d'exception) si l'écriture échoue."""
        try:
            with _lock:
                data = _load(self.file)
                data[self.key] = str(value)
                _save(self.file, data)
            return True
        except OSError:
            _log.warning("reglage non enregistre : %s", self.key)
            return False

    def __repr__(self):
        return f"Param({self.key!r})"


def migrate(file=None, root=ROOT):
    """Reprend les anciens fichiers .txt dans parametres.json (une valeur déjà dans le JSON gagne), puis les
    supprime. Un fichier illisible est laissé en place. Renvoie les clés reprises."""
    file = file or FILE
    found = {}
    for key, name in LEGACY.items():
        p = os.path.join(root, name)
        try:
            with open(p, encoding="utf-8") as f:
                found[key] = (f.read().strip(), p)
        except OSError:
            continue
    if not found:
        return []
    try:
        with _lock:
            data = _load(file)
            taken = [k for k in found if k not in data]
            for k in taken:
                data[k] = found[k][0]
            _save(file, data)
    except OSError:
        _log.warning("reglages : reprise des anciens fichiers impossible")
        return []
    for _, p in found.values():
        try:
            os.remove(p)
        except OSError:
            pass
    _log.info("reglages repris dans parametres.json : %s", ", ".join(taken) or "aucun nouveau")
    return taken


POINTER = Param("pointeur")         # « main » ou « tete »
QUOTA = Param("quota")              # « oui » : quota affiché
CONVERSATION = Param("conversation")   # « oui » (défaut) ou « non »
QUIET = Param("voix_basse")         # « auto », « oui » ou « non »
VOLUME = Param("volume")            # volume des sons d'Iris, 0..1
LECTURE = Param("lecture")          # « oui » : lecture à voix haute
SECTION = Param("accueil_section")  # dernière section ouverte de l'accueil
