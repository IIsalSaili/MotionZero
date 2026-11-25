"""« iris candidature » : Iris pilote CVGEN (plan-cvgen.md), sans rien changer à CVGEN : méthodes de Candidature (EvenementsMixin, découpé de cvgen.py, #52)."""
import logging
import queue

from .cvgen_base import BUSY_MAX_S, HELP_S, prep_text

log = logging.getLogger("motionzero.cvgen")


class EvenementsMixin:

    def events(self, core, t):
        if not self.busy:
            self._busy_t = None
        elif self._busy_t is None:
            self._busy_t = t
        elif t - self._busy_t > BUSY_MAX_S:      # réponse perdue : on débloque plutôt que d'attendre pour rien
            log.warning("cvgen : demande sans réponse depuis %.0f s, oubliée", t - self._busy_t)
            self.busy, self._busy_t = False, None
            self._show("Candidature", ["CVGEN n'a pas répondu : redis la commande"], t)
        while True:
            try:
                msg = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                self._event(msg, core, t)
            except Exception:                     # un message mal traité ne bloque jamais le mode
                log.exception("cvgen : message %s", msg[0])
                self.busy = False
                self._show("Candidature", ["Erreur inattendue : redis la commande"], t)
        return []

    def _event(self, msg, core, t):
        if True:
            if msg[0] == "wait":
                self._show("Candidature", [msg[1]], t)
            elif msg[0] == "chiffres":
                self.agent = msg[1] if msg[1] is not None else self.agent
                self.compte = msg[2]
            elif msg[0] == "ok" and self.offres and msg[1] == "Candidature":
                self.busy = False                   # « état » avec une offre affichée : les chiffres suffisent
                self._card(t)
            elif msg[0] == "ok":
                self.busy = False
                self._show(msg[1], msg[2], t)
                core.last_gesture = (f"CANDIDATURE : {msg[1]}".upper()[:60], t)
            elif msg[0] == "liste":
                self.busy = False
                self.offres, self.i = msg[1], 0
                self._card(t)
                core.last_gesture = (f"CANDIDATURE : {len(msg[1])} OFFRES", t)
            elif msg[0] == "field":
                self.busy = False
                _, word, value = msg
                if value is None:
                    self._show(self.title or "Candidature", [f"« {word} » : absent de ton profil CVGEN"], t, self.meta)
                elif not self.browser_front():   # le focus a changé pendant l'attente : rien n'est tapé
                    self._show(self.title or "Candidature", [f"« {word} » : le navigateur n'est plus devant, "
                                                             "rien n'est écrit"], t, self.meta)
                else:
                    self.typer(value)
                    core.last_gesture = (f"CANDIDATURE : {word.upper()} ECRIT", t)
            elif msg[0] == "files":
                self.busy = False
                _, oid, paths, word = msg
                self.files[oid] = paths
                self._file(oid, word, t)
            elif msg[0] == "reponse":
                self.busy = False
                _, question, rep_ = msg
                if rep_ is None:
                    self._show("Candidature", ["Pas de réponse du modèle : redis « question »"], t)
                else:
                    self.reponse = rep_
                    self._show("Réponse proposée", [f"Question : {question}"[:160], rep_,
                                                    "« écris » : l'écrire dans le champ cliqué"], t)
                    self.show_until = t + HELP_S
                core.last_gesture = ("CANDIDATURE : REPONSE PROPOSEE" if rep_ else "CANDIDATURE : PAS DE REPONSE", t)
            elif msg[0] == "brouillon":
                self.busy = False
                _, oid, path, to = msg
                try:
                    if self.open_url is not None:
                        self.open_url(path)
                    note = f"Brouillon pour {to} ouvert : relis, puis envoie"
                except OSError:
                    note = "Brouillon prêt, mais aucun logiciel de mail ne l'ouvre"
                if self.offres and self.offres[self.i]["id"] == oid:
                    self._card(t, note)
                else:
                    self._show("Candidature", [note], t)
            elif msg[0] == "long":                 # « détails », « relances » : le temps de lire
                self.busy = False
                self._show(msg[1], msg[2], t)
                self.show_until = t + HELP_S
            elif msg[0] == "note":
                self.busy = False
                if self.offres and self.offres[self.i]["id"] == msg[1]:
                    self._card(t, msg[2])
                else:
                    self._show("Candidature", [msg[2]], t)
            elif msg[0] == "annule":
                self.busy = False
                _, o, pos = msg
                self.last = None
                self.offres = [x for x in self.offres or [] if x["id"] != o["id"]]
                pos = min(pos, len(self.offres))
                self.offres.insert(pos, o)
                self.i = pos
                self._card(t, "Annulé : l'offre est revenue")
                core.last_gesture = ("CANDIDATURE : ANNULE", t)
            elif msg[0] == "verdict":
                self.busy = False
                _, oid, word = msg
                for k, x in enumerate(self.offres or []):
                    if x["id"] == oid:
                        self.last = (dict(x), k)       # « annule » la remet à sa place, dans son état d'avant
                if word == "garde":                # reste visible, « CV en cours », jusqu'à son CV (#59)
                    self.offres = [dict(o, etat="gardee") if o["id"] == oid else o for o in self.offres or []]
                else:
                    self.offres = [o for o in self.offres or [] if o["id"] != oid]
                    self.todo = [o for o in self.todo if o["id"] != oid]
                self.i = min(self.i, max(len(self.offres) - 1, 0))
                fait = {"garde": "Gardée : CVGEN prépare son CV", "écarte": "Écartée",
                        "postulé": "Notée postulée : relance dans 7 jours"}[word]
                self._card(t, fait)
                core.last_gesture = (f"CANDIDATURE : {fait}".upper()[:60], t)
            elif msg[0] == "prep":
                _, oid, prep = msg
                self.busy = False
                self.prep[oid] = prep_text(prep)
                if prep.get("etape") in ("pret", "erreur") and self.preparing == oid:
                    self.preparing = None
                elif prep.get("etape") not in ("pret", "erreur") and self.preparing is None:
                    self.preparing = oid           # préparation reprise après une relance d'Iris
                if self.offres and self.offres[self.i]["id"] == oid:
                    self._card(t)              # l'offre affichée : la carte suit l'avancement
                core.last_gesture = (f"CANDIDATURE : {self.prep[oid]}".upper()[:60], t)
                if self.preparing is None and self.todo:
                    self._next_prep(t)             # « prépare tout » : la suivante
            elif msg[0] == "error":
                self.busy = False
                self._show("Candidature impossible", [msg[1]], t)
                core.last_gesture = (f"CANDIDATURE : {msg[1]}".upper()[:60], t)
