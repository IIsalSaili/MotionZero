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


def test_appli_favorite_seulement_avec_iris():
    core = Core(Config())
    core.app_words = {"steam", "bloc notes"}
    assert core.voice("steam", 1.0) == []
    core.voice("iris", 2.0)
    assert core.voice("bloc notes", 2.5) == [("open_fav", "bloc notes")]


def test_ouvre():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("ouvre", 1.5) == [("open_start",)]
    assert core.voice("clic", 2.0) == []
    assert core.open_tick(4.3, last_speech_t=3.0) == [("open_stop",)]


def test_voix_appli_en_deux_mots():
    from motionzero import voice
    voice.set_app_words(["bloc notes", "steam"])
    w = lambda x, c=0.95: {"word": x, "conf": c, "start": 0, "end": 0.1}
    got = voice.accepted_words({"result": [w("iris"), w("bloc"), w("notes")]})
    assert [x["word"] for x in got] == ["iris", "bloc notes"]
    assert voice.accepted_words({"result": [w("steam")]}) == []      # sans « iris » : jamais


def test_rapprochement():
    from motionzero.apps import best_match
    apps = {"Bloc-notes": "a", "Calculatrice": "b", "DaVinci Resolve": "c", "Gestionnaire des tâches": "d"}
    assert best_match("Bloc-notes.", apps) == "Bloc-notes"
    assert best_match("le gestionnaire des tâches", apps) == "Gestionnaire des tâches"
    assert best_match("truc machin", apps) is None
