"""« iris candidature » : Iris pilote CVGEN par ses adresses existantes (plan-cvgen.md), échecs compris."""
import json
import re
import time
from pathlib import Path

import pytest

from motionzero import cvgen as cv
from motionzero.config import Config
from motionzero.core import CAND_IDLE_S, Core


# ---- les adresses utilisées existent toujours dans CVGEN (CVGEN n'est jamais modifié pour Iris)
def test_routes_existent_dans_cvgen():
    server = cv.DIR / "server.mjs"
    if not server.exists():
        pytest.skip("CVGEN absent de ce PC")
    src = server.read_text(encoding="utf-8")
    # toutes les routes du serveur : ['MÉTHODE', /regex/i, …] ; la regex JS se lit telle quelle en Python
    routes = [(m, re.compile(rx.replace("\\/", "/"), re.I if fl else 0))
              for m, rx, fl in re.findall(r"\['(GET|POST|PUT|PATCH|DELETE|\*)', /(\^.+?\$)/(i?),", src)]

    def existe(method, path):
        return any(m in (method, "*") and rx.match(path) for m, rx in routes)

    for name, (method, path) in cv.ROUTES.items():
        assert existe(method, path.format(id="o-1")), name
    pdf = cv.PAGES["pdf_cv"].format(id="o-1").split("?")[0]
    assert existe("GET", pdf)
    for page in ("atelier", "jury"):
        fichier = cv.PAGES[page].split("?")[0].lstrip("/")
        assert (cv.DIR / "public" / fichier).exists(), page


# ---- carte « état »
def test_resume_etat():
    lines = cv.summary({"etat": "en-cours"}, {"verif": 3, "tri": 1, "off": 40}, {"offreId": "x"})
    assert lines == ["Recherche en cours", "3 à vérifier · 1 à trier", "Une candidature est en préparation"]
    assert cv.summary({"etat": "arrete"}, {}, {}) == ["Recherche arrêtée", "Aucune offre en attente"]
    assert cv.summary(None, None, None)[0] == "Recherche arrêtée"


# ---- service : faux CVGEN
class FauxCvgen:
    def __init__(self, up=True, etat="arrete", refus=None, panne=None):
        self.up, self.etat, self.refus, self.panne = up, etat, refus, panne
        self.calls = []
        self.preps = [{"etape": "cv"}, {"etape": "pdf-cv"}, {"etape": "lettre", "libelle": "Lettre…"},
                      {"etape": "pret"}]

    def __call__(self, method, path, body=None):
        self.calls.append((method, path) if body is None else (method, path, body))
        if self.panne:
            raise self.panne
        if not self.up:
            raise cv.CvgenError("CVGEN ne répond pas")
        if self.refus and path == self.refus[0]:
            raise cv.CvgenError(self.refus[1])
        if path == "/api/agent/demarrer":
            self.etat = "en-cours"
        if path == "/api/agent/arreter":
            self.etat = "arrete"
        if path == "/api/offres":
            return OFFRES
        if path.startswith("/api/offres/") and method == "GET" and path != "/api/offres/compte":
            return {"preparation": self.preps.pop(0) if len(self.preps) > 1 else self.preps[0]}
        return {"/api/agent": {"etat": self.etat}, "/api/offres/compte": {"verif": 2},
                "/api/preparation": {"offreId": None}}.get(path, {"ok": True})


def _attendre(c, core, t=0.0):
    for _ in range(200):
        c.events(core, t)
        if not c.busy:
            return c.state(t)
        time.sleep(0.01)
    raise AssertionError("pas de réponse")


def test_cherche_lance_puis_arrete():
    faux = FauxCvgen()
    c, core = cv.Candidature(http=faux, launch=lambda: None), Core(Config())
    c.ask("cherche", 0.0)
    assert _attendre(c, core)["title"] == "Recherche lancée"
    assert ("POST", "/api/agent/demarrer") in faux.calls
    c.ask("cherche", 1.0)
    st = _attendre(c, core, 1.0)
    assert st["title"] == "Recherche arrêtée" and ("POST", "/api/agent/arreter") in faux.calls


def test_etat_et_offres():
    ouvert = []
    c, core = cv.Candidature(http=FauxCvgen(), launch=lambda: None, open_url=ouvert.append), Core(Config())
    c.ask("état", 0.0)
    _attendre(c, core)
    assert [o["id"] for o in c.offres] == ["t2", "t1", "v1"]      # ouverture : la liste tout de suite
    pn = c.panel(0.0)
    assert pn["status"] == "Recherche arrêtée" and pn["offer"]["poste"] == "Poste t2"
    assert (2, "à vérifier", False) in pn["tiles"]
    c.ask("état", 20.0)                                          # liste déjà ouverte : pas rechargée
    _attendre(c, core, 20.0)
    assert c.panel(20.0)["offer"] is not None
    c.ask("offres", 0.0)
    assert _attendre(c, core)["title"] == "Offres ouvertes" and ouvert == [cv.BASE + "/"]


def test_cvgen_eteint_est_lance():
    faux = FauxCvgen(up=False)
    lances = []

    def launch():
        lances.append(1)
        faux.up = True
    c = cv.Candidature(http=faux, launch=launch, sleep=lambda s: None)
    c.ask("état", 0.0)
    assert _attendre(c, Core(Config()))["title"].startswith("Offre 1 / 2") and lances == [1]


def test_cvgen_ne_demarre_pas():
    horloge = iter(range(0, 1000, 5))
    c = cv.Candidature(http=FauxCvgen(up=False), launch=lambda: None, sleep=lambda s: None,
                       clock=lambda: next(horloge))
    c.ask("cherche", 0.0)
    st = _attendre(c, Core(Config()))
    assert st["title"] == "Candidature impossible" and st["lines"] == ["CVGEN n'a pas démarré"]


def test_cvgen_introuvable():
    def launch():
        raise cv.CvgenError("CVGEN introuvable sur ce PC")
    c = cv.Candidature(http=FauxCvgen(up=False), launch=launch)
    c.ask("état", 0.0)
    assert _attendre(c, Core(Config()))["lines"] == ["CVGEN introuvable sur ce PC"]


def test_refus_de_cvgen_affiche():
    c = cv.Candidature(http=FauxCvgen(refus=("/api/agent/demarrer", "La recherche tourne déjà")), launch=lambda: None)
    c.ask("cherche", 0.0)
    assert _attendre(c, Core(Config()))["lines"] == ["La recherche tourne déjà"]


def test_panne_inattendue_ne_remonte_pas():
    c = cv.Candidature(http=FauxCvgen(panne=KeyError("x")), launch=lambda: None)
    c.ask("état", 0.0)
    st = _attendre(c, Core(Config()))
    assert st["title"] == "Candidature impossible" and "KeyError" in st["lines"][0]


