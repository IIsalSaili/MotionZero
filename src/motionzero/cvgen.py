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
    "postulees": ("GET", "/api/postulees"),         # journal des candidatures (page « Postulées »)
    "verifier_lien": ("POST", "/api/offres/{id}/verifier-lien"),   # l'annonce est-elle encore en ligne ?
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
         "postulé": "candidature notée envoyée (relance à J+7)",
         # 21/11 : ce qu'il faut pour chercher depuis Iris sans ouvrir CVGEN
         "annule": "annule le dernier « garde », « écarte » ou « postulé »",
         "détails": "le texte de l'annonce dans le panneau",
         "vérifie": "l'annonce est-elle encore en ligne",
         "relances": "les candidatures envoyées et celles à relancer",
         "adresse": "ton adresse", "code postal": "ton code postal", "pays": "ton pays",
         "naissance": "ta date de naissance", "disponibilité": "ta disponibilité",
         "salaire": "ton salaire souhaité", "permis": "ton permis",
         "tab": "passe au champ suivant du formulaire",
         "prépare tout": "prépare l'une après l'autre toutes les offres dont le CV est prêt"}
FIELDS = {"mail": "email", "téléphone": "telephone", "prénom": "prenom", "nom": "nom", "ville": "ville",
          "adresse": "adresse", "code postal": "code_postal", "pays": "pays", "naissance": "date_naissance",
          "disponibilité": "disponibilite", "salaire": "salaire_souhaite", "permis": "permis"}   # profil CVGEN
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}   # on n'écrit que là (#61)
LINKS = {"github", "linkedin"}
FILES = {"cv", "lettre"}
FILE_DIALOG = "#32770"   # classe Windows des fenêtres « Ouvrir » / « Choisir un fichier »
HELP_S = 40.0
HELP_LINES = [
    "Recherche : « cherche » (lance / arrête) · « état » · « offres » (la page)",
    "Tri : « liste », puis « suivante » · « précédente » · « garde » · « écarte »",
    "CV : « prépare » (CV et pièces en PDF) · « prépare tout » · « montre » (le PDF) · « relis » (jury)",
    "Postuler : « lien » ouvre l'offre sur son site ; clique dans un champ, puis dis",
    "  « mail » · « téléphone » · « prénom » · « nom » · « ville » · « github » · « linkedin »",
    "  « adresse » · « code postal » · « pays » · « naissance » · « disponibilité » · « salaire » · « permis »",
    "  « tab » : champ suivant",
    "  « cv » / « lettre » dans la fenêtre « Choisir un fichier » ; « postulé » une fois envoyé",
    "Annonce : « détails » (son texte) · « vérifie » (encore en ligne ?) · « annule » (dernier verdict)",
    "Suivi : « relances » (candidatures envoyées, à relancer)",
    "Souris : « souris », puis « clic » · « scroll »… · « stop » arrête tout",
    "Quitter le mode : « candidature »",
]
NAV = {"suivante", "précédente", "garde", "écarte", "lien", "prépare", "montre", "relis", "cv", "lettre",
       "postulé", "détails", "vérifie"}   # liste ouverte
RELANCE_J = 7
DETAILS_MAX = 1400       # caractères de l'annonce montrés par « détails »
# à trier d'abord (verdict à donner), puis à vérifier (CV prêt) ; meilleure note en tête
A_PARCOURIR = {"a-trier": "à trier", "generee": "à vérifier", "gardee": "CV en cours"}


def next_hint(o, prep_line=None, preparing=False):
    """Bas de la carte : les 3 ou 4 mots utiles à l'étape de l'offre affichée (court : sinon illisible)."""
    if o is None:
        return "« liste » · « cherche » · « aide »"
    if o.get("etat") == "a-trier":
        return "« garde » · « écarte » · « suivante » · « aide »"
    if o.get("etat") == "gardee":
        return "CV en cours · « suivante » · « écarte » · « aide »"
    pret = prep_line == PREP_STEPS["pret"] or (o.get("preparation") or {}).get("etape") == "pret"
    if pret:
        return "« lien » · « mail » · « cv » · « postulé » · « aide »"
    if preparing:
        return "préparation en cours · « suivante » · « aide »"
    return "« prépare » · « montre » · « écarte » · « aide »"


def hint_words(o, prep_line=None, preparing=False):
    """Les mots utiles à l'étape de l'offre affichée, le plus probable en tête (boutons du panneau). Pur."""
    if o is None:
        return ["liste", "cherche", "état", "offres"]
    if o.get("etat") == "a-trier":
        return ["garde", "écarte", "suivante", "lien"]
    if o.get("etat") == "gardee":
        return ["suivante", "précédente", "écarte", "lien"]
    pret = prep_line == PREP_STEPS["pret"] or (o.get("preparation") or {}).get("etape") == "pret"
    if pret:
        return ["lien", "mail", "cv", "postulé"]
    if preparing:
        return ["suivante", "précédente", "lien", "relis"]
    return ["prépare", "montre", "écarte", "suivante"]


