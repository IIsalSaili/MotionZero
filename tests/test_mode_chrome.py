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


def test_mots_chrome_sans_iris():
    core = _chrome()
    assert core.voice("retour", 2.5) == [("chrome_keys", ["alt", "left"])]
    assert core.voice("descends", 3.0) == [("chrome_keys", ["pagedown"])]
    assert core.voice("ferme", 3.5) == [("chrome_keys", ["ctrl", "w"])]


def test_autres_commandes_gardent_iris_en_mode_chrome():
    core = _chrome()
    assert core.voice("copie", 2.5) == []
    core.voice("iris", 3.0)
    assert core.voice("copie", 3.5) == [("hotkey", ["ctrl", "c"])]


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


def test_mots_chrome_absents_de_la_liste_de_base():
    import json
    from motionzero.core import CHROME_KEYS
    from motionzero.voice import GRAMMARS
    base, chrome = json.loads(GRAMMARS["base"]), json.loads(GRAMMARS["chrome"])
    for w in ("haut", "bas", "retour", "recharge", "agrandis", "descends"):
        assert w not in base and w in chrome, w
    assert all(w in chrome for w in CHROME_KEYS)
    assert all(w in chrome for w in base)          # en mode Chrome, les commandes habituelles restent


def test_changement_de_liste_dans_le_fil_voix():
    from motionzero.voice import GRAMMARS, VoiceListener

    class Rec:
        def __init__(self):
            self.grammars = []

        def SetGrammar(self, g):
            self.grammars.append(g)

        def Reset(self):
            pass

        def AcceptWaveform(self, b):
            return False

        def PartialResult(self):
            return '{"partial": ""}'

    v = VoiceListener("x")
    v.rec, v.free = Rec(), Rec()
    v._free_final, v._free_until, v._was_muted, v.samples = (0.0, ""), 0.0, False, 0
    from collections import deque
    v._free_pre = deque(maxlen=10)
    v.grammar = "chrome"
    v.audio.put(b"\x00\x00" * 480)
    v._step()
    assert v.rec.grammars == [GRAMMARS["chrome"]] and v._grammar == "chrome"
    v.grammar = "inconnue"                         # nom inconnu : on garde la liste en place
    v.audio.put(b"\x00\x00" * 480)
    v._step()
    assert v.rec.grammars == [GRAMMARS["chrome"]]


def test_clic_et_double_sans_iris_en_mode_chrome():
    core = _chrome()
    assert core.voice("clic", 2.5) == [("click", "left")]
    assert core.voice("double", 3.0) == [("click", "left"), ("click", "left")]


def test_clic_garde_iris_hors_chrome():
    core = Core(Config())
    assert core.voice("clic", 1.0) == []