def test_demande_pendant_une_autre():
    c = cv.Candidature(http=FauxCvgen(), launch=lambda: None)
    c.busy = True
    c.ask("cherche", 0.0)
    assert "Patiente" in c.state(0.0)["lines"][0]


def test_http_cvgen_eteint():
    with pytest.raises(cv.CvgenError, match="ne répond pas"):
        cv._http("GET", "/api/health", base="http://127.0.0.1:9", timeout=5)


def test_carte_fermee_par_merci():
    c = cv.Candidature(http=FauxCvgen(), launch=lambda: None)
    c._show("Candidature", ["x"], 0.0)
    assert c.actions([("rappel_merci",)], Core(Config()), 0.0) == [("rappel_merci",)]
    assert c.state(0.0) is None


# ---- Core : le mode
def test_mode_allume_redit_eteint():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert ("cand", "état") in core.voice("candidature", 1.3)
    assert core.cand_on(2.0)
    assert core.voice("cherche", 3.0) == [("cand", "cherche")]       # sans « iris »
    assert core.voice("candidature", 4.0) == [("cand_off",)]         # redit seul : éteint
    assert not core.cand_on(4.1)
    core.voice("iris", 5.0)
    core.voice("candidature", 5.3)
    core.voice("iris", 6.0)
    assert core.voice("candidature", 6.3) == [("cand_off",)]         # « iris candidature » redit : éteint aussi


def test_mots_du_mode_sans_effet_hors_mode():
    core = Core(Config())
    assert ("cand", "cherche") not in core.voice("cherche", 1.0)


def test_mode_ne_s_eteint_jamais_seul():
    core = Core(Config())                          # 19/11 : éteint seulement par « candidature » redit
    core.voice("iris", 1.0)
    core.voice("candidature", 1.3)
    assert core.cand_on(1.3 + 24 * 3600)


def test_pause_eteint_le_mode():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("candidature", 1.3)
    core.voice("iris", 2.0)
    assert ("cand_off",) in core.voice("pause", 2.3)
    assert not core.cand_on(3.0)


def test_mots_du_mode_guettes_seulement_mode_allume():
    from motionzero.voice import GRAMMARS
    for nom, g in GRAMMARS.items():
        mots = json.loads(g)
        assert ("cherche" in mots) == nom.startswith("candidature"), nom
        assert "candidature" in mots


def test_mode_n_ecoute_que_ses_mots():
    """Demande du 17/11 : dans le mode, plus aucun mot de base ni de Chrome ; la souris seulement allumée."""
    from motionzero.voice import GRAMMARS
    base = set(json.loads(GRAMMARS["candidature"])) - {"[unk]"}
    assert base == set(cv.WORDS) | {"candidature", "stop", "souris"}
    souris = set(json.loads(GRAMMARS["candidature_souris"])) - base - {"[unk]"}
    assert souris == {"clic", "double", "double clic", "menu", "agrippe", "scroll"}


def test_souris_sans_iris_dans_le_mode():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("candidature", 1.3)
    core.voice("souris", 2.0)
    assert core.mouse and core.cand_on(2.1)
    core.voice("souris", 3.0)
    assert not core.mouse



# ---- phase 2 : tri des offres
def _offre(id, etat, note, url="https://exemple.fr/o"):
    return {"id": id, "etat": etat, **({"cvId": f"cv-{id}"} if etat == "generee" else {}), "poste": f"Poste {id}", "entreprise": "ACME", "source": "apec", "url": url,
            "evaluation": {"globale": note, "verdict": "Bonne", "axes": [
                {"libelle": "Adéquation", "note": 5, "detail": "très bien"},
                {"libelle": "Niveau", "note": 2, "detail": "senior"}]}}


OFFRES = [_offre("v1", "generee", 4.0), _offre("t1", "a-trier", 3.0), _offre("t2", "a-trier", 4.5, url=None),
          _offre("x", "ecartee", 5.0)]


def test_ordre_a_trier_puis_a_verifier():
    assert [o["id"] for o in cv.a_parcourir(OFFRES)] == ["t2", "t1", "v1"]
    assert cv.a_parcourir(None) == []


def test_carte_d_une_offre():
    titre, lignes = cv.card(cv.a_parcourir(OFFRES), 1)
    assert titre == "Offre 2 / 2 à trier · 3 / 5"
    assert lignes == ["Poste t1 · ACME", "Bonne (apec)", "+ Adéquation : très bien", "- Niveau : senior"]
    assert cv.card(cv.a_parcourir(OFFRES), 2)[0] == "Offre 1 / 1 à vérifier · 4 / 5"
    assert cv.card([], 0)[0] == "Aucune offre à trier ni à vérifier"
    assert cv.fmt_note(4.5) == "4,5" and cv.fmt_note(None) == "?"


def test_carte_offre_incomplete():
    titre, lignes = cv.card([{"id": "a", "etat": "a-trier"}], 0)
    assert titre == "Offre 1 / 1 à trier · ? / 5" and lignes == ["Poste ? · entreprise ?"]


def _liste(ouvert=None):
    faux = FauxCvgen()
    c = cv.Candidature(http=faux, launch=lambda: None, open_url=ouvert.append if ouvert is not None else None)
    core = Core(Config())
    c.ask("liste", 0.0)
    _attendre(c, core)
    return c, core, faux


def test_liste_suivante_precedente():
    c, core, _ = _liste()
    assert c.state(0.0)["lines"][0] == "Poste t2 · ACME"
    c.ask("suivante", 1.0)
    assert c.state(1.0)["lines"][0] == "Poste t1 · ACME"
    c.ask("précédente", 2.0)
    c.ask("précédente", 2.0)                       # boucle : de la première à la dernière
    assert c.state(2.0)["lines"][0] == "Poste v1 · ACME"


def test_garde_et_ecarte_passent_par_cvgen():
    c, core, faux = _liste()
    c.ask("garde", 0.0)
    st = _attendre(c, core)
    assert ("PATCH", "/api/offres/t2", {"etat": "gardee"}) in faux.calls
    assert "Gardée" in st["lines"][-1] and st["lines"][0] == "Poste t2 · ACME"   # reste visible, CV en cours (#59)
    assert c.offres[c.i]["etat"] == "gardee"
    c.ask("garde", 0.0)
    assert "CV est en cours" in c.state(0.0)["lines"][-1] and not c.busy
    c.ask("suivante", 0.0)
    c.ask("écarte", 0.0)
    _attendre(c, core)
    assert ("PATCH", "/api/offres/t1", {"etat": "ecartee"}) in faux.calls
    assert [o["id"] for o in c.offres] == ["t2", "v1"]


