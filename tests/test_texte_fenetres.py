"""Mots du check-up du 13/11 : sélection, coupe, efface, agrandis / réduis, gauche / droite."""
import json

from motionzero.config import Config
from motionzero.core import Core, Mode, VOICE_LABELS
from motionzero.output import VK
from motionzero.voice import GRAMMARS


def _say(core, word, t):
    core.voice("iris", t)
    return core.voice(word, t + 0.5)


def test_raccourcis_texte():
    core = Core(Config())
    assert _say(core, "sélection", 1) == [("hotkey", ["ctrl", "a"])]
    assert _say(core, "coupe", 3) == [("hotkey", ["ctrl", "x"])]
    assert _say(core, "efface", 5) == [("hotkey", ["ctrl", "backspace"])]


def test_fenetres():
    core = Core(Config())
    assert _say(core, "agrandis", 1) == [("window", "max")]   # plein écran, même après « gauche »
    assert _say(core, "réduis", 3) == [("hotkey", ["win", "down"])]
    assert _say(core, "gauche", 5) == [("hotkey", ["win", "left"])]
    assert _say(core, "droite", 7) == [("hotkey", ["win", "right"])]


def test_sans_iris_rien():
    core = Core(Config())
    for i, w in enumerate(("sélection", "coupe", "efface", "agrandis", "gauche")):
        assert core.voice(w, 1 + i) == [], w


def test_efface_repete_sans_iris():
    core = Core(Config())
    _say(core, "efface", 1)
    assert core.voice("efface", 2.0) == [("hotkey", ["ctrl", "backspace"])]
    assert core.voice("efface", 3.0) == [("hotkey", ["ctrl", "backspace"])]
    assert core.voice("coupe", 3.5) == []          # autre mot : fin de la répétition, « iris » redemandé
    assert core.voice("efface", 4.0) == []


def test_en_mode_chrome_agrandis_reste_le_zoom():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("chrome", 1.5)
    assert core.mode == Mode.CHROME
    assert core.voice("agrandis", 2.5) == [("chrome_keys", ["ctrl", "plus"])]
    assert core.voice("réduis", 3.0) == [("chrome_keys", ["ctrl", "minus"])]
    assert _say(core, "gauche", 4) == [("hotkey", ["win", "left"])]   # fenêtres : marche aussi en Chrome
    assert _say(core, "sélection", 6) == [("hotkey", ["ctrl", "a"])]


def test_mots_ecoutes_et_touches_connues():
    base = json.loads(GRAMMARS["base"])
    for w in ("sélection", "coupe", "efface", "agrandis", "réduis", "gauche", "droite", "plein écran"):
        assert w in base, w
    for w in ("sélection", "coupe", "efface", "réduis", "gauche", "droite"):
        assert w in VOICE_LABELS, w
    for k in ("x", "win", "backspace", "a"):
        assert k in VK


def test_calendrier_ouvert_gauche_ne_casse_rien():
    core = Core(Config())
    _say(core, "calendrier", 1)
    acts = _say(core, "gauche", 3)
    assert acts == [("hotkey", ["win", "left"])] or acts == [], acts   # jamais d'exception


def test_chaque_mot_ecoute_a_un_traitement():
    """Tables de commandes complètes : un mot ajouté au modèle sans traitement serait affiché sans rien faire."""
    from motionzero.calendar_view import WORDS as CAL
    from motionzero.core import ALIASES, CHROME_KEYS, COMMANDS, SIMPLE_ACTIONS, VOICE_HOTKEYS
    from motionzero.voice import WORDS
    special = {"iris", "stop", "skip", "back"}
    handled = set(COMMANDS) | set(SIMPLE_ACTIONS) | set(VOICE_HOTKEYS) | set(CHROME_KEYS) | set(ALIASES) | set(CAL)
    assert [w for w in WORDS if w not in handled | special] == []
    assert all(hasattr(Core, "_cmd_" + m) for m in COMMANDS.values())


def test_plein_ecran_partout_meme_en_chrome():
    core = Core(Config())
    assert _say(core, "plein écran", 1) == [("window", "max")]
    assert core.last_gesture[0] == "PLEIN ECRAN"
    core.voice("iris", 3.0)
    core.voice("chrome", 3.5)
    assert _say(core, "plein écran", 5) == [("window", "max")]
    assert core.voice("plein écran", 7.0) == []        # sans « iris » : rien


def test_plein_ecran_dit_en_deux_mots():
    from motionzero.voice import _join_demute as merge_words
    words = [{"word": "plein", "conf": 1.0, "start": 0.0, "end": 0.3},
             {"word": "écran", "conf": 0.9, "start": 0.3, "end": 0.6}]
    assert [w["word"] for w in merge_words(words)] == ["plein écran"]


def test_window_actions():
    from motionzero.fenetre import maximize_foreground, window_actions
    calls = []
    rest = window_actions([("window", "max"), ("hotkey", ["enter"])], maximize=lambda: calls.append(1))
    assert calls == [1] and rest == [("hotkey", ["enter"])]

    class NoWindow:
        def GetForegroundWindow(self):
            return 0
    assert maximize_foreground(NoWindow()) is False

    class Boom:
        def GetForegroundWindow(self):
            raise OSError("api")
    assert maximize_foreground(Boom()) is False      # jamais d'exception vers la boucle

    class Ok:
        shown = None
        def GetForegroundWindow(self):
            return 42
        def ShowWindow(self, h, n):
            Ok.shown = (h, n)
    assert maximize_foreground(Ok()) is True and Ok.shown == (42, 3)
