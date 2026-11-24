"""« iris question » avec recherche internet (navigateur headless) : tous les chemins, sans réseau."""
import base64
from motionzero import ask, web
from motionzero.ui import island_text


def test_requete_demandee():
    assert ask.search_query("RECHERCHE: météo Paris") == "météo Paris"
    assert ask.search_query("« recherche: psg »") == "psg"
    assert ask.search_query("La capitale est Canberra.") is None
    assert ask.search_query("RECHERCHE:") is None


def _asker(replies):
    calls = []
    def fake(question, system=""):
        calls.append(system)
        return replies.pop(0)
    return fake, calls


def test_reponse_directe_un_seul_appel():
    fake, calls = _asker(["Canberra."])
    assert ask.answer_question("capitale ?", ask=fake, research=lambda q: 1 / 0) == "Canberra."
    assert len(calls) == 1


def test_recherche_puis_reponse_avec_les_pages():
    fake, calls = _asker(["RECHERCHE: psg", "Le PSG a gagné 1-0."])
    seen = []
    out = ask.answer_question("psg ?", ask=fake, research=lambda q: "PAGE PSG " + q, on_search=seen.append)
    assert out == "Le PSG a gagné 1-0." and seen == ["psg"]
    assert "PAGE PSG psg" in calls[1]


def test_recherche_en_panne_reponse_sans_internet():
    fake, calls = _asker(["RECHERCHE: psg", "La recherche a échoué ; de mémoire…"])
    def boom(q):
        raise web.WebError("aucun moteur")
    assert ask.answer_question("psg ?", ask=fake, research=boom).startswith("La recherche a échoué")
    assert "a échoué" in calls[1]


def test_pas_de_boucle_si_il_redemande():
    fake, _ = _asker(["RECHERCHE: psg", "RECHERCHE: psg encore"])
    assert "pas trouvé" in ask.answer_question("psg ?", ask=fake, research=lambda q: "rien")


def test_liens_bing_et_nettoyage():
    u = "a1" + base64.urlsafe_b64encode(b"https://meteofrance.com/paris").decode().rstrip("=")
    assert web.bing_target(f"https://www.bing.com/ck/a?!&&p=x&u={u}&ntb=1") == "https://meteofrance.com/paris"
    assert web.bing_target("https://exemple.fr/a") == "https://exemple.fr/a"
    assert web.clean("  a\n\n bonjour   le\xa0monde \n", 100) == "bonjour le monde"
    assert len(web.clean("x" * 50, 10)) == 10


def test_bandeau_recherche():
    assert island_text({"mode": "NEUTRE", "qa": {"phase": "searching"}})[1] == "Recherche sur internet…"