def test_garde_une_offre_a_verifier_refusee():
    c, core, faux = _liste()
    c.i = 2
    c.ask("garde", 0.0)
    assert "Déjà gardée" in c.state(0.0)["lines"][-1] and not c.busy
    assert not [x for x in faux.calls if x[0] == "PATCH"]


def test_ouvre_l_offre_et_sans_lien():
    ouvert = []
    c, core, _ = _liste(ouvert)
    c.ask("lien", 0.0)
    assert ouvert == [] and "pas de lien" in c.state(0.0)["lines"][-1]   # t2 n'a pas de lien
    c.ask("suivante", 0.0)
    c.ask("lien", 0.0)
    assert ouvert == ["https://exemple.fr/o"]


def test_mots_de_liste_sans_liste():
    c = cv.Candidature(http=FauxCvgen(), launch=lambda: None)
    c.ask("garde", 0.0)
    assert "dis « liste »" in c.state(0.0)["lines"][0] and not c.busy


def test_liste_vide():
    c = cv.Candidature(http=lambda m, p, b=None: [] if p == "/api/offres" else {}, launch=lambda: None)
    c.ask("liste", 0.0)
    st = _attendre(c, Core(Config()))
    assert st["title"] == "Aucune offre à trier ni à vérifier"
    c.ask("suivante", 0.0)
    assert "dis « liste »" in c.state(0.0)["lines"][0]


def test_garde_refusee_par_cvgen_garde_l_offre():
    c, core, faux = _liste()
    faux.refus = ("/api/offres/t2", "Offre inconnue")
    c.ask("garde", 0.0)
    st = _attendre(c, core)
    assert st["lines"] == ["Offre inconnue"] and c.offres[0]["id"] == "t2"


def test_derniere_offre_traitee():
    c, core, faux = _liste()
    for _ in range(3):
        c.ask("écarte", 0.0)
        _attendre(c, core)
    assert c.state(0.0)["title"] == "Aucune offre à trier ni à vérifier" and c.offres == []


def test_quitter_le_mode_ferme_la_liste():
    c, core, _ = _liste()
    c.actions([("cand_off",)], core, 0.0)
    assert c.offres is None and c.state(0.0) is None


# ---- phase 3 : CV et pièces
def test_texte_d_avancement():
    assert cv.prep_text({"etape": "cv"}) == "Préparation : Iris compose le CV…"
    assert cv.prep_text({"etape": "lettre", "libelle": "Lettre…"}) == "Préparation : Lettre…"
    assert cv.prep_text({"etape": "pret"}) == "Prêt : CV et pièces en PDF"
    assert cv.prep_text({"etape": "erreur", "erreur": "Claude est déjà occupé"}) == "Échec : Iris est déjà occupé"
    assert cv.prep_text(None) == "Préparation : pièces…"


def _sur_v1(ouvert=None):
    c, core, faux = _liste(ouvert)
    c.i = 2                                        # v1 : à vérifier, CV prêt
    c.sleep = lambda s: None
    return c, core, faux


def _fin_prep(c, core):
    for _ in range(300):
        c.events(core, 0.0)
        if c.preparing is None:
            return c.state(0.0)
        time.sleep(0.01)
    raise AssertionError("préparation jamais finie")


def test_prepare_suit_jusqu_a_pret():
    c, core, faux = _sur_v1()
    c.ask("prépare", 0.0)
    st = _fin_prep(c, core)
    assert ("POST", "/api/offres/v1/preparer", {}) in faux.calls
    assert st["lines"][-1] == "Prêt : CV et pièces en PDF"


def test_prepare_echec_de_cvgen():
    c, core, faux = _sur_v1()
    faux.preps = [{"etape": "erreur", "erreur": "Le CV déborde d'une page"}]
    c.ask("prépare", 0.0)
    assert _fin_prep(c, core)["lines"][-1] == "Échec : Le CV déborde d'une page"


def test_prepare_refusee_au_lancement():
    c, core, faux = _sur_v1()
    faux.refus = ("/api/offres/v1/preparer", "Claude est déjà occupé (jury ou composition en cours)")
    c.ask("prépare", 0.0)
    _fin_prep(c, core)
    assert c.prep["v1"] == "Échec : Iris est déjà occupé (jury ou composition en cours)"
    assert "Claude" not in " ".join(c.state(0.0)["lines"])


def test_prepare_une_seule_a_la_fois():
    c, core, faux = _sur_v1()
    c.preparing = "autre"
    c.ask("prépare", 0.0)
    assert "en préparation" in c.state(0.0)["lines"][-1]
    assert not [x for x in faux.calls if "preparer" in x[1]]


def test_prepare_sans_cv():
    c, core, faux = _liste()                       # t2 : à trier, pas de CV
    for w in ("prépare", "montre", "relis"):
        c.ask(w, 0.0)
        assert "dis « garde » d'abord" in c.state(0.0)["lines"][-1]
    assert c.preparing is None


def test_prepare_trop_long():
    horloge = iter(range(0, 100000, 100))
    c, core, faux = _sur_v1()
    c.clock = lambda: next(horloge)
    faux.preps = [{"etape": "cv"}]
    c.ask("prépare", 0.0)
    assert "trop long" in _fin_prep(c, core)["lines"][-1]


def test_montre_atelier_puis_pdf_et_relis():
    ouvert = []
    c, core, faux = _sur_v1(ouvert)
    c.ask("montre", 0.0)
    assert ouvert[-1] == cv.BASE + "/generate.html?id=cv-v1"       # pas encore préparé : l'atelier
    c.ask("prépare", 0.0)
    _fin_prep(c, core)
    c.ask("montre", 0.0)
    assert ouvert[-1] == cv.BASE + "/api/offres/v1/pdf/cv?voir=1"
    c.ask("relis", 0.0)
    assert ouvert[-1] == cv.BASE + "/jury.html?id=cv-v1"


def test_montre_offre_deja_preparee_avant():
    ouvert = []
    c, core, faux = _sur_v1(ouvert)
    c.offres[2] = {**c.offres[2], "preparation": {"etape": "pret"}}
    c.ask("montre", 0.0)
    assert ouvert[-1].endswith("/pdf/cv?voir=1")


# ---- aide : les commandes visibles (17/11 : « aucun endroit où voir les commandes »)
def test_aide_du_mode():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("candidature", 1.3)
    assert core.voice("aide", 2.0) == [("cand", "aide")]          # sans « iris », dans le mode
    c = cv.Candidature(http=FauxCvgen(), launch=lambda: None)
    c.ask("aide", 0.0)
    st = c.state(0.0)
    assert st["lines"] == cv.HELP_LINES and not c.busy
    assert c.state(cv.HELP_S - 1) is not None                      # reste le temps de lire


