"""« iris type » : dictée écrite au curseur, coupure au silence, puis 3 s pour « envoie » / « annule »."""
from motionzero.config import Config
from motionzero.core import Core


def _typed():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("type", 2.0) == [("type_start",)] and core.typing
    assert core.voice("clic", 3.0) == []                              # pendant la dictée : du texte
    assert core.type_tick(5.9, last_speech_t=4.0) == []
    assert core.type_tick(6.05, last_speech_t=4.0) == [("type_stop",)]  # 2 s de silence
    assert not core.typing and core.confirming(7.0)
    return core


def test_envoie():
    assert _typed().voice("envoie", 8.0) == [("type_send",)]


def test_iris_envoie():
    core = _typed()
    core.voice("iris", 8.0)
    assert core.voice("envoie", 8.5) == [("type_send",)]


def test_annule():
    assert _typed().voice("annule", 8.0) == [("type_erase",)]


def test_apres_3_s_rien():
    core = _typed()
    assert not core.confirming(10.0)
    assert core.voice("envoie", 10.0) == []           # mot seul, écoute fermée : ignoré


def test_autre_commande_termine_l_attente():
    core = _typed()
    core.voice("iris", 7.5)
    assert core.voice("copie", 8.0) == [("hotkey", ["ctrl", "c"])]
    assert not core.confirming(8.1)


def test_rien_dit():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("type", 2.0)
    assert core.type_tick(10.5, last_speech_t=0.0) == [("type_cancel",)]


def test_espace_et_space():
    for word in ("espace", "space"):
        core = Core(Config())
        core.voice("iris", 1.0)
        assert core.voice(word, 1.5) == [("hotkey", ["space"])]
