"""« iris candidature » : Iris pilote CVGEN (plan-cvgen.md), sans rien changer à CVGEN : méthodes de Candidature (CommandesMixin, découpé de cvgen.py, #52)."""
import logging
import threading

from .cvgen_base import BASE, CLOSE_HINT, FIELDS, FILES, FILE_DIALOG, HELP_LINES, HELP_S, LINKS, NAV, PAGES, PREP_STEPS

log = logging.getLogger("motionzero.cvgen")


class CommandesMixin:

    # ---- boucle principale ----
    def ask(self, word, t):
        if (word in FIELDS or word in LINKS) and not self.busy:
            self.busy = True                    # le champ garde le focus : rien n'est affiché devant avant d'écrire
            threading.Thread(target=self._work, args=(word,), name="cvgen", daemon=True).start()
            return
        if word == "tab":
            self.press("tab")                  # touche seule : le champ garde le focus, rien à demander à CVGEN
            return
        if word == "prépare tout":
            return self._prep_all(t)
        if word == "écris":
            if self.reponse is None:
                self._show("Candidature", ["Pas de réponse prête : dis « question », puis la question"], t)
            elif not self.browser_front():
                self._show("Candidature", ["Le navigateur n'est pas devant : rien n'est écrit"], t)
            else:
                self.typer(self.reponse)
            return
        if word == "aide":
            self._show("Candidature : ce que tu peux dire", HELP_LINES, t, meta=CLOSE_HINT)
            self.show_until = t + HELP_S
            return
        if word == "annule":
            if self.busy:
                self._show("Candidature", ["Patiente : la demande d'avant n'est pas finie"], t)
            elif self.last is None:
                self._show("Candidature", ["Rien à annuler"], t)
            else:
                self._send(word, t, {"offre": self.last[0], "pos": self.last[1]})
            return
        if word in NAV:
            return self._nav(word, t)
        if self.busy:
            self._show("Candidature", ["Patiente : la demande d'avant n'est pas finie"], t)
            return
        self._send(word, t, {"liste": True} if word == "état" and self.offres is None else None)

    def submit_question(self, audio, transcribe):
        """« question » : la phrase enregistrée est transcrite puis envoyée au modèle de CVGEN (fil « cvgen »).
        Seulement boucle principale (l'offre affichée est lue ici)."""
        if self.busy:
            self._q.put(("error", "Patiente : la demande d'avant n'est pas finie"))
            return
        self.busy = True
        o = dict(self.offres[self.i]) if self.offres else None
        self._show("Question", ["Je transcris ta question, puis je prépare une réponse…"
                                + ("" if o else " (sans offre affichée : d'après ton profil seulement)")],
                   self.clock(), self.meta)

        def run():
            try:
                q = " ".join(str(transcribe(audio) or "").split()).strip()
            except Exception:
                log.exception("transcription question")
                q = ""
            if len(q) < 3:
                self._q.put(("error", "Rien compris : redis « question »"))
                return
            self._work("question", {"question": q, "offre": o})
        threading.Thread(target=run, name="cvgen", daemon=True).start()

    def _prep_all(self, t):
        """« prépare tout » : les offres à vérifier pas encore prêtes, l'une après l'autre (CVGEN n'en fait qu'une)."""
        if not self.offres:
            self._show("Candidature", ["Pas de liste ouverte : dis « liste »"], t)
            return
        if self.busy:
            self._card(t, "Patiente : la demande d'avant n'est pas finie")
            return
        todo = [o for o in self.offres if o.get("cvId") and o["id"] != self.preparing
                and (o.get("preparation") or {}).get("etape") != "pret" and self.prep.get(o["id"]) != PREP_STEPS["pret"]]
        if not todo:
            self._card(t, "Rien à préparer : aucune offre avec un CV prêt")
            return
        self.todo = todo
        self._card(t, f"{len(todo)} offre(s) à préparer, l'une après l'autre")
        self._next_prep(t)

    def _next_prep(self, t):
        if self.preparing is not None or self.busy or not self.todo:
            return
        o = self.todo.pop(0)
        self.preparing = o["id"]
        self._send("prépare", t, o)

    def _send(self, word, t, arg=None):
        self.busy = True
        self._show(self.title or "Candidature", (self.lines or [])[:1] + ["Je demande à CVGEN…"], t, self.meta)
        threading.Thread(target=self._work, args=(word, arg), name="cvgen", daemon=True).start()

    def _nav(self, word, t):
        """Mots de la liste : sans liste ouverte, ils le disent ; garde / écarte passent par CVGEN."""
        if not self.offres:
            self._show("Candidature", ["Pas de liste ouverte : dis « liste »"], t)
            return
        if self.busy:
            self._show(self.title, self.lines[:1] + ["Patiente : la demande d'avant n'est pas finie"], t, self.meta)
            return
        o = self.offres[self.i]
        if word in ("suivante", "précédente"):
            j = self.i + (1 if word == "suivante" else -1)
            self.i = j % len(self.offres)
            bout = None
            if len(self.offres) > 1 and j >= len(self.offres):
                bout = "Fin de la liste : retour à la première"
            elif len(self.offres) > 1 and j < 0:
                bout = "Début de la liste : retour à la dernière"
            self._card(t, bout)
        elif word in ("détails", "vérifie"):
            if word == "vérifie" and not o.get("url"):
                self._card(t, "Cette offre n'a pas de lien")
            else:
                self._send(word, t, o)
        elif word == "lien":
            if not o.get("url"):
                self._card(t, "Cette offre n'a pas de lien")
            else:
                if self.open_url is not None:
                    self.open_url(o["url"])
                self._card(t, "Ouverte dans le navigateur")
        elif word == "garde" and o["etat"] != "a-trier":
            self._card(t, "Déjà gardée : son CV est en cours" if o["etat"] == "gardee" else "Déjà gardée : son CV est prêt")
        elif o["etat"] == "gardee" and word in FILES | {"postulé", "prépare", "montre", "relis"}:
            self._card(t, "Son CV est en cours : dis « liste » un peu plus tard")
        elif word == "brouillon" and o["etat"] == "a-trier":
            self._card(t, "Pas encore de CV : dis « garde » d'abord")
        elif word in FILES or word == "postulé":
            if not o.get("cvId"):
                self._card(t, "Pas encore de CV : dis « garde » d'abord")
            elif word == "postulé":
                self._send(word, t, o)
            elif self.files.get(o["id"], {}).get(word):
                self._file(o["id"], word, t)
            else:
                self._send(word, t, o)         # PDF posés par CVGEN, puis collés
        elif word in ("prépare", "montre", "relis") and not o.get("cvId"):
            self._card(t, "Pas encore de CV : dis « garde » d'abord")
        elif word == "prépare":
            if self.preparing is not None:
                self._card(t, "Une autre candidature est en préparation : patiente")
            else:
                self.preparing = o["id"]
                self._send(word, t, o)
        elif word in ("montre", "relis"):
            if word == "relis":
                url, note = PAGES["jury"].format(cv=o["cvId"]), "Relecture ouverte dans le navigateur"
            elif ((o.get("preparation") or {}).get("etape") == "pret"
                  or self.prep.get(o["id"]) == PREP_STEPS["pret"]):
                url, note = PAGES["pdf_cv"].format(id=o["id"]), "PDF du CV ouvert"
            else:
                url, note = PAGES["atelier"].format(cv=o["cvId"]), "Pas encore préparé : atelier ouvert"
            if self.open_url is not None:
                self.open_url(BASE + url)
            self._card(t, note)
        else:
            self._send(word, t, o)

    def _file(self, oid, word, t):
        """Écrit le chemin du PDF dans la fenêtre « Choisir un fichier » (une fenêtre de Windows, pas le site)."""
        path = self.files.get(oid, {}).get(word)
        if not path:
            self._card(t, f"Pas de PDF {'du CV' if word == 'cv' else 'de la lettre'} : dis « prépare » d'abord")
        elif self.fg_class() != FILE_DIALOG:
            self._card(t, "Ouvre d'abord la fenêtre « Choisir un fichier » du site, puis redis-le")
        else:
            self.typer(path, enter=True)
            self._card(t, f"{'CV' if word == 'cv' else 'Lettre'} joint{'' if word == 'cv' else 'e'}")
