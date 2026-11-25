"""« iris candidature » : Iris pilote CVGEN (plan-cvgen.md), sans rien changer à CVGEN.

Iris appelle les adresses que les boutons de CVGEN appellent déjà : pour CVGEN, c'est comme un clic. Toutes ces
adresses sont ici (ROUTES), et un test vérifie qu'elles existent encore dans server.mjs.

Les appels HTTP tournent dans le fil « cvgen » ; ils ne rendent compte que par la queue `_q`, lue par events()
dans la boucle principale (jamais Core ailleurs).
"""
import logging
import queue
import time
from .cvgen_base import (fmt_note, A_PARCOURIR, BASE, BROWSERS, BUSY_MAX_S, CLOSE_HINT, CONTRATS, CvgenError, DETAILS_MAX, DIR, ETATS, EXTRA, FIELDS, FILES, FILE_DIALOG, HELP_LINES, HELP_S, LINKS, NAV, PAGES, PREP_MAX_S, PREP_POLL_S, PREP_STEPS, RELANCE_J, ROUTES, ROUTE_TIMEOUT_S, SHORT, SHOW_S, START_WAIT_S, TILES, TIMEOUT_S, WORDS, _COMMUNS, _browser_front, _fg_class, _press, _type, details_lines, fmt_age, fmt_contrat, hint_words, iris_says, next_hint, offer_view, prep_text, profile_value, relances_lines, step_of, vivacite_text)  # noqa: F401
from .cvgen_base2 import (PRIVE, PROMPT_QUESTION, QUESTION_MAX, _http, _launch, a_parcourir, call, card, clean_answer, draft_eml, offer_email, question_prompt, summary)  # noqa: F401
from .cvgen_fil import FilMixin
from .cvgen_evenements import EvenementsMixin
from .cvgen_commandes import CommandesMixin

log = logging.getLogger("motionzero.cvgen")


class Candidature(FilMixin, EvenementsMixin, CommandesMixin):
    def __init__(self, http=_http, launch=_launch, open_url=None, clock=time.monotonic, sleep=time.sleep,
                 typer=_type, fg_class=_fg_class, press=_press, browser_front=_browser_front):
        self.http, self.launch, self.open_url = http, launch, open_url
        self.typer, self.fg_class, self.press, self.browser_front = typer, fg_class, press, browser_front
        self.profile = None                # profil CVGEN lu une fois par ouverture du mode (en mémoire seulement)
        self.todo = []                     # « prépare tout » : offres qui attendent leur tour
        self.reponse = None                # réponse proposée à la dernière question libre (#46)
        self._busy_t = None                # début de la demande en cours (garde-fou BUSY_MAX_S)
        self.clock, self.sleep = clock, sleep
        self._q = queue.Queue()
        self.busy = False
        self.title = self.lines = self.meta = None
        self.show_until = -1e9
        self.offres, self.i = None, 0     # liste parcourue (None : pas ouverte) ; seulement boucle principale
        self.preparing = None              # id de l'offre en préparation (une à la fois, comme CVGEN)
        self.prep = {}                     # id -> dernière ligne d'avancement
        self.files = {}                    # id -> {"cv": chemin, "lettre": chemin} (dossier fixe de CVGEN)
        self.view = "msg"                  # le panneau montre l'offre (« card ») ou un message (« msg »)
        self.note = None                   # retour de la dernière commande, sous l'offre
        self.compte = self.agent = None    # derniers chiffres et état de la recherche reçus de CVGEN
        self.last = None                   # (offre avant verdict, position) : pour « annule »

    def _card(self, t, note=None):
        title, lines = card(self.offres or [], self.i)
        if self.offres and self.offres[self.i]["id"] in self.prep:
            lines.append(self.prep[self.offres[self.i]["id"]])
        o = self.offres[self.i] if self.offres else None
        hint = next_hint(o, self.prep.get(o["id"]) if o else None, o is not None and self.preparing == o["id"])
        self._show(title, lines + ([note] if note else []), t, meta=hint)
        self.view, self.note = ("card" if o is not None else "msg"), note

    def _show(self, title, lines, t, meta=None):
        self.title, self.lines = title, list(lines)
        self.meta = meta or next_hint(None)
        self.show_until = t + SHOW_S
        self.view = "msg"

    def actions(self, acts, core, t):
        rest = []
        for a in acts:
            if a[0] == "cand":
                try:
                    self.ask(a[1], t)
                except Exception:                 # frappe, ouverture d'un lien… : dit, jamais bloquant
                    log.exception("cvgen : %s", a[1])
                    self.busy = False
                    self._show("Candidature", [f"« {a[1]} » n'a pas marché : redis-le"], t)
            elif a[0] == "cand_off":
                self.lines, self.offres = None, None
                self.profile, self.todo, self.reponse = None, [], None   # profil relu à la prochaine ouverture
            elif a[0] in ("rappel_merci", "ask_close") and self.lines is not None:
                self.lines = None              # « iris merci » / « iris ferme » : la carte se ferme
                rest.append(a)
            else:
                rest.append(a)
        return rest

    def panel(self, t, today=None):
        """Panneau de droite (maquette A1), affiché tant que le mode est allumé. Seulement boucle principale."""
        import datetime as _dt
        today = today or _dt.date.today()
        o = self.offres[self.i] if self.offres else None
        msg = None
        if self.view == "msg" and self.lines is not None and (t < self.show_until or self.busy or o is None):
            msg = {"title": self.title, "lines": list(self.lines)}
        elif o is None:
            msg = {"title": "Candidature", "lines": ["« liste » pour parcourir les offres"]}
        etat = (self.agent or {}).get("etat")
        status = ("Recherche en cours" if etat == "en-cours" else "Recherche en train de s'arrêter"
                  if etat == "arret-demande" else "Recherche arrêtée" if self.agent else "")
        compte = self.compte or {}
        tiles = [(int(compte.get(k) or 0), lbl, o is not None and o["etat"] == e) for k, lbl, e in TILES]
        nxt = []
        if self.offres and len(self.offres) > 1:
            for j in range(1, min(3, len(self.offres))):
                x = self.offres[(self.i + j) % len(self.offres)]
                nxt.append((f"{x.get('poste') or 'Poste ?'} · {x.get('entreprise') or '?'}",
                            fmt_note((x.get("evaluation") or {}).get("globale"))))
        prep_line = self.prep.get(o["id"]) if o else None
        preparing = o is not None and self.preparing == o["id"]
        words = hint_words(o, prep_line, preparing)
        return {"status": status, "tiles": tiles, "msg": msg, "next": nxt, "busy": self.busy,
                "words": [(w, SHORT[w]) for w in words], "extra": EXTRA[step_of(o, prep_line, preparing)],
                "offer": offer_view(self.offres, self.i, today, prep_line) if o is not None and msg is None else None,
                "note": self.note if msg is None else None,
                "foot": "« candidature » : quitter le mode"}

    def state(self, t):
        if self.lines is None or (t >= self.show_until and not self.busy):
            return None
        return {"title": self.title, "lines": list(self.lines), "meta": self.meta}