def test_bas_de_carte_selon_l_etape():
    assert "« garde »" in cv.next_hint({"etat": "a-trier"})
    assert cv.next_hint({"etat": "generee"}).startswith("« prépare »")
    assert "en cours" in cv.next_hint({"etat": "generee"}, preparing=True)
    pret = cv.next_hint({"etat": "generee"}, cv.PREP_STEPS["pret"])
    assert "« lien »" in pret and "« postulé »" in pret
    assert "« lien »" in cv.next_hint({"etat": "generee", "preparation": {"etape": "pret"}})
    assert "« liste »" in cv.next_hint(None)
    for h in (cv.next_hint(None), pret):
        assert len(h) <= 60 and "« aide »" in h                    # court : sinon rétréci, illisible


def test_carte_apres_preparation_propose_la_suite():
    c, core, faux = _sur_v1()
    c.ask("prépare", 0.0)
    st = _fin_prep(c, core)
    assert "« lien »" in st["meta"] and "« cv »" in st["meta"] and "« postulé »" in st["meta"]


# ---- phase 4 : remplir le formulaire du site, un champ quand tu le demandes
PROFIL = {"identity": {"prenom": "Ada", "nom": "Lovelace", "email": "ada@exemple.fr", "telephone": "06 00 00 00 00",
                       "ville": "", "liens": [{"label": "github.com/ada", "url": "https://github.com/ada"}]}}


class FauxDepot(FauxCvgen):
    def __init__(self, en_cours=None, **kw):
        super().__init__(**kw)
        self.en_cours = en_cours if en_cours is not None else {"cv": "C:\\en-cours\\CV Ada.pdf", "lettre": None}

    def __call__(self, method, path, body=None):
        if path == "/api/profile":
            self.calls.append((method, path))
            return PROFIL
        if path.endswith("/en-cours"):
            self.calls.append((method, path, body))
            if self.refus and path == self.refus[0]:
                raise cv.CvgenError(self.refus[1])
            return self.en_cours
        return super().__call__(method, path, body)


def test_valeurs_du_profil():
    assert cv.profile_value(PROFIL, "mail") == "ada@exemple.fr"
    assert cv.profile_value(PROFIL, "github") == "https://github.com/ada"
    assert cv.profile_value(PROFIL, "ville") is None              # vide : rien n'est écrit
    assert cv.profile_value(PROFIL, "linkedin") is None
    assert cv.profile_value(None, "nom") is None


def _depot(fg="Chrome_WidgetWin_1", navigateur=True, **kw):
    ecrit = []
    faux = FauxDepot(**kw)
    c = cv.Candidature(http=faux, launch=lambda: None, typer=lambda s, enter=False: ecrit.append((s, enter)),
                       fg_class=lambda: fg, browser_front=lambda: navigateur)
    c.sleep = lambda s: None
    core = Core(Config())
    c.ask("liste", 0.0)
    _attendre(c, core)
    c.i = 2                                        # v1 : CV prêt
    return c, core, faux, ecrit


def test_champ_ecrit_a_la_demande():
    c, core, faux, ecrit = _depot()
    c.ask("mail", 0.0)
    _attendre(c, core)
    assert ecrit == [("ada@exemple.fr", False)]
    c.ask("téléphone", 0.0)
    _attendre(c, core)
    assert ecrit[-1] == ("06 00 00 00 00", False)


def test_champ_absent_du_profil():
    c, core, faux, ecrit = _depot()
    c.ask("linkedin", 0.0)
    st = _attendre(c, core)
    assert ecrit == [] and "absent de ton profil" in st["lines"][0]


def test_champ_sans_liste_marche_aussi():
    ecrit = []
    c = cv.Candidature(http=FauxDepot(), launch=lambda: None, typer=lambda s, enter=False: ecrit.append(s),
                       browser_front=lambda: True)
    c.ask("prénom", 0.0)
    _attendre(c, Core(Config()))
    assert ecrit == ["Ada"]


def test_cv_dans_la_fenetre_choisir_un_fichier():
    c, core, faux, ecrit = _depot(fg=cv.FILE_DIALOG)
    c.ask("cv", 0.0)
    st = _attendre(c, core)
    assert ecrit == [("C:\\en-cours\\CV Ada.pdf", True)] and st["lines"][-1] == "CV joint"
    c.ask("cv", 0.0)                                # chemin déjà connu : pas de nouvel appel
    assert len([x for x in faux.calls if x[1].endswith("/en-cours")]) == 1 and len(ecrit) == 2


def test_cv_sans_fenetre_de_fichier():
    c, core, faux, ecrit = _depot()
    c.ask("cv", 0.0)
    st = _attendre(c, core)
    assert ecrit == [] and "Choisir un fichier" in st["lines"][-1]


def test_lettre_absente():
    c, core, faux, ecrit = _depot(fg=cv.FILE_DIALOG)
    c.ask("lettre", 0.0)
    st = _attendre(c, core)
    assert ecrit == [] and "dis « prépare » d'abord" in st["lines"][-1]


def test_pdf_pas_encore_prepares():
    c, core, faux, ecrit = _depot(fg=cv.FILE_DIALOG)
    faux.refus = ("/api/offres/v1/en-cours", "Le dossier n'a pas encore été préparé")
    c.ask("cv", 0.0)
    st = _attendre(c, core)
    assert ecrit == [] and st["lines"] == ["Le dossier n'a pas encore été préparé"]


def test_cv_offre_sans_cv():
    c, core, faux, ecrit = _depot(fg=cv.FILE_DIALOG)
    c.i = 0                                        # t2 : à trier
    for w in ("cv", "postulé"):
        c.ask(w, 0.0)
        assert "dis « garde » d'abord" in c.state(0.0)["lines"][-1]
    assert ecrit == [] and not [x for x in faux.calls if x[0] == "PATCH"]


def test_postule_note_la_candidature():
    c, core, faux, ecrit = _depot()
    c.ask("postulé", 0.0)
    st = _attendre(c, core)
    assert ("PATCH", "/api/offres/v1", {"etat": "postulee"}) in faux.calls
    assert "postulée" in st["lines"][-1] and "v1" not in [o["id"] for o in c.offres]


