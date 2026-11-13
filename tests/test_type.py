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


class _FakeAsker:
    def __init__(self, text=None, error=False):
        self.text, self.error = text, error

    def _transcribe(self, audio, sr):
        if self.error:
            raise RuntimeError("whisper en panne")
        return self.text


def _launcher(asker, apps):
    from motionzero.apps import Launcher
    got = []
    la = Launcher.__new__(Launcher)
    la.all, la.recent, la.asker, la.on_message = apps, [], asker, got.append
    return la, got


def test_ouvre_appli_inconnue_ne_plante_pas():
    la, got = _launcher(_FakeAsker("J'ai force expérience."), {"Calculatrice": "x", "Steam": "y"})
    la._open_spoken(b"")
    assert got and got[0].startswith("PAS COMPRIS")


def test_ouvre_rien_entendu_ou_whisper_en_panne():
    for asker in (_FakeAsker(""), _FakeAsker(error=True)):
        la, got = _launcher(asker, {"Steam": "y"})
        la._open_spoken(b"")
        assert got == ["PAS COMPRIS : rien entendu"]


def test_ouvre_liste_pas_prete():
    la, got = _launcher(_FakeAsker("steam"), {})
    la._open_spoken(b"")
    assert got == ["LISTE DES APPLIS PAS PRETE"]


def test_ouvre_lancement_qui_echoue(monkeypatch):
    from motionzero import apps
    monkeypatch.setattr(apps, "open_entry", lambda n, a: (_ for _ in ()).throw(OSError("non")))
    la, got = _launcher(_FakeAsker("steam"), {"Steam": "y"})
    la._open_spoken(b"")
    assert got and "ECHEC" in got[0]


def test_ferme_avec_nom():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("ferme", 1.5) == [("ask_close",), ("open_start",)]
    assert core.voice("clic", 2.0) == []
    assert core.open_tick(4.3, last_speech_t=3.0) == [("close_stop",)]


def test_ferme_seul_retire_juste_la_reponse():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("ferme", 1.5)
    assert core.open_tick(3.0, last_speech_t=0.0) == []
    assert core.open_tick(4.1, last_speech_t=0.0) == [("open_cancel",)]
    assert not core.opening
    core.voice("iris", 5.0)
    assert core.voice("clic", 5.5) == [("click", "left")]       # les commandes remarchent


def test_ferme_appli_pas_ouverte_ou_inconnue(monkeypatch):
    from motionzero import apps
    monkeypatch.setattr(apps, "find_window", lambda n, a: None)
    la, got = _launcher(_FakeAsker("steam"), {"Steam": "y"})
    la._spoken(b"", la._close)
    assert got == ["STEAM N'EST PAS OUVERT"]
    la, got = _launcher(_FakeAsker("blabla truc"), {"Steam": "y"})
    la._spoken(b"", la._close)
    assert got[0].startswith("PAS COMPRIS")


def test_rapprochement_articles_et_debut_du_nom():
    from motionzero.apps import best_match
    apps = {"Bloc-notes": "a", "Explorateur de fichiers": "b", "Calculatrice": "c", "Paramètres": "d"}
    assert best_match("la calculatrice", apps) == "Calculatrice"
    assert best_match("l'explorateur", apps) == "Explorateur de fichiers"
    assert best_match("les paramètres.", apps) == "Paramètres"
    assert best_match("la", apps) is None
