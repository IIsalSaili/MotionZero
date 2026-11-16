"""Commandes d'Iris écrites en MP au bot Discord (issue #43).

Le bot transmet le texte ({"t": "command", "id", "text"}) ; Iris le traite dans la boucle principale comme
« iris » + le mot dit, puis renvoie {"t": "command_result", "id", "ok", "text"} que le bot écrit dans le MP.
Le résultat se lit dans l'île (core.last_gesture) : un échec y est marqué (is_failure), comme pour la voix.
"""
import difflib
import re

from .sounds import is_failure
from .voice import SPLIT, WORDS

# suivies d'une phrase dite (Whisper) : pas encore possibles par écrit
NEEDS_SPEECH = {"ouvre", "type", "question", "message", "salon", "rappel", "timer", "volume", "claude"}
# « stop » arrête Iris : à distance, plus personne pour la relancer
REFUSED = {"stop"}
WAIT_S = 1.5          # temps laissé à la commande pour s'exécuter avant de lire l'île
VOCAB = (set(WORDS) | set(SPLIT.values())) - {"iris"}


def parse(text):
    """Texte du MP -> (mot, None) ou (None, (erreur, suggestions)). Pur : testable."""
    s = re.sub(r"[^\w' -]", " ", (text or "").lower()).strip()
    s = re.sub(r"^iris\b", "", s).strip()
    s = " ".join(s.split())
    s = {"double clic": "double", "envoyé": "envoie"}.get(s, s)
    if not s:
        return None, ("message_vide", [])
    if s in REFUSED:
        return None, ("refuse_a_distance", [])
    if s.split()[0] in NEEDS_SPEECH:
        return None, ("pas_encore_par_ecrit", [])
    if s not in VOCAB:
        return None, ("commande_inconnue", difflib.get_close_matches(s, sorted(VOCAB), n=3, cutoff=0.6))
    return s, None


ERROR_TEXT = {"message_vide": "Message vide : écris une commande, par exemple « studio ».",
              "refuse_a_distance": "« stop » est refusé à distance : personne ne pourrait relancer Iris.",
              "pas_encore_par_ecrit": "Cette commande attend une phrase dite au micro : pas encore possible par écrit.",
              "commande_inconnue": "Commande inconnue."}


def error_reply(req_id, error, suggestions):
    text = ERROR_TEXT[error]
    if suggestions:
        text += " Tu voulais dire : " + ", ".join(suggestions) + " ?"
    return {"t": "command_result", "id": req_id, "ok": False, "text": text}


class Pending:
    """Une commande exécutée, dont on attend l'effet dans l'île avant de répondre."""

    def __init__(self, req_id, word, before, t):
        self.id, self.word, self.before, self.t = req_id, word, before, t

    def reply(self, last_gesture, t):
        """Réponse à envoyer, ou None s'il faut encore attendre. Pur : testable."""
        changed = last_gesture is not None and last_gesture is not self.before
        if changed and is_failure(last_gesture[0]):
            return {"t": "command_result", "id": self.id, "ok": False, "text": f"Échec : {last_gesture[0]}"}
        if t - self.t < WAIT_S:
            return None
        label = last_gesture[0] if changed else "fait"
        return {"t": "command_result", "id": self.id, "ok": True, "text": f"« {self.word} » : {label}"}