def test_mots_du_panneau_par_etape():
    assert cv.hint_words(None) == ["liste", "cherche", "état", "offres"]
    assert cv.hint_words({"etat": "a-trier"})[0] == "garde"
    assert cv.hint_words({"etat": "generee"})[0] == "prépare"
    assert cv.hint_words({"etat": "generee"}, cv.PREP_STEPS["pret"])[0] == "lien"
    assert cv.hint_words({"etat": "generee"}, preparing=True)[0] == "suivante"
    for o in (None, {"etat": "a-trier"}, {"etat": "generee"}):       # tous les mots existent dans le mode
        assert set(cv.hint_words(o)) <= set(cv.WORDS)


def test_contrat_et_anciennete():
    import datetime
    assert cv.fmt_contrat("FULL_TIME") == "Temps plein"
    assert cv.fmt_contrat("CONTRACTOR, FULL_TIME") == "Freelance · Temps plein"
    assert cv.fmt_contrat(None) is None and cv.fmt_contrat("") is None
    j = datetime.date(2026, 11, 21)
    assert cv.fmt_age("2026-11-18 19:02:28 +0200", j) == "il y a 3 j"
    assert cv.fmt_age("2026-11-20T08:00:00Z", j) == "hier"
    assert cv.fmt_age("2026-11-21", j) == "aujourd'hui"
    assert cv.fmt_age(None, j) is None and cv.fmt_age("n'importe", j) is None


def test_vue_de_l_offre():
    import datetime
    offres = cv.a_parcourir(OFFRES)
    v = cv.offer_view(offres, 1, datetime.date(2026, 11, 21))
    assert v["pos"] == "Offre 2 sur 2 à trier" and v["note"] == "3" and abs(v["frac"] - 0.6) < 1e-9
    assert v["plus"].startswith("Adéquation") and v["minus"].startswith("Niveau")
    vide = cv.offer_view([{"id": "z", "etat": "a-trier"}], 0, datetime.date(2026, 11, 21))   # offre sans rien
    assert vide["poste"] == "Poste ?" and vide["note"] == "?" and vide["frac"] == 0.0 and vide["chips"] == []


def test_panneau_sans_liste_et_en_erreur():
    c = cv.Candidature(http=FauxCvgen(up=False), launch=lambda: (_ for _ in ()).throw(cv.CvgenError("CVGEN introuvable sur ce PC")))
    pn = c.panel(0.0)
    assert pn["offer"] is None and "liste" in pn["msg"]["lines"][0] and pn["status"] == ""
    c.ask("état", 0.0)
    _attendre(c, Core(Config()))
    pn = c.panel(0.0)
    assert pn["msg"]["title"] == "Candidature impossible" and pn["msg"]["lines"] == ["CVGEN introuvable sur ce PC"]
    assert pn["tiles"][0] == (0, "à trier", False)


def test_panneau_retour_sous_l_offre_puis_message_qui_expire():
    c, core = cv.Candidature(http=FauxCvgen(), launch=lambda: None), Core(Config())
    c.ask("liste", 0.0)
    _attendre(c, core)
    c.ask("suivante", 1.0)
    assert c.panel(1.0)["offer"]["poste"] == "Poste t1"
    c.ask("aide", 2.0)
    assert c.panel(2.0)["msg"]["title"].startswith("Candidature : ce que")
    assert c.panel(2.0 + cv.HELP_S + 1)["offer"]["poste"] == "Poste t1"   # l'aide passe, l'offre revient
    c.ask("écarte", 50.0)
    _attendre(c, core, 50.0)
    assert c.panel(50.0)["note"] == "Écartée"


def test_panneau_dessine_et_efface():
    """Le panneau se dessine sans erreur (offre, message, liste vide) et la droite est repeinte à l'extinction."""
    from PySide6.QtGui import QImage, QPainter
    from motionzero.ui import QApplication, _IslandPainter
    QApplication.instance() or QApplication([])
    c, core = cv.Candidature(http=FauxCvgen(), launch=lambda: None), Core(Config())
    vues = [c.panel(0.0)]
    c.ask("liste", 0.0)
    _attendre(c, core)
    vues.append(c.panel(0.0))
    c.ask("aide", 1.0)
    vues.append(c.panel(1.0))
    p = _IslandPainter(1920, 1080)
    img = QImage(1920, 1080, QImage.Format.Format_ARGB32)
    for k, pn in enumerate(vues):
        p.update({"mode": "NEUTRE", "candidature": True, "cand_panel": pn}, float(k))
        assert p.rect().right() >= 1919 and p.rect().bottom() >= 1000
        painter = QPainter(img)
        p.paint(painter)
        painter.end()
    p.update({"mode": "NEUTRE"}, 10.0)
    assert p.rect().right() >= 1919       # repeinte une fois pour effacer
    p.update({"mode": "NEUTRE"}, 11.0)
    assert p.rect().bottom() < 1000


def test_app_panneau_seulement_mode_allume():
    from types import SimpleNamespace
    from motionzero.app import cand_panel

    class Casse:
        def panel(self, t):
            raise RuntimeError("boum")
    core = Core(Config())
    d = SimpleNamespace(core=core, candidature=cv.Candidature(http=FauxCvgen(), launch=lambda: None))
    assert cand_panel(d, 0.0) is None                     # mode éteint
    core.cand_until = 100.0
    assert cand_panel(d, 0.0)["words"][0][0] == "liste"
    d.candidature = Casse()
    assert cand_panel(d, 0.0) is None                     # une exception ne remonte pas


def test_chaque_mot_du_panneau_dit_ce_qu_il_fait():
    for o, prep, en_cours in ((None, None, False), ({"etat": "a-trier"}, None, False), ({"etat": "generee"}, None, False),
                              ({"etat": "generee"}, None, True), ({"etat": "generee"}, cv.PREP_STEPS["pret"], False)):
        for w in cv.hint_words(o, prep, en_cours):
            assert cv.SHORT[w]
        for mots, quoi in cv.EXTRA[cv.step_of(o, prep, en_cours)]:
            assert quoi and all(m in cv.WORDS for m in mots.split(" · "))   # seulement des mots qui existent


# ---- 21/11 : annule, détails, vérifie, relances, fin de liste
def _introuvable():
    raise cv.CvgenError("CVGEN introuvable sur ce PC")


def _ouverte(http=None):
    c, core = cv.Candidature(http=http or FauxCvgen(), launch=_introuvable), Core(Config())
    c.ask("liste", 0.0)
    _attendre(c, core)
    return c, core


