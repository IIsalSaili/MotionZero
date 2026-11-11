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


def test_slash():
    from motionzero.typer import spoken_symbols
    assert spoken_symbols("Slash clear.") == "/clear"
    assert spoken_symbols("slash, Compact") == "/compact"
    assert spoken_symbols("Slash code-review high.") == "/code-review high"
    assert spoken_symbols("un texte normal.") == "un texte normal."
    assert spoken_symbols("et/ou slash fin") == "et/ou /fin"


def test_nom_d_appli_seul_ne_fait_rien():
    from motionzero import voice
    assert "steam" not in voice.WORDS and "ouvre" in voice.WORDS   # seul « iris ouvre » ouvre une appli


def test_ouvre():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("ouvre", 1.5) == [("open_start",)]
    assert core.voice("clic", 2.0) == []
    assert core.open_tick(4.3, last_speech_t=3.0) == [("open_stop",)]


def test_rapprochement():
    from motionzero.apps import best_match
    apps = {"Bloc-notes": "a", "Calculatrice": "b", "DaVinci Resolve": "c", "Gestionnaire des tâches": "d"}
    assert best_match("Bloc-notes.", apps) == "Bloc-notes"
    assert best_match("le gestionnaire des tâches", apps) == "Gestionnaire des tâches"
    assert best_match("truc machin", apps) is None
