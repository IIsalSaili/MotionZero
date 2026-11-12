"""Dictée Claude dans VS Code : « iris », « claude », coupure au silence, « envoie » / « annule ». Sans micro."""
from motionzero.config import Config
from motionzero.core import Core

TOGGLE = [("vscode_dictation",)]


def _start():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("claude", 2.0) == TOGGLE and core.dictating
    return core


def test_claude_sans_iris_ne_fait_rien():
    core = Core(Config())
    assert core.voice("claude", 1.0) == [] and not core.dictating


def test_pendant_la_dictee_les_mots_ne_declenchent_rien():
    core = _start()
    for word in ("clic", "menu", "copie", "pause", "stop", "iris", "envoie"):
        assert core.voice(word, 3.0) == [], word
    assert core.dictating


def test_le_micro_reste_allume_tant_qu_on_parle():
    core = _start()
    # on parle 40 s d'affilée (dernière parole toujours récente) : jamais coupé, pas de durée maximale
    for t in range(3, 43):
        assert core.dictation_tick(float(t), last_speech_t=t - 0.5) == []
    assert core.dictating


def test_coupe_apres_le_silence_puis_envoie():
    core = _start()
    assert core.dictation_tick(6.5, last_speech_t=4.0) == []      # 2,5 s de silence (pause pour réfléchir) : on attend
    assert core.dictation_tick(6.85, last_speech_t=4.0) == TOGGLE  # 2,85 s : micro coupé
    assert not core.dictating and core.confirming(8.0)
    assert core.voice("clic", 8.0) == []                          # mot seul sans « iris » : ignoré
    assert core.voice("envoie", 9.0) == [("vscode_keys", [["enter"]])]
    assert not core.confirming(9.1)


def test_annule_vide_le_champ():
    core = _start()
    core.dictation_tick(8.0, last_speech_t=4.0)
    assert core.voice("annule", 9.0) == [("vscode_keys", [["ctrl", "a"], ["backspace"]])]


def test_la_fin_du_mot_claude_ne_compte_pas_comme_parole():
    core = _start()
    assert core.dictation_tick(5.0, last_speech_t=2.3) == []      # écho de « claude » : on attend toujours


def test_rien_dit_du_tout():
    core = _start()
    assert core.dictation_tick(10.5, last_speech_t=0.0) == TOGGLE
    assert not core.dictating and not core.confirming(11.0)


def test_sans_reponse_la_confirmation_expire():
    core = _start()
    core.dictation_tick(8.0, last_speech_t=4.0)
    assert not core.confirming(40.0)
    assert core.voice("envoie", 40.0) == []  # écoute fermée : ignoré


def test_apres_la_dictee_aucune_commande_n_est_bloquee():
    """Demande de l'utilisateur : le message dicté pas encore envoyé ne doit bloquer aucune commande."""
    core = _start()
    core.dictation_tick(8.0, last_speech_t=4.0)            # micro coupé : envoie / annule possibles
    core.voice("iris", 9.0)
    assert ("open_app", "chrome") in core.voice("chrome", 9.2)
    assert core.voice("envoie", 9.5) == [("vscode_keys", [["enter"]])]   # sans « iris » : marche encore


def test_iris_envoie_et_iris_annule_a_tout_moment():
    """Sans « iris claude » avant : « iris envoie » = touche Entrée dans la fenêtre active, pas VS Code."""
    from motionzero.config import Config
    from motionzero.core import Core
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("envoie", 1.5) == [("hotkey", ["enter"])]
    core.voice("iris", 2.0)
    assert core.voice("annule", 2.5) == [("annule",)]


def test_iris_skip_et_back():
    """« iris skip » / « iris back » : une flèche droite / gauche dans la fenêtre active."""
    from motionzero.config import Config
    from motionzero.core import Core
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("skip", 1.5) == [("hotkey", ["right"])]
    core.voice("iris", 2.0)
    assert core.voice("back", 2.5) == [("hotkey", ["left"])]
    assert core.voice("skip", 10.0) == []          # sans « iris » : ignoré


def test_skip_repete_sans_iris():
    """Après « iris skip » : « skip » / « back » seuls marchent tant qu'ils arrivent à moins de 2 s d'écart."""
    from motionzero.config import Config
    from motionzero.core import Core
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("skip", 1.5) == [("hotkey", ["right"])]
    assert core.voice("skip", 3.0) == [("hotkey", ["right"])]      # 1,5 s après : marche
    assert core.voice("skip", 4.8) == [("hotkey", ["right"])]      # la fenêtre a été relancée
    assert core.voice("back", 6.0) == [("hotkey", ["left"])]       # back aussi
    assert core.voice("skip", 8.5) == []                            # plus de 2 s : fini


def test_skip_puis_autre_mot():
    """Un autre mot coupe la répétition : il suit le comportement habituel (sans « iris » : ignoré)."""
    from motionzero.config import Config
    from motionzero.core import Core
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("skip", 1.5)
    assert core.voice("clic", 2.0) == []                            # sans « iris » : ignoré
    assert core.voice("skip", 2.5) == []                            # la répétition est finie
    core.voice("iris", 5.0)
    assert core.voice("clic", 5.5) == [("click", "left")]           # « iris clic » : normal


def test_skip_seul_sans_iris_avant():
    from motionzero.config import Config
    from motionzero.core import Core
    assert Core(Config()).voice("skip", 1.0) == []


def test_envoye_synonyme_de_envoie():
    """« envoyé » fait partout la même chose qu'« envoie »."""
    from motionzero.config import Config
    from motionzero.core import Core
    from motionzero.voice import GRAMMAR
    assert "envoyé" in GRAMMAR
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("envoyé", 1.5) == [("hotkey", ["enter"])]          # touche Entrée
    core.dictating = True
    core.dictation_tick(10.0, last_speech_t=4.0)                         # après « iris claude »
    core.dictating = False
    core.ask_confirm("claude", 20.0, 30.0)
    assert core.voice("envoyé", 21.0) == [("vscode_keys", [["enter"]])]   # message de Claude, sans « iris »
    core.ask_confirm("rappel", 30.0, 20.0)
    assert core.voice("envoyé", 31.0) == [("rappel_ok",)]                # validation d'un rappel
