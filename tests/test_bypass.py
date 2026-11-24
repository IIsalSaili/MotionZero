"""« iris bypass » (17/11) : mots acceptés même mal dits, sauf les définitifs ; s'ajoute au focus."""
from motionzero.config import Config
from motionzero.core import BYPASS_IDLE_S, Core
from motionzero.ui import island_text
from motionzero.voice import BYPASS_EXCLUDED, accepted_words, confirmed


def _res(*words):
    return {"result": [{"word": w, "conf": c, "start": i * 0.4, "end": i * 0.4 + 0.3}
                       for i, (w, c) in enumerate(words)]}


def test_commande_mal_dite_acceptee_en_bypass_seulement():
    r = _res(("iris", 0.9), ("pause", 0.45))
    assert accepted_words(r) == []
    assert [w["word"] for w in accepted_words(r, bypass=True)] == ["iris", "pause"]
    assert accepted_words(_res(("iris", 0.9), ("pause", 0.3)), bypass=True) == []   # trop flou : non


def test_mot_seul_en_focus():
    r = _res(("clic", 0.6))
    assert accepted_words(r) == []
    assert [w["word"] for w in accepted_words(r, bypass=True)] == ["clic"]
    assert accepted_words(_res(("clic", 0.5)), bypass=True) == []


def test_mots_definitifs_gardent_le_seuil_normal():
    for w in ("ferme", "envoie", "annule", "efface", "stop", "recharge"):
        assert w in BYPASS_EXCLUDED
        assert accepted_words(_res(("iris", 0.9), (w, 0.45)), bypass=True) == []
        assert accepted_words(_res((w, 0.6)), bypass=True) == []


def test_pas_de_deuxieme_verification_sauf_definitifs():
    words = [{"word": "iris", "conf": 0.9}, {"word": "pause", "conf": 0.5}]
    long_text = "on parlait de la pause de midi hier avec les autres"
    assert not confirmed(words, long_text, n_heard=8)
    assert confirmed(words, long_text, n_heard=8, bypass=True)
    ferme = [{"word": "iris", "conf": 0.9}, {"word": "ferme", "conf": 0.9}]
    assert not confirmed(ferme, long_text, n_heard=8, bypass=True)


def test_iris_bypass_allume_eteint_et_s_ajoute_au_focus():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("focus", 1.3)
    core.voice("iris", 2.0)
    core.voice("bypass", 2.3)
    assert core.bypass_on(3.0) and core.focus_on(3.0)
    assert island_text({"mode": "NEUTRE", "focus": True, "bypass": True})[0] == "FOCUS · BYPASS"   # deux mots max
    core.voice("bypass", 4.0)                      # en focus : redit sans « iris », il s'éteint
    assert not core.bypass_on(5.0) and core.focus_on(5.0)


def test_bypass_ne_s_eteint_jamais_seul():
    core = Core(Config())                          # 19/11 : éteint seulement par « bypass » redit
    core.voice("iris", 1.0)
    core.voice("bypass", 1.3)
    assert core.bypass_on(1.3 + 24 * 3600)
    core.voice("iris", 100.0)
    core.voice("bypass", 100.3)
    assert not core.bypass_on(101.0)
