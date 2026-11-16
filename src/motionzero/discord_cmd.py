"""Commandes d'Iris écrites en MP au bot Discord (issue #43).

Le bot transmet le texte ({"t": "command", "id", "text"}) ; Iris le traite dans la boucle principale comme
« iris » + le mot dit, puis renvoie {"t": "command_result", "id", "ok", "text"} que le bot écrit dans le MP.
Les commandes suivies d'une phrase (« ouvre spotify », « timer 10 minutes ») reçoivent le reste du MP à la
place de l'enregistrement du micro : Whisper est sauté, tout le reste est le chemin de la voix.
Le résultat se lit dans l'île (core.last_gesture) : un échec y est marqué (is_failure), comme pour la voix.
"""
import difflib
import re

from .sounds import is_failure
from .voice import SPLIT, WORDS

# suivies d'une phrase (dite au micro, ici écrite dans le MP)
WITH_PHRASE = {"ouvre", "ferme", "type", "question", "message", "salon", "rappel", "timer", "volume", "claude"}
# la phrase est obligatoire (« ferme » seul retire la réponse affichée, « timer » seul arrête celui en cours)
PHRASE_NEEDED = {"ouvre", "type", "question", "message", "salon", "rappel", "claude"}
# « stop » arrête Iris : à distance, plus personne pour la relancer
REFUSED = {"stop"}
WAIT_S = 1.5          # temps laissé à la commande pour s'exécuter avant de lire l'île
WAIT_PHRASE_S = 8.0   # appli à lancer, message à envoyer, rappel compris par Haiku… : plus long
WAIT_BOT_S = 20.0     # viens / pars / activation / message / salon : on attend la réponse du bot lui-même
BOT_WORDS = {"viens", "pars", "activation", "message", "salon"}
VOCAB = (set(WORDS) | set(SPLIT.values())) - {"iris"}
EXAMPLES = {"ouvre": "ouvre spotify", "type": "type bonjour", "question": "question quel temps fait-il",
            "message": "message dans général, salut", "salon": "salon jeux", "rappel": "rappel dans 10 minutes, pâtes",
            "claude": "claude corrige le test"}


def parse(text):
    """Texte du MP -> (mot, phrase, None) ou (None, None, (erreur, suggestions)). Pur : testable."""
    raw = re.sub(r"^\s*iris\b[\s,:!.]*", "", (text or "").strip(), flags=re.I)
    head = raw.split(None, 1)
    first = re.sub(r"[^\w'-]", "", head[0].lower()) if head else ""
    if first in WITH_PHRASE:
        phrase = head[1].strip() if len(head) > 1 else ""
        if not phrase and first in PHRASE_NEEDED:
            return None, None, ("phrase_manquante", [EXAMPLES[first]])
        return first, phrase or None, None
    s = " ".join(re.sub(r"[^\w' -]", " ", raw.lower()).split())
    s = {"double clic": "double", "envoyé": "envoie"}.get(s, s)
    if not s:
        return None, None, ("message_vide", [])
    if s in REFUSED:
        return None, None, ("refuse_a_distance", [])
    if s not in VOCAB:
        return None, None, ("commande_inconnue", difflib.get_close_matches(s, sorted(VOCAB), n=3, cutoff=0.6))
    return s, None, None


ERROR_TEXT = {"message_vide": "Message vide : écris une commande, par exemple « studio ».",
              "refuse_a_distance": "« stop » est refusé à distance : personne ne pourrait relancer Iris.",
              "phrase_manquante": "Il manque la suite de la commande.",
              "pas_de_micro": "Iris tourne sans la voix : les commandes avec une phrase ne marchent pas.",
              "commande_inconnue": "Commande inconnue."}


def error_reply(req_id, error, suggestions):
    text = ERROR_TEXT[error]
    if suggestions:
        text += (" Exemple : " if error == "phrase_manquante" else " Tu voulais dire : ") + ", ".join(suggestions)
        text += "." if error == "phrase_manquante" else " ?"
    return {"t": "command_result", "id": req_id, "ok": False, "text": text}


class Pending:
    """Une commande exécutée, dont on attend l'effet dans l'île avant de répondre."""

    def __init__(self, req_id, word, before, t, wait=WAIT_S):
        self.id, self.word, self.before, self.t, self.wait = req_id, word, before, t, wait
        self.bot_result = None            # (réussi ?, texte) : réponse du bot à l'ordre envoyé par Iris

    def reply(self, last_gesture, t):
        """Réponse à envoyer, ou None s'il faut encore attendre. Pur : testable."""
        if self.bot_result is not None:
            ok, label = self.bot_result
            return {"t": "command_result", "id": self.id, "ok": ok,
                    "text": f"« {self.word} » : {label}" if ok else f"Échec : {label}"}
        changed = last_gesture is not None and last_gesture is not self.before
        if self.word in BOT_WORDS and not (changed and is_failure(last_gesture[0])):
            if t - self.t < self.wait:
                return None
            return {"t": "command_result", "id": self.id, "ok": False,
                    "text": f"« {self.word} » : ordre envoyé, mais le bot n'a pas répondu"}
        if changed and is_failure(last_gesture[0]):
            return {"t": "command_result", "id": self.id, "ok": False, "text": f"Échec : {last_gesture[0]}"}
        if t - self.t < self.wait:
            return None
        label = last_gesture[0] if changed else "fait"
        return {"t": "command_result", "id": self.id, "ok": True, "text": f"« {self.word} » : {label}"}
