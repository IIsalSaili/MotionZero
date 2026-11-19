"""« iris candidature » : Iris pilote CVGEN (plan-cvgen.md), sans rien changer à CVGEN.

Iris appelle les adresses que les boutons de CVGEN appellent déjà : pour CVGEN, c'est comme un clic. Toutes ces
adresses sont ici (ROUTES), et un test vérifie qu'elles existent encore dans server.mjs.

Les appels HTTP tournent dans le fil « cvgen » ; ils ne rendent compte que par la queue `_q`, lue par events()
dans la boucle principale (jamais Core ailleurs).
"""
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger("motionzero.cvgen")

BASE = "http://127.0.0.1:3000"
DIR = Path.home() / "Desktop" / "CVGEN"
TIMEOUT_S = 8
START_WAIT_S = 20.0      # CVGEN lancé par Iris : temps laissé pour qu'il réponde
SHOW_S = 15.0            # la carte reste ce temps
CLOSE_HINT = "« candidature » pour quitter"

# Adresses de CVGEN utilisées par Iris (mêmes que celles des boutons). Vérifiées par tests/test_cvgen.py.
ROUTES = {
    "sante": ("GET", "/api/health"),
    "agent": ("GET", "/api/agent"),
    "demarrer": ("POST", "/api/agent/demarrer"),
    "arreter": ("POST", "/api/agent/arreter"),
    "compte": ("GET", "/api/offres/compte"),
    "preparation": ("GET", "/api/preparation"),
    "offres": ("GET", "/api/offres"),
    "maj_offre": ("PATCH", "/api/offres/{id}"),     # garder / écarter : comme les boutons de la page Offres
    "offre": ("GET", "/api/offres/{id}"),           # suivi de la préparation (offre.preparation.etape)
    "preparer": ("POST", "/api/offres/{id}/preparer"),   # « Préparer la candidature » : CV composé, PDF, pièces
    "profil": ("GET", "/api/profile"),              # nom, mail, téléphone… lus à la demande, jamais recopiés
    "en_cours": ("POST", "/api/offres/{id}/en-cours"),   # PDF de l'offre dans le dossier fixe, et leurs chemins
}
# Pages ouvertes dans le navigateur (vérifiées par les tests : fichiers de public/ et route des PDF)
PAGES = {"atelier": "/generate.html?id={cv}", "jury": "/jury.html?id={cv}",
         "pdf_cv": "/api/offres/{id}/pdf/cv?voir=1"}
PREP_POLL_S = 3.0
PREP_MAX_S = 900.0       # au-delà, Iris arrête de suivre (CVGEN, lui, continue)
PREP_STEPS = {"attente": "en attente", "cv": "Iris compose le CV…", "pdf-cv": "PDF du CV…",
              "pret": "Prêt : CV et pièces en PDF", "erreur": "Échec"}

# Mots du mode (sans « iris » tant qu'il est allumé). Tous présents dans le modèle Vosk (vérifié le 17/11).
WORDS = {"cherche": "lance ou arrête la recherche",
         "état": "où en est CVGEN",
         "offres": "la page des offres",
         # phase 2 : une offre à la fois sur la carte
         "liste": "les offres à trier puis à vérifier, une par une",
         "suivante": "offre suivante", "précédente": "offre précédente",
         "garde": "garder l'offre (CVGEN prépare le CV)", "écarte": "écarter l'offre",
         "lien": "l'offre sur son site",
         # phase 3 : le CV et les pièces
         "prépare": "CV composé, PDF et pièces prêts (comme « Préparer la candidature »)",
         "montre": "le PDF prêt, sinon l'atelier du CV",
         "relis": "la relecture par le jury",
         "aide": "toutes les commandes du mode, par étape",
         # phase 4 : remplir le formulaire du site, un champ à la fois, quand tu le demandes
         "mail": "écrit ton e-mail dans le champ choisi", "téléphone": "ton téléphone", "prénom": "ton prénom",
         "nom": "ton nom", "ville": "ta ville", "github": "ton lien GitHub", "linkedin": "ton lien LinkedIn",
         "cv": "le PDF du CV, dans la fenêtre « Choisir un fichier »",
         "lettre": "le PDF de la lettre, dans la fenêtre « Choisir un fichier »",
         "postulé": "candidature notée envoyée (relance à J+7)"}