def test_annule_remet_l_offre_ecartee_a_sa_place():
    faux = FauxCvgen()
    c, core = _ouverte(faux)
    c.ask("suivante", 1.0)                                       # t1, 2e de la liste
    c.ask("écarte", 2.0)
    _attendre(c, core, 2.0)
    assert [o["id"] for o in c.offres] == ["t2", "v1"]
    c.ask("annule", 3.0)
    _attendre(c, core, 3.0)
    assert [o["id"] for o in c.offres] == ["t2", "t1", "v1"] and c.offres[c.i]["id"] == "t1"
    assert ("PATCH", "/api/offres/t1", {"etat": "a-trier"}) in faux.calls and c.panel(3.0)["note"].startswith("Annulé")
    c.ask("annule", 4.0)                                         # une seule annulation
    assert c.state(4.0)["lines"] == ["Rien à annuler"]


def test_annule_sans_rien_et_en_erreur():
    c = cv.Candidature(http=FauxCvgen(), launch=lambda: None)
    c.ask("annule", 0.0)
    assert c.state(0.0)["lines"] == ["Rien à annuler"] and not c.busy
    faux = FauxCvgen()
    c, core = _ouverte(faux)
    c.ask("écarte", 1.0)
    _attendre(c, core, 1.0)
    faux.up = False                                              # CVGEN tombe avant l'annulation
    c.ask("annule", 2.0)
    st = _attendre(c, core, 2.0)
    assert st["title"] == "Candidature impossible" and c.last is not None   # on pourra réessayer


def test_details_et_verifie():
    base = FauxCvgen()

    def http(method, path, body=None):
        if path == "/api/offres/t2" and method == "GET":
            return {"texte": "Poste basé à Lyon.\n\nSalaire : 40 k€\n" + "x " * 2000}
        if path.endswith("/verifier-lien"):
            return {"etat": "vivante"}
        return base(method, path, body)
    c, core = _ouverte(http)
    c.ask("détails", 1.0)
    st = _attendre(c, core, 1.0)
    assert st["title"] == "Annonce : Poste t2" and st["lines"][:2] == ["Poste basé à Lyon.", "Salaire : 40 k€"]
    assert st["lines"][-1].endswith("…") and c.state(1.0 + cv.HELP_S - 1) is not None
    assert c.panel(1.0)["msg"]["title"] == "Annonce : Poste t2"
    c.ask("suivante", 2.0)                                       # t1 : a un lien
    c.ask("vérifie", 3.0)
    _attendre(c, core, 3.0)
    assert c.panel(3.0)["note"] == "Annonce encore en ligne"


def test_verifie_sans_lien_et_details_cvgen_absent():
    faux = FauxCvgen()
    c, core = _ouverte(faux)                                       # t2 n'a pas de lien
    c.ask("vérifie", 1.0)
    assert "pas de lien" in c.state(1.0)["lines"][-1] and not c.busy
    faux.up = False
    c.ask("détails", 2.0)
    assert _attendre(c, core, 2.0)["title"] == "Candidature impossible"


def test_fin_et_debut_de_liste_annonces():
    c, _ = _ouverte()
    c.ask("précédente", 1.0)
    assert c.panel(1.0)["note"].startswith("Début de la liste")
    c.ask("suivante", 2.0)
    assert c.panel(2.0)["note"].startswith("Fin de la liste") and c.i == 0
    c.ask("suivante", 3.0)
    assert c.panel(3.0)["note"] is None


def test_relances():
    import datetime
    j = datetime.date(2026, 11, 21)
    liste = [{"poste": "A", "entreprise": "X", "date": "2026-11-10"},
             {"poste": "B", "entreprise": "Y", "date": "2026-11-19"},
             {"poste": "C", "entreprise": "Z", "date": "2026-11-01", "refus": True},
             {"poste": "D", "entreprise": "W", "date": "2026-11-02", "entretiens": [{"le": "x"}]},
             {"poste": "E", "entreprise": "V", "date": None}, "abîmé"]
    lignes = cv.relances_lines(liste, j)
    assert lignes[0] == "1 à relancer"
    assert lignes[1] == "À relancer · A · X · il y a 11 j"
    assert "B · Y · il y a 2 j" in lignes and not any("C ·" in l for l in lignes)
    assert cv.relances_lines([], j) == ["Aucune candidature en attente de réponse"]
    assert cv.relances_lines(None, j) == ["Aucune candidature en attente de réponse"]


def test_relances_par_la_voix():
    base = FauxCvgen()

    def http(method, path, body=None):
        if path == "/api/postulees":
            return []
        return base(method, path, body)
    c = cv.Candidature(http=http, launch=lambda: None)
    c.ask("relances", 0.0)
    st = _attendre(c, Core(Config()))
    assert st["title"] == "Candidatures envoyées" and st["lines"] == ["Aucune candidature en attente de réponse"]


def test_vivacite_et_texte_annonce():
    assert cv.vivacite_text({"etat": "morte"}) == "Annonce retirée"
    assert cv.vivacite_text({"etat": "douteuse", "detail": "Claude a vu un captcha"}).endswith("(Iris a vu un captcha)")
    assert cv.vivacite_text(None) == "Annonce : état inconnu"
    assert cv.details_lines("") == ["Pas de texte pour cette annonce"]
    assert cv.details_lines("a\r\n\r\n  b   c ") == ["a", "b c"]


# ---- 24/11 : champs du profil (#68), « tab » (#67), profil lu une fois (#62), mauvaise fenêtre (#61)
PROFIL["identity"].update({"adresse": "1 rue des Fleurs", "code_postal": "75001", "pays": "France",
                           "date_naissance": "1990-12-10", "disponibilite": "immédiate", "permis": ""})


def test_nouveaux_champs_du_profil():
    assert cv.profile_value(PROFIL, "adresse") == "1 rue des Fleurs"
    assert cv.profile_value(PROFIL, "code postal") == "75001"
    assert cv.profile_value(PROFIL, "naissance") == "10/12/1990"     # format des formulaires français
    assert cv.profile_value(PROFIL, "salaire") is None                 # absent : rien n'est écrit
    assert cv.profile_value(PROFIL, "permis") is None                  # vide
    assert cv.profile_value({"identity": {"date_naissance": "10 déc."}}, "naissance") == "10 déc."


def test_profil_lu_une_seule_fois_par_ouverture():
    c, core, faux, ecrit = _depot()
    for w in ("mail", "pays", "code postal"):
        c.ask(w, 0.0)
        _attendre(c, core)
    assert [e[0] for e in ecrit] == ["ada@exemple.fr", "France", "75001"]
    assert len([x for x in faux.calls if x[1] == "/api/profile"]) == 1
    c.actions([("cand_off",)], core, 0.0)                              # fermé : relu à la réouverture
    assert c.profile is None


def test_champ_pas_ecrit_si_le_navigateur_n_est_plus_devant():
    c, core, faux, ecrit = _depot(navigateur=False)
    c.ask("mail", 0.0)
    st = _attendre(c, core)
    assert ecrit == [] and "navigateur n'est plus devant" in st["lines"][0]


