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
    assert not core.dictating and core.confirming(8.0) and core.listening(8.0)
    assert core.voice("clic", 8.0) == []                          # pas d'autre commande pendant la confirmation
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