FIELDS = {"mail": "email", "téléphone": "telephone", "prénom": "prenom", "nom": "nom", "ville": "ville"}
LINKS = {"github", "linkedin"}
FILES = {"cv", "lettre"}
FILE_DIALOG = "#32770"   # classe Windows des fenêtres « Ouvrir » / « Choisir un fichier »
HELP_S = 40.0
HELP_LINES = [
    "Recherche : « cherche » (lance / arrête) · « état » · « offres » (la page)",
    "Tri : « liste », puis « suivante » · « précédente » · « garde » · « écarte »",
    "CV : « prépare » (CV et pièces en PDF) · « montre » (le PDF) · « relis » (jury)",
    "Postuler : « lien » ouvre l'offre sur son site ; clique dans un champ, puis dis",
    "  « mail » · « téléphone » · « prénom » · « nom » · « ville » · « github » · « linkedin »",
    "  « cv » / « lettre » dans la fenêtre « Choisir un fichier » ; « postulé » une fois envoyé",
    "Souris : « souris », puis « clic » · « scroll »… · « stop » arrête tout",
    "Quitter le mode : « candidature »",
]
NAV = {"suivante", "précédente", "garde", "écarte", "lien", "prépare", "montre", "relis", "cv", "lettre",
       "postulé"}   # liste ouverte
# à trier d'abord (verdict à donner), puis à vérifier (CV prêt) ; meilleure note en tête
A_PARCOURIR = {"a-trier": "à trier", "generee": "à vérifier"}


def next_hint(o, prep_line=None, preparing=False):
    """Bas de la carte : les 3 ou 4 mots utiles à l'étape de l'offre affichée (court : sinon illisible)."""
    if o is None:
        return "« liste » · « cherche » · « aide »"
    if o.get("etat") == "a-trier":
        return "« garde » · « écarte » · « suivante » · « aide »"
    pret = prep_line == PREP_STEPS["pret"] or (o.get("preparation") or {}).get("etape") == "pret"
    if pret:
        return "« lien » · « mail » · « cv » · « postulé » · « aide »"
    if preparing:
        return "préparation en cours · « suivante » · « aide »"
    return "« prépare » · « montre » · « écarte » · « aide »"


def profile_value(profile, word):
    """Texte à écrire pour « mail », « github »… ; None s'il manque au profil. Pur : testable."""
    ident = (profile or {}).get("identity") or {}
    if word in FIELDS:
        v = str(ident.get(FIELDS[word]) or "").strip()
        return v or None
    for lien in ident.get("liens") or []:
        url = str((lien or {}).get("url") or "") if isinstance(lien, dict) else str(lien)
        if word in url.lower() or word in str((lien or {}).get("label", "") if isinstance(lien, dict) else "").lower():
            return url or None
    return None


def _fg_class():
    import ctypes
    buf = ctypes.create_unicode_buffer(64)
    ctypes.windll.user32.GetClassNameW(ctypes.windll.user32.GetForegroundWindow(), buf, 64)
    return buf.value


def _type(text, enter=False):
    from .typer import press, type_text
    type_text(text)
    if enter:
        press("enter")


def iris_says(msg):
    """Messages de CVGEN montrés par Iris : jamais « Claude » (Iris parle en son nom)."""
    return str(msg).replace("Claude", "Iris")


def prep_text(prep):
    """Ligne d'avancement de la préparation d'une offre. Pur : testable."""
    prep = prep or {}
    etape = prep.get("etape")
    if etape == "erreur":
        return "Échec : " + iris_says(prep.get("erreur") or "raison inconnue")
    if etape in PREP_STEPS:
        return "Préparation : " + PREP_STEPS[etape] if etape != "pret" else PREP_STEPS["pret"]
    return "Préparation : " + (prep.get("libelle") or "pièces…")

ETATS = (("verif", "à vérifier"), ("tri", "à trier"), ("ok", "postulées"), ("ref", "refusées"))


class CvgenError(Exception):
    """Message court, affichable tel quel."""


