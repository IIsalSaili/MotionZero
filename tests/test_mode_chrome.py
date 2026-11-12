"""Mode CHROME : « iris chrome » l'active, commandes à la voix avec « iris », quitté quand Chrome n'est plus devant."""
from motionzero.config import Config
from motionzero.core import Core, Mode


def _chrome():
    core = Core(Config())
    core.voice("iris", 1.0)
    acts = core.voice("chrome", 1.5)
    assert ("open_app", "chrome") in acts and core.mode == Mode.CHROME
    return core


def test_iris_chrome_active_le_mode():
    _chrome()


def test_commande_avec_iris():
    core = _chrome()
    core.voice("iris", 2.0)
    assert core.voice("retour", 2.5) == [("chrome_keys", ["alt", "left"])]
    core.voice("iris", 3.0)
    assert core.voice("suivant", 3.5) == [("chrome_keys", ["ctrl", "tab"])]   # mot du calendrier, ici l'onglet


def test_sans_iris_rien():
    core = _chrome()
    assert core.voice("retour", 2.5) == []
    assert core.voice("ferme", 3.0) == []


def test_une_seule_commande_par_iris():
    core = _chrome()
    core.voice("iris", 2.0)
    core.voice("descends", 2.5)
    assert core.voice("descends", 3.0) == []


def test_hors_mode_chrome_les_mots_ne_font_rien():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("retour", 1.5) == []
    assert "seulement en mode Chrome" in core.last_gesture[0]
    core.voice("iris", 2.0)
    assert core.voice("suivant", 2.5) == []     # calendrier fermé, pas Chrome : ignoré


def test_ferme_garde_son_sens_hors_chrome():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert ("open_start",) in core.voice("ferme", 1.5)


def test_ferme_l_onglet_en_mode_chrome():
    core = _chrome()
    core.voice("iris", 2.0)
    assert core.voice("ferme", 2.5) == [("chrome_keys", ["ctrl", "w"])]


def test_recherche_ouvre_la_dictee():
    core = _chrome()
    core.voice("iris", 2.0)
    acts = core.voice("recherche", 2.5)
    assert acts == [("chrome_keys", ["ctrl", "l"]), ("type_start",)] and core.typing


def test_quitte_quand_chrome_n_est_plus_devant():
    core = _chrome()
    assert core.chrome_front(True, 2.0) == []
    acts = core.chrome_front(False, 2.3)
    assert ("mode", Mode.NEUTRAL) in acts and core.mode == Mode.NEUTRAL


def test_delai_d_ouverture_de_chrome():
    core = _chrome()                                  # Chrome pas encore devant (il s'ouvre)
    assert core.chrome_front(False, 3.0) == [] and core.mode == Mode.CHROME
    core.chrome_front(False, 7.0)                     # jamais venu : on abandonne
    assert core.mode == Mode.NEUTRAL


def test_stop_et_autre_appli_quittent_le_mode():
    core = _chrome()
    core.voice("stop", 2.0)
    assert core.mode == Mode.NEUTRAL
    core = _chrome()
    core.voice("iris", 2.0)
    core.voice("discord", 2.5)
    assert core.mode == Mode.NEUTRAL


def test_chrome_front_hors_mode_ne_fait_rien():
    core = Core(Config())
    assert core.chrome_front(False, 1.0) == [] and core.mode == Mode.NEUTRAL


def test_touches_envoyees_seulement_si_chrome_devant(monkeypatch):
    from motionzero import app
    core = _chrome()
    monkeypatch.setattr("motionzero.app.chrome_in_front", lambda: False)
    rest = app.vscode_actions([("chrome_keys", ["f5"])], core, None, None, 3.0)
    assert rest == [] and "PAS DEVANT" in core.last_gesture[0]
    monkeypatch.setattr("motionzero.app.chrome_in_front", lambda: True)
    assert app.vscode_actions([("chrome_keys", ["f5"])], core, None, None, 3.0) == [("hotkey", ["f5"])]


def test_toutes_les_touches_existent():
    from motionzero.core import CHROME_KEYS
    from motionzero.output import VK
    for keys in CHROME_KEYS.values():
        assert all(k in VK for k in keys), keys
