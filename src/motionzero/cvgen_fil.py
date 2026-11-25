"""« iris candidature » : Iris pilote CVGEN (plan-cvgen.md), sans rien changer à CVGEN : méthodes de Candidature (FilMixin, découpé de cvgen.py, #52)."""
import logging
from pathlib import Path

from .cvgen_base import BASE, CvgenError, FIELDS, FILES, LINKS, PREP_MAX_S, PREP_POLL_S, START_WAIT_S, details_lines, iris_says, profile_value, relances_lines, vivacite_text
from .cvgen_base2 import a_parcourir, call, clean_answer, draft_eml, offer_email, question_prompt, summary

log = logging.getLogger("motionzero.cvgen")


class FilMixin:

    # ---- fil « cvgen » ----
    def _ensure(self):
        """CVGEN joignable, lancé au besoin. Lève CvgenError sinon."""
        try:
            return call("sante", self.http)
        except CvgenError:
            pass
        self._q.put(("wait", "CVGEN démarre…"))
        self.launch()
        end = self.clock() + START_WAIT_S
        while self.clock() < end:
            self.sleep(1.0)
            try:
                return call("sante", self.http)
            except CvgenError:
                continue
        raise CvgenError("CVGEN n'a pas démarré")

    def _follow(self, oid):
        """Suit la préparation (lancée en fond par CVGEN) jusqu'à « prêt » ou « erreur »."""
        end = self.clock() + PREP_MAX_S
        last = None
        while self.clock() < end:
            self.sleep(PREP_POLL_S)
            try:
                prep = (call("offre", self.http, id=oid) or {}).get("preparation") or {}
            except CvgenError:
                continue                         # CVGEN occupé ou relancé : on réessaie
            key = (prep.get("etape"), prep.get("libelle"))
            if key != last:
                self._q.put(("prep", oid, prep))
                last = key
            if prep.get("etape") in ("pret", "erreur"):
                return
        self._q.put(("prep", oid, {"etape": "erreur", "erreur": "trop long : regarde dans CVGEN"}))

    def _status(self):
        agent, compte = call("agent", self.http), call("compte", self.http)
        self._q.put(("chiffres", agent, compte))
        return summary(agent, compte, call("preparation", self.http))

    def _work(self, word, arg=None):
        try:
            self._ensure()
            if word == "cherche":
                running = call("agent", self.http).get("etat") in ("en-cours", "arret-demande")
                call("arreter" if running else "demarrer", self.http)
                title = "Recherche arrêtée" if running else "Recherche lancée"
            elif word == "offres":
                if self.open_url is not None:
                    self.open_url(BASE + "/")
                title = "Offres ouvertes"
            elif word == "liste":
                self._q.put(("chiffres", None, call("compte", self.http)))
                self._q.put(("liste", a_parcourir(call("offres", self.http))))
                return
            elif word == "prépare":
                call("preparer", self.http, {}, id=arg["id"])
                self._q.put(("prep", arg["id"], {"etape": "attente"}))
                self._follow(arg["id"])
                return
            elif word in FIELDS or word in LINKS:
                if self.profile is None:
                    self.profile = call("profil", self.http)
                self._q.put(("field", word, profile_value(self.profile, word)))
                return
            elif word in FILES:
                r = call("en_cours", self.http, {}, id=arg["id"]) or {}
                self._q.put(("files", arg["id"], {k: r.get(k) for k in FILES}, word))
                return
            elif word == "postulé":
                call("maj_offre", self.http, {"etat": "postulee"}, id=arg["id"])
                self._q.put(("verdict", arg["id"], word))
                return
            elif word == "annule":
                call("maj_offre", self.http, {"etat": arg["offre"]["etat"]}, id=arg["offre"]["id"])
                self._q.put(("annule", arg["offre"], arg["pos"]))
                return
            elif word == "détails":
                o = call("offre", self.http, id=arg["id"]) or {}
                self._q.put(("long", f"Annonce : {arg.get('poste') or 'offre'}", details_lines(o.get("texte"))))
                return
            elif word == "vérifie":
                self._q.put(("note", arg["id"], vivacite_text(call("verifier_lien", self.http, {}, id=arg["id"]))))
                return
            elif word == "question":
                question, o = arg["question"], arg.get("offre")
                if self.profile is None:
                    self.profile = call("profil", self.http)
                texte = (call("offre", self.http, id=o["id"]) or {}).get("texte") if o else None
                r = call("llm", self.http, {"messages": [{"role": "user", "content":
                                                           question_prompt(question, o, self.profile, texte)}]})
                self._q.put(("reponse", question, clean_answer((r or {}).get("content"))))
                return
            elif word == "brouillon":
                o = arg
                to = offer_email((call("offre", self.http, id=o["id"]) or {}).get("texte"))
                if to is None:
                    self._q.put(("note", o["id"], "Pas d'adresse e-mail dans l'annonce : postule sur le site"))
                    return
                r = call("en_cours", self.http, {}, id=o["id"]) or {}
                pdf = [r[k] for k in ("cv", "lettre") if r.get(k)]
                if not pdf:
                    self._q.put(("note", o["id"], "Pas de PDF : dis « prépare » d'abord"))
                    return
                if self.profile is None:
                    self.profile = call("profil", self.http)
                import tempfile
                path = Path(tempfile.gettempdir()) / "iris-candidature.eml"
                path.write_bytes(draft_eml(to, o, self.profile, pdf))
                self._q.put(("brouillon", o["id"], str(path), to))
                return
            elif word == "relances":
                import datetime as _dt
                self._q.put(("long", "Candidatures envoyées",
                             relances_lines(call("postulees", self.http), _dt.date.today())))
                return
            elif word in ("garde", "écarte"):
                etat = "gardee" if word == "garde" else "ecartee"
                call("maj_offre", self.http, {"etat": etat}, id=arg["id"])
                self._q.put(("verdict", arg["id"], word))
                return
            else:
                title = "Candidature"
            lines = self._status()
            if (arg or {}).get("liste"):           # ouverture du mode : la première offre tout de suite
                self._q.put(("liste", a_parcourir(call("offres", self.http))))
                oid = (call("preparation", self.http) or {}).get("offreId")
                if oid:                            # Iris relancée pendant une préparation : on reprend le suivi
                    self._q.put(("prep", oid, {"etape": "attente", "libelle": "reprise du suivi"}))
                    self._q.put(("ok", title, lines))
                    self._follow(oid)
                    return
            self._q.put(("ok", title, lines))
        except CvgenError as e:
            log.warning("cvgen %s : %s", word, e)
            if word == "prépare":
                self._q.put(("prep", arg["id"], {"etape": "erreur", "erreur": str(e)}))
            self._q.put(("error", iris_says(e)))
        except Exception as e:                 # jamais d'exception qui remonte : la carte le dit
            log.exception("cvgen")
            self._q.put(("error", f"Erreur inattendue ({type(e).__name__})"))
