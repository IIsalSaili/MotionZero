"""« iris candidature » : Iris pilote CVGEN (plan-cvgen.md), sans rien changer à CVGEN : constantes et fonctions (1/2, découpé de cvgen.py, #52)."""
import logging
from pathlib import Path






log = logging.getLogger("motionzero.cvgen")

BASE = "http://127.0.0.1:3000"
DIR = Path.home() / "Desktop" / "CVGEN"
TIMEOUT_S = 8
# appels longs : le modèle (réveil compris), la visite de l'annonce, les PDF (24/11 : 8 s ne suffisaient pas)
ROUTE_TIMEOUT_S = {"llm": 120, "verifier_lien": 40, "en_cours": 60, "preparer": 30, "offre": 20}
BUSY_MAX_S = 180.0       # au-delà, une demande sans réponse est oubliée : le mode ne reste jamais bloqué
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
    "llm": ("POST", "/api/llm"),                    # modèle local de CVGEN : réponse aux questions libres (#46)
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
         "question": "dis la question du formulaire : Iris propose une réponse",
         "écris": "écrit la réponse proposée dans le champ cliqué",
         "brouillon": "prépare un e-mail de candidature avec le CV et la lettre",
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
    "Questions libres : « question », dis-la, puis « écris » (la réponse proposée, dans le champ cliqué)",
    "Par e-mail : « brouillon » (adresse de l'annonce, CV et lettre joints ; tu relis et tu envoies)",
    "Suivi : « relances » (candidatures envoyées, à relancer)",
    "Souris : « souris », puis « clic » · « scroll »… · « stop » arrête tout",
    "Quitter le mode : « candidature »",
]
NAV = {"suivante", "précédente", "garde", "écarte", "lien", "prépare", "montre", "relis", "cv", "lettre",
       "postulé", "détails", "vérifie", "brouillon"}   # liste ouverte
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
         "prépare tout": "prépare toutes les offres à vérifier",
         "question": "propose une réponse à la question", "écris": "écrit la réponse proposée",
         "brouillon": "e-mail prêt avec CV et lettre", "cv": "joint le PDF du CV au site",
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
                  ("question · écris", "réponse à une question du formulaire"),
                  ("brouillon", "e-mail de candidature, CV et lettre joints"),
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


def fmt_note(v):
    if not isinstance(v, (int, float)):
        return "?"
    return (f"{v:.1f}".rstrip("0").rstrip(".")).replace(".", ",")