# Ce que fait chaque mot, tel qu'on le voit à l'écran (panneau : sous le mot, court)
SHORT = {"liste": "affiche les offres une par une", "cherche": "lance ou arrête la recherche d'offres",
         "état": "met à jour les chiffres", "offres": "ouvre la page des offres de CVGEN",
         "garde": "je la veux : CVGEN fait le CV", "écarte": "pas pour moi : retirée de la liste",
         "suivante": "passe à l'offre d'après", "précédente": "revient à l'offre d'avant",
         "lien": "ouvre l'annonce sur son site", "prépare": "fabrique le CV et la lettre en PDF",
         "montre": "ouvre le PDF de ton CV", "relis": "ouvre la relecture de ton CV",
         "mail": "écrit ton e-mail dans le champ cliqué", "tab": "passe au champ suivant",
         "prépare tout": "prépare toutes les offres à vérifier", "cv": "joint le PDF du CV au site",
         "lettre": "joint le PDF de la lettre au site", "postulé": "marque envoyée, relance à J+7"}
_COMMUNS = [("détails · vérifie", "texte de l'annonce · encore en ligne ?"),
            ("annule · relances", "dernier verdict · candidatures envoyées")]
# Les autres mots de l'étape, sous les boutons : (mots, ce qu'ils font)
EXTRA = {"aucune": [("relances", "candidatures envoyées, celles à relancer"),
                    ("annule", "annule le dernier verdict")],
         "tri": [("précédente", "revient à l'offre d'avant")] + _COMMUNS,
         "cv": [("relis · précédente", "relecture de ton CV · offre d'avant"),
                ("lien", "ouvre l'annonce sur son site")] + _COMMUNS,
         "prep": [("montre", "ouvre l'atelier du CV en cours"), ("écarte", "pas pour moi : retirée")] + _COMMUNS,
         "pret": [("prénom · nom · téléphone · ville", "écrit dans le champ cliqué"),
                  ("github · linkedin · lettre", "ton lien · le PDF de la lettre"),
                  ("montre · relis", "ouvre le PDF du CV · sa relecture"),
                  ("suivante · précédente", "change d'offre")] + _COMMUNS}


def step_of(o, prep_line=None, preparing=False):
    """Étape de l'offre affichée : aucune, tri, cv (à préparer), prep (en cours), pret. Pur : testable."""
    if o is None:
        return "aucune"
    if o.get("etat") in ("a-trier", "gardee"):
        return "tri"
    if prep_line == PREP_STEPS["pret"] or (o.get("preparation") or {}).get("etape") == "pret":
        return "pret"
    return "prep" if preparing else "cv"


CONTRATS = {"FULL_TIME": "Temps plein", "PART_TIME": "Temps partiel", "INTERN": "Stage", "CONTRACTOR": "Freelance",
            "TEMPORARY": "CDD", "APPRENTICESHIP": "Alternance"}


def fmt_contrat(v):
    """« FULL_TIME, CONTRACTOR » -> « Temps plein · Freelance » ; None si absent. Pur : testable."""
    parts = [CONTRATS.get(x.strip(), x.strip().capitalize()) for x in str(v or "").split(",") if x.strip()]
    return " · ".join(parts) or None


def fmt_age(date, today):
    """« 2026-10-09 19:02:28 +0200 » -> « il y a 3 j » ; None si illisible. Pur : testable."""
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(str(date)[:10])
    except ValueError:
        return None
    n = (today - d).days
    return "aujourd'hui" if n <= 0 else "hier" if n == 1 else f"il y a {n} j"


def offer_view(offres, i, today, prep_line=None):
    """Ce que le panneau montre de l'offre i. Pur : testable."""
    o = offres[i]
    ev = o.get("evaluation") or {}
    total = sum(1 for x in offres if x["etat"] == o["etat"])
    k = sum(1 for x in offres[:i + 1] if x["etat"] == o["etat"])
    contrat = o.get("contratLibelle") or fmt_contrat(o.get("contrat"))   # lus dans l'annonce par CVGEN (#64)
    chips = [str(c)[:40] for c in (contrat, o.get("ville"), o.get("teletravail"), o.get("salaire"), ev.get("verdict"),
                                   fmt_age(o.get("datePubliee"), today)) if c]
    axes = [a for a in ev.get("axes") or [] if isinstance(a.get("note"), (int, float))]
    plus = minus = None
    if axes:
        fort, faible = max(axes, key=lambda a: a["note"]), min(axes, key=lambda a: a["note"])
        plus = f"{fort.get('libelle')} : {fort.get('detail', '')}"[:120]
        if faible is not fort:
            minus = f"{faible.get('libelle')} : {faible.get('detail', '')}"[:120]
    note = ev.get("globale")
    return {"pos": f"Offre {k} sur {total} {A_PARCOURIR[o['etat']]}", "source": o.get("source") or "",
            "poste": o.get("poste") or "Poste ?", "entreprise": o.get("entreprise") or "entreprise ?",
            "chips": chips, "note": fmt_note(note),
            "frac": min(max(note / 5, 0.0), 1.0) if isinstance(note, (int, float)) else 0.0,
            "plus": plus, "minus": minus, "prep": prep_line}