def test_tab_appuie_sur_la_touche_sans_cvgen():
    touches = []
    faux = FauxCvgen()
    c = cv.Candidature(http=faux, launch=lambda: None, press=touches.append)
    c.ask("tab", 0.0)
    assert touches == ["tab"] and faux.calls == [] and not c.busy


def test_mots_en_deux_morceaux_recolles():
    from motionzero.voice import GRAMMARS, _join_demute
    w = [{"word": "code", "conf": 1, "start": 0, "end": 1}, {"word": "postal", "conf": 0.9, "start": 1, "end": 2}]
    assert [x["word"] for x in _join_demute(w)] == ["code postal"]
    assert "code postal" in GRAMMARS["candidature"] and "code postal" not in GRAMMARS["base"]
    assert "prépare tout" not in GRAMMARS["chrome"]


# ---- « prépare tout » (#72), reprise après relance (#63)
class FauxFile(FauxCvgen):
    """Deux offres à vérifier ; chaque préparation finit « prête » au premier suivi."""
    def __init__(self, en_cours_id=None, **kw):
        super().__init__(**kw)
        self.en_cours_id = en_cours_id

    def __call__(self, method, path, body=None):
        if path == "/api/offres":
            self.calls.append((method, path))
            return [_offre("v1", "generee", 4.0), _offre("v2", "generee", 3.0), _offre("t1", "a-trier", 3.0)]
        if path == "/api/preparation":
            self.calls.append((method, path))
            return {"offreId": self.en_cours_id}
        if method == "GET" and path.startswith("/api/offres/v"):
            self.calls.append((method, path))
            return {"preparation": {"etape": "pret"}}
        return super().__call__(method, path, body)


def _file(**kw):
    faux = FauxFile(**kw)
    c = cv.Candidature(http=faux, launch=lambda: None)
    c.sleep = lambda s: None
    core = Core(Config())
    return c, core, faux


def test_prepare_tout_enchaine_les_offres():
    c, core, faux = _file()
    c.ask("liste", 0.0)
    _attendre(c, core)
    c.ask("prépare tout", 0.0)
    for _ in range(300):
        c.events(core, 0.0)
        if c.preparing is None and not c.todo and not c.busy:
            break
        time.sleep(0.01)
    prep = [x[1] for x in faux.calls if x[1].endswith("/preparer")]
    assert prep == ["/api/offres/v1/preparer", "/api/offres/v2/preparer"]   # l'une après l'autre, jamais t1


def test_prepare_tout_sans_liste_ou_sans_offre_prete():
    c, core, faux = _file()
    c.ask("prépare tout", 0.0)
    assert "Pas de liste" in c.state(0.0)["lines"][0]
    c.offres = [_offre("t1", "a-trier", 3.0)]
    c.ask("prépare tout", 0.0)
    assert "Rien à préparer" in c.state(0.0)["lines"][-1] and not c.busy


def test_preparation_reprise_apres_relance_d_iris():
    c, core, faux = _file(en_cours_id="v2")
    c.ask("état", 0.0)                             # ouverture du mode après une relance
    for _ in range(300):
        c.events(core, 0.0)
        if c.prep.get("v2") == cv.PREP_STEPS["pret"] and not c.busy:
            break
        time.sleep(0.01)
    assert c.prep.get("v2") == cv.PREP_STEPS["pret"] and c.preparing is None
    assert ("GET", "/api/offres/v2") in faux.calls                     # suivi repris
    c2, core2, faux2 = _file()                                         # rien en cours : pas de suivi
    c2.ask("état", 0.0)
    _attendre(c2, core2)
    assert not [x for x in faux2.calls if x[1] == "/api/offres/v2"]


def test_panneau_ville_teletravail_salaire():
    """#64 : ce que CVGEN lit dans l'annonce s'affiche ; contrat en français de CVGEN d'abord ; absents : rien."""
    import datetime as dt
    o = dict(_offre("v1", "generee", 4.0), contratLibelle="CDI", ville="Lyon", teletravail="Hybride",
             salaire="45 k€", contrat="FULL_TIME")
    chips = cv.offer_view([o], 0, dt.date(2026, 11, 24))["chips"]
    assert chips[:4] == ["CDI", "Lyon", "Hybride", "45 k€"]
    nu = cv.offer_view([dict(_offre("v1", "generee", 4.0), contrat="FULL_TIME", ville=None)], 0, dt.date(2026, 11, 24))
    assert nu["chips"][0] == "Temps plein" and None not in nu["chips"]


def test_etiquettes_sur_deux_lignes():
    from motionzero.ui import chip_rows
    w = lambda c: 10 * len(c)
    assert chip_rows(w, ["aaaa", "bbbb", "cccc"], 130) == [["aaaa", "bbbb"], ["cccc"]]
    assert chip_rows(w, ["a" * 50, "ok"], 130) == [["ok"]]           # trop longue : laissée de côté
    assert len(chip_rows(w, ["aaaaaaaaaa"] * 5, 130)) == 2           # jamais plus de deux lignes
    assert chip_rows(w, [], 130) == [[]]


# ---- #46 : question libre du formulaire ; #47 : brouillon d'e-mail
def test_question_lance_l_ecoute_puis_s_arrete_au_silence():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("candidature", 1.3)
    assert core.voice("question", 2.0) == [("open_start",)] and core.opening
    assert core.voice("garde", 2.5) == []                            # pendant la question : du texte
    assert core.open_tick(2.2, 2.0) == []
    assert core.open_tick(10.0, 3.0) == [("candq_stop",)] and not core.opening
    core.voice("question", 11.0)
    assert core.open_tick(60.0, 0.0) == [("open_cancel",)]           # rien dit : abandon
    assert "question annulee" in core.last_gesture[0]


class FauxLlm(FauxCvgen):
    def __init__(self, reponse="Réponse : J'aime vos projets.", texte="Écrire à jobs@acme.fr. Merci", **kw):
        super().__init__(**kw)
        self.reponse, self.texte = reponse, texte

    def __call__(self, method, path, body=None):
        if path == "/api/llm":
            self.calls.append((method, path, body))
            if isinstance(self.reponse, Exception):
                raise self.reponse
            return {"content": self.reponse}
        if path == "/api/profile":
            return PROFIL
        if method == "GET" and path.startswith("/api/offres/") and path != "/api/offres/compte":
            return {"texte": self.texte}
        if path.endswith("/en-cours"):
            return {"cv": self.cv_pdf, "lettre": None}
        return super().__call__(method, path, body)


