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
    for name, (method, path) in cv.ROUTES.items():
        motif = re.escape(path.replace("/", "\\/")).replace(re.escape("{id}"), re.escape("[^/]+"))
        assert re.search(rf"\['{method}', /\^{motif}\$/", src), name


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
    return {"id": id, "etat": etat, "poste": f"Poste {id}", "entreprise": "ACME", "source": "apec", "url": url,
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