def details_lines(texte, limit=DETAILS_MAX):
    """Début du texte de l'annonce, en paragraphes courts. Pur : testable."""
    out, n = [], 0
    for para in str(texte or "").replace("\r", "").split("\n"):
        para = " ".join(para.split())
        if not para:
            continue
        if n + len(para) > limit:
            out.append(para[:max(limit - n, 40)].rsplit(" ", 1)[0] + "…")
            break
        out.append(para)
        n += len(para)
    return out or ["Pas de texte pour cette annonce"]


def relances_lines(liste, today):
    """Candidatures envoyées : à relancer d'abord (J+7 passé, sans réponse), puis les plus récentes. Pur."""
    import datetime as _dt
    rows = []
    for e in liste or []:
        if not isinstance(e, dict) or e.get("refus") or e.get("proposition"):
            continue
        try:
            d = _dt.date.fromisoformat(str(e.get("date"))[:10])
        except ValueError:
            continue
        n = (today - d).days
        due = n >= RELANCE_J and not e.get("entretiens")
        rows.append((not due, -d.toordinal(), f"{e.get('poste') or 'Poste ?'} · {e.get('entreprise') or '?'}", n, due))
    rows.sort()
    if not rows:
        return ["Aucune candidature en attente de réponse"]
    a_relancer = sum(1 for r in rows if r[4])
    head = f"{a_relancer} à relancer" if a_relancer else "Rien à relancer aujourd'hui"
    return [head] + [f"{'À relancer · ' if due else ''}{lbl} · il y a {n} j" for _, _, lbl, n, due in rows[:8]]


def vivacite_text(v):
    """Réponse de « vérifier le lien » en une ligne. Pur : testable."""
    v = v or {}
    etat = v.get("etat")
    lbl = {"vivante": "Annonce encore en ligne", "morte": "Annonce retirée", "douteuse": "Vérification incertaine"}
    txt = lbl.get(etat, f"Annonce : {etat or 'état inconnu'}")
    return f"{txt} ({iris_says(v['detail'])})"[:120] if v.get("detail") else txt


def profile_value(profile, word):
    """Texte à écrire pour « mail », « github »… ; None s'il manque au profil. Pur : testable."""
    ident = (profile or {}).get("identity") or {}
    if word in FIELDS:
        v = str(ident.get(FIELDS[word]) or "").strip()
        if word == "naissance" and len(v) == 10 and v[4] == v[7] == "-":
            v = f"{v[8:]}/{v[5:7]}/{v[:4]}"          # AAAA-MM-JJ (CVGEN) -> JJ/MM/AAAA (formulaires français)
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


def _browser_front():
    import ctypes
    from .vscode import _exe_of
    return _exe_of(ctypes.windll.user32.GetForegroundWindow()) in BROWSERS


def _press(key):
    from .typer import press
    press(key)


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
TILES = (("tri", "à trier", "a-trier"), ("verif", "à vérifier", "generee"), ("ok", "postulées", None),
         ("ref", "refusées", None))   # tuiles du panneau, dans l'ordre du travail


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
                 typer=_type, fg_class=_fg_class, press=_press, browser_front=_browser_front):
        self.http, self.launch, self.open_url = http, launch, open_url
        self.typer, self.fg_class, self.press, self.browser_front = typer, fg_class, press, browser_front
        self.profile = None                # profil CVGEN lu une fois par ouverture du mode (en mémoire seulement)
        self.todo = []                     # « prépare tout » : offres qui attendent leur tour
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
        if word == "tab":
            self.press("tab")                  # touche seule : le champ garde le focus, rien à demander à CVGEN
            return
        if word == "prépare tout":
            return self._prep_all(t)
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
        self.view, self.note = ("card" if o is not None else "msg"), note

    def _show(self, title, lines, t, meta=None):
        self.title, self.lines = title, list(lines)
        self.meta = meta or next_hint(None)
        self.show_until = t + SHOW_S
        self.view = "msg"

    def events(self, core, t):
        while True:
            try:
                msg = self._q.get_nowait()
            except queue.Empty:
                break
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
        return []

    def actions(self, acts, core, t):
        rest = []
        for a in acts:
            if a[0] == "cand":
                self.ask(a[1], t)
            elif a[0] == "cand_off":
                self.lines, self.offres = None, None
                self.profile, self.todo = None, []   # profil relu à la prochaine ouverture
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