def _q(faux, navigateur=True):
    ecrit = []
    c = cv.Candidature(http=faux, launch=lambda: None, typer=lambda s, enter=False: ecrit.append(s),
                       browser_front=lambda: navigateur, open_url=lambda p: ecrit.append(("ouvert", p)))
    core = Core(Config())
    c.ask("liste", 0.0)
    _attendre(c, core)
    return c, core, ecrit


def test_question_reponse_puis_ecris():
    faux = FauxLlm()
    c, core, ecrit = _q(faux)
    c.submit_question(b"audio", lambda a: "  Pourquoi notre entreprise ? ")
    st = _attendre(c, core)
    assert st["title"] == "Réponse proposée" and st["lines"][1] == "J'aime vos projets."
    prompt = faux.calls[-1][2]["messages"][0]["content"]
    assert "Pourquoi notre entreprise ?" in prompt and "jobs@acme.fr" in prompt
    assert "06 00 00 00 00" not in prompt and "1 rue des Fleurs" not in prompt   # rien de privé au modèle
    c.ask("écris", 0.0)
    assert ecrit == ["J'aime vos projets."]


def test_question_echecs():
    c, core, ecrit = _q(FauxLlm())
    c.ask("écris", 0.0)
    assert "Pas de réponse prête" in c.state(0.0)["lines"][0] and ecrit == []
    c.submit_question(b"", lambda a: "")                              # rien entendu
    assert "Rien compris" in _attendre(c, core)["lines"][0]
    c.submit_question(b"", lambda a: 1 / 0)                           # transcription en panne
    assert "Rien compris" in _attendre(c, core)["lines"][0]
    c2, core2, _ = _q(FauxLlm(reponse=cv.CvgenError("Ollama ne répond pas")))
    c2.submit_question(b"a", lambda a: "pourquoi nous ?")
    assert "Ollama" in _attendre(c2, core2)["lines"][0] and c2.reponse is None
    c3, core3, e3 = _q(FauxLlm(reponse="   "), navigateur=False)
    c3.submit_question(b"a", lambda a: "pourquoi nous ?")
    assert "Pas de réponse du modèle" in _attendre(c3, core3)["lines"][0]
    c3.reponse = "x"
    c3.ask("écris", 0.0)
    assert e3 == [] and "pas devant" in c3.state(0.0)["lines"][0]


def test_adresse_mail_de_l_annonce():
    assert cv.offer_email("Envoyez CV à rh.paris@acme-group.fr.") == "rh.paris@acme-group.fr"
    assert cv.offer_email("noreply@x.fr puis jobs@x.fr") == "jobs@x.fr"
    assert cv.offer_email("postulez sur le site") is None and cv.offer_email(None) is None


def test_brouillon_eml(tmp_path):
    import email
    pdf = tmp_path / "CV Ada.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")
    raw = cv.draft_eml("jobs@acme.fr", {"poste": "Dev", "entreprise": "ACME"}, PROFIL, [str(pdf)])
    m = email.message_from_bytes(raw)
    assert m["To"] == "jobs@acme.fr" and m["Subject"] == "Candidature : Dev" and m["X-Unsent"] == "1"
    noms = [p.get_filename() for p in m.walk() if p.get_filename()]
    assert noms == ["CV Ada.pdf"]


def test_brouillon_de_bout_en_bout_et_echecs(tmp_path):
    pdf = tmp_path / "CV.pdf"
    pdf.write_bytes(b"%PDF")
    faux = FauxLlm()
    faux.cv_pdf = str(pdf)
    c, core, ecrit = _q(faux)
    c.i = 2                                                           # v1 : CV prêt
    c.ask("brouillon", 0.0)
    st = _attendre(c, core)
    assert ecrit[-1][0] == "ouvert" and ecrit[-1][1].endswith(".eml") and "jobs@acme.fr" in st["lines"][-1]
    faux.texte = "postulez sur le site"                               # pas d'adresse
    c.ask("brouillon", 0.0)
    assert "Pas d'adresse" in _attendre(c, core)["lines"][-1]
    faux.texte, faux.cv_pdf = "jobs@acme.fr", None                    # pas de PDF
    c.ask("brouillon", 0.0)
    assert "Pas de PDF" in _attendre(c, core)["lines"][-1]
    c.i = 0                                                           # offre à trier : pas de CV
    c.ask("brouillon", 0.0)
    assert "dis « garde »" in c.state(0.0)["lines"][-1]


# ---- 24/11 : rien d'imprévu ne bloque le mode
def test_serveur_trop_lent_message_clair():
    import socket
    import threading as th
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)                                                     # accepte, ne répond jamais
    port = srv.getsockname()[1]
    try:
        with pytest.raises(cv.CvgenError, match="trop de temps"):
            cv._http("GET", "/api/health", base=f"http://127.0.0.1:{port}", timeout=0.5)
    finally:
        srv.close()
    assert cv.ROUTE_TIMEOUT_S["llm"] >= 60                            # le modèle a le temps de se réveiller


def test_question_sans_offre_affiche_l_attente_et_repond():
    faux = FauxLlm()
    c = cv.Candidature(http=faux, launch=lambda: None, browser_front=lambda: True, typer=lambda s, enter=False: None)
    c.submit_question(b"a", lambda a: "pourquoi nous ?")
    assert "sans offre affichée" in c.lines[0]                       # quelque chose à l'écran tout de suite
    st = _attendre(c, Core(Config()))
    assert st["title"] == "Réponse proposée"
    assert not [x for x in faux.calls if x[1].startswith("/api/offres/") and x[0] == "GET"]


def test_demande_perdue_debloquee():
    c = cv.Candidature(http=FauxCvgen(), launch=lambda: None)
    core = Core(Config())
    c.busy = True                                                     # aucune réponse n'arrivera
    c.events(core, 0.0)
    c.events(core, cv.BUSY_MAX_S - 1)
    assert c.busy
    c.events(core, cv.BUSY_MAX_S + 1)
    assert not c.busy and "n'a pas répondu" in c.lines[0]


def test_message_qui_plante_ne_bloque_pas():
    def boom(s, enter=False):
        raise OSError("clavier")
    c = cv.Candidature(http=FauxDepot(), launch=lambda: None, typer=boom, browser_front=lambda: True)
    core = Core(Config())
    c.ask("mail", 0.0)
    st = _attendre(c, core)
    assert not c.busy and "Erreur inattendue" in st["lines"][0]
    c.reponse = "x"
    assert c.actions([("cand", "écris")], core, 0.0) == []           # frappe en panne : dit, pas d'exception
    assert "n'a pas marché" in c.lines[0] and not c.busy
    c._q.put(("inconnu",))                                            # message inattendu : ignoré sans planter
    c.events(core, 0.0)