def _http(method, path, body=None, base=BASE, timeout=TIMEOUT_S):
    data = json.dumps(body or {}).encode("utf-8") if method != "GET" else None
    req = urllib.request.Request(base + path, method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error")
        except (ValueError, OSError):
            msg = None
        raise CvgenError(msg or f"CVGEN a refusé ({e.code})") from None
    except (OSError, ValueError):
        raise CvgenError("CVGEN ne répond pas") from None


def _launch(root=DIR):
    """Démarre `node server.mjs` sans fenêtre, détaché d'Iris (il survit à une relance d'Iris)."""
    node = shutil.which("node")
    if node is None or not (Path(root) / "server.mjs").exists():
        raise CvgenError("CVGEN introuvable sur ce PC")
    flags = 0x08000000 | 0x00000200   # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([node, "server.mjs"], cwd=str(root), creationflags=flags if os.name == "nt" else 0,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def call(name, http=_http, body=None, **ids):
    method, path = ROUTES[name]
    path = path.format(**{k: urllib.parse.quote(str(v), safe="") for k, v in ids.items()})
    return http(method, path, body) if body is not None else http(method, path)


def a_parcourir(offres):
    """Offres à trier puis à vérifier, meilleure note en tête. Pur : testable."""
    def note(o):
        return (o.get("evaluation") or {}).get("globale") or 0
    out = [o for o in offres or [] if o.get("etat") in A_PARCOURIR]
    return sorted(out, key=lambda o: (list(A_PARCOURIR).index(o["etat"]), -note(o)))


def fmt_note(v):
    if not isinstance(v, (int, float)):
        return "?"
    return (f"{v:.1f}".rstrip("0").rstrip(".")).replace(".", ",")


def card(offres, i):
    """(titre, lignes) de l'offre i. Pur : testable."""
    if not offres:
        return "Aucune offre à trier ni à vérifier", ["« cherche » pour en trouver"]
    o = offres[i]
    ev = o.get("evaluation") or {}
    total = sum(1 for x in offres if x["etat"] == o["etat"])
    k = sum(1 for x in offres[:i + 1] if x["etat"] == o["etat"])
    title = f"Offre {k} / {total} {A_PARCOURIR[o['etat']]} · {fmt_note(ev.get('globale'))} / 5"
    lines = [f"{o.get('poste') or 'Poste ?'} · {o.get('entreprise') or 'entreprise ?'}"]
    if ev.get("verdict"):
        lines.append(f"{ev['verdict']} ({o.get('source') or 'site ?'})")
    axes = [a for a in ev.get("axes") or [] if isinstance(a.get("note"), (int, float))]
    if axes:
        fort, faible = max(axes, key=lambda a: a["note"]), min(axes, key=lambda a: a["note"])
        lines.append(f"+ {fort.get('libelle')} : {fort.get('detail', '')}"[:110])
        if faible is not fort:
            lines.append(f"- {faible.get('libelle')} : {faible.get('detail', '')}"[:110])
    return title, lines


def summary(agent, compte, prep):
    """Lignes de la carte « état ». Pur : testable."""
    etat = (agent or {}).get("etat")
    lines = ["Recherche en cours" if etat == "en-cours" else
             "Recherche en train de s'arrêter" if etat == "arret-demande" else "Recherche arrêtée"]
    counts = [f"{(compte or {}).get(k, 0)} {lbl}" for k, lbl in ETATS if (compte or {}).get(k)]
    lines.append(" · ".join(counts) if counts else "Aucune offre en attente")
    if (prep or {}).get("offreId"):
        lines.append("Une candidature est en préparation")
    msg = (agent or {}).get("message")
    if msg:
        lines.append(str(msg)[:80])
    return lines


class Candidature:
    def __init__(self, http=_http, launch=_launch, open_url=None, clock=time.monotonic, sleep=time.sleep,
                 typer=_type, fg_class=_fg_class):
        self.http, self.launch, self.open_url = http, launch, open_url
        self.typer, self.fg_class = typer, fg_class
        self.clock, self.sleep = clock, sleep
        self._q = queue.Queue()
        self.busy = False
        self.title = self.lines = self.meta = None
        self.show_until = -1e9
        self.offres, self.i = None, 0     # liste parcourue (None : pas ouverte) ; seulement boucle principale
        self.preparing = None              # id de l'offre en préparation (une à la fois, comme CVGEN)
        self.prep = {}                     # id -> dernière ligne d'avancement
        self.files = {}                    # id -> {"cv": chemin, "lettre": chemin} (dossier fixe de CVGEN)

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
        return summary(call("agent", self.http), call("compte", self.http), call("preparation", self.http))

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
                self._q.put(("liste", a_parcourir(call("offres", self.http))))
                return
            elif word == "prépare":
                call("preparer", self.http, {}, id=arg["id"])
                self._q.put(("prep", arg["id"], {"etape": "attente"}))
                self._follow(arg["id"])
                return
            elif word in FIELDS or word in LINKS:
                self._q.put(("field", word, profile_value(call("profil", self.http), word)))
                return
            elif word in FILES:
                r = call("en_cours", self.http, {}, id=arg["id"]) or {}
                self._q.put(("files", arg["id"], {k: r.get(k) for k in FILES}, word))
                return
            elif word == "postulé":
                call("maj_offre", self.http, {"etat": "postulee"}, id=arg["id"])
                self._q.put(("verdict", arg["id"], word))
                return
            elif word in ("garde", "écarte"):
                etat = "gardee" if word == "garde" else "ecartee"
                call("maj_offre", self.http, {"etat": etat}, id=arg["id"])
                self._q.put(("verdict", arg["id"], word))
                return
            else:
                title = "Candidature"
            self._q.put(("ok", title, self._status()))
        except CvgenError as e:
            if word == "prépare":
                self._q.put(("prep", arg["id"], {"etape": "erreur", "erreur": str(e)}))
            self._q.put(("error", iris_says(e)))
        except Exception as e:                 # jamais d'exception qui remonte : la carte le dit
            log.exception("cvgen")
            self._q.put(("error", f"Erreur inattendue ({type(e).__name__})"))

    # ---- boucle principale ----
    def ask(self, word, t):
        if (word in FIELDS or word in LINKS) and not self.busy:
            self.busy = True                    # le champ garde le focus : rien n'est affiché devant avant d'écrire
            threading.Thread(target=self._work, args=(word,), name="cvgen", daemon=True).start()
            return
        if word == "aide":
            self._show("Candidature : ce que tu peux dire", HELP_LINES, t, meta=CLOSE_HINT)
            self.show_until = t + HELP_S
            return
        if word in NAV:
            return self._nav(word, t)
        if self.busy:
            self._show("Candidature", ["Patiente : la demande d'avant n'est pas finie"], t)
            return
        self._send(word, t)

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
            self.i = (self.i + (1 if word == "suivante" else -1)) % len(self.offres)
            self._card(t)
        elif word == "lien":
            if not o.get("url"):
                self._card(t, "Cette offre n'a pas de lien")
            else:
                if self.open_url is not None:
                    self.open_url(o["url"])
                self._card(t, "Ouverte dans le navigateur")
        elif word == "garde" and o["etat"] != "a-trier":
            self._card(t, "Déjà gardée : son CV est prêt")
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

    def _card(self, t, note=None):
        title, lines = card(self.offres or [], self.i)
        if self.offres and self.offres[self.i]["id"] in self.prep:
            lines.append(self.prep[self.offres[self.i]["id"]])
        o = self.offres[self.i] if self.offres else None
        hint = next_hint(o, self.prep.get(o["id"]) if o else None, o is not None and self.preparing == o["id"])
        self._show(title, lines + ([note] if note else []), t, meta=hint)

    def _show(self, title, lines, t, meta=None):
        self.title, self.lines = title, list(lines)
        self.meta = meta or next_hint(None)
        self.show_until = t + SHOW_S

    def events(self, core, t):
        while True:
            try:
                msg = self._q.get_nowait()
            except queue.Empty:
                break
            if msg[0] == "wait":
                self._show("Candidature", [msg[1]], t)
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
                else:
                    self.typer(value)
                    core.last_gesture = (f"CANDIDATURE : {word.upper()} ECRIT", t)
            elif msg[0] == "files":
                self.busy = False
                _, oid, paths, word = msg
                self.files[oid] = paths
                self._file(oid, word, t)
            elif msg[0] == "verdict":
                self.busy = False
                _, oid, word = msg
                self.offres = [o for o in self.offres or [] if o["id"] != oid]
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
                if self.offres and self.offres[self.i]["id"] == oid:
                    self._card(t)              # l'offre affichée : la carte suit l'avancement
                core.last_gesture = (f"CANDIDATURE : {self.prep[oid]}".upper()[:60], t)
            elif msg[0] == "error":
                self.busy = False
                self._show("Candidature impossible", [msg[1]], t)
                core.last_gesture = (f"CANDIDATURE : {msg[1]}".upper()[:60], t)
        return []

    def actions(self, acts, core, t):
        rest = []
        for a in acts:
            if a[0] == "cand":
                self.ask(a[1], t)
            elif a[0] == "cand_off":
                self.lines, self.offres = None, None
            elif a[0] in ("rappel_merci", "ask_close") and self.lines is not None:
                self.lines = None              # « iris merci » / « iris ferme » : la carte se ferme
                rest.append(a)
            else:
                rest.append(a)
        return rest

    def state(self, t):
        if self.lines is None or (t >= self.show_until and not self.busy):
            return None
        return {"title": self.title, "lines": list(self.lines), "meta": self.meta}
