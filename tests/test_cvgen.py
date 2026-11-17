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
    assert _attendre(c, core)["lines"][1] == "2 à vérifier"
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
    assert _attendre(c, Core(Config()))["title"] == "Candidature" and lances == [1]


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
        cv._http("GET", "/api/health", base="http://127.0.0.1:9", timeout=0.5)


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


def test_mode_s_eteint_seul_et_se_prolonge():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("candidature", 1.3)
    assert not core.cand_on(1.3 + CAND_IDLE_S + 1)
    core.voice("état", 100.0)
    assert core.cand_on(100.0 + CAND_IDLE_S - 1)


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
    assert "Gardée" in st["lines"][-1] and st["lines"][0] == "Poste t1 · ACME"   # la suivante vient d'elle-même
    c.ask("écarte", 0.0)
    _attendre(c, core)
    assert ("PATCH", "/api/offres/t1", {"etat": "ecartee"}) in faux.calls
    assert [o["id"] for o in c.offres] == ["v1"]


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
    assert "« montre »" in pret and "« lien »" in pret
    assert "« lien »" in cv.next_hint({"etat": "generee", "preparation": {"etape": "pret"}})
    assert "« liste »" in cv.next_hint(None)
    for h in (cv.next_hint(None), pret):
        assert len(h) <= 60 and "« aide »" in h                    # court : sinon rétréci, illisible


def test_carte_apres_preparation_propose_la_suite():
    c, core, faux = _sur_v1()
    c.ask("prépare", 0.0)
    st = _fin_prep(c, core)
    assert "« montre »" in st["meta"] and "« lien »" in st["meta"]
