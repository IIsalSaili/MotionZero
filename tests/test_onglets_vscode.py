"""« iris suivant / précédent » hors Chrome : onglets de VS Code (onglets Claude), 13/11."""
from motionzero.config import Config
from motionzero.core import Core, Mode


def say(core, word, t):
    core.voice("iris", t)
    return core.voice(word, t + 0.3)


def test_iris_suivant_precedent_hors_chrome():
    core = Core(Config())
    assert say(core, "suivant", 1.0) == [("editor_tab", ["ctrl", "pagedown"])]
    assert say(core, "précédent", 2.0) == [("editor_tab", ["ctrl", "pageup"])]


def test_sans_iris_rien():
    core = Core(Config())
    assert core.voice("suivant", 1.0) == []


def test_mode_chrome_garde_les_onglets_de_chrome():
    core = Core(Config())
    say(core, "chrome", 1.0)
    assert core.mode == Mode.CHROME
    assert say(core, "suivant", 2.0) == [("chrome_keys", ["ctrl", "tab"])]


def test_calendrier_garde_ses_semaines():
    core = Core(Config())
    say(core, "calendrier", 1.0)
    assert core.voice("suivant", 2.0) == [("cal", "suivant")]


def test_touche_envoyee_seulement_si_vscode_devant(monkeypatch):
    """Premier plan jugé par le programme (code.exe), plus par le titre (14/11)."""
    import motionzero.app as app
    import motionzero.vscode as vs
    core = Core(Config())
    devant = {"exe": "code.exe"}
    monkeypatch.setattr(vs, "vscode_in_front", lambda: devant["exe"] == "code.exe")
    monkeypatch.setattr(vs, "foreground_exe", lambda: devant["exe"])
    monkeypatch.setattr(vs, "find_window", lambda *a: 42)
    acts = [("editor_tab", ["ctrl", "pagedown"])]
    assert app.vscode_actions(acts, core, None, None, 1.0) == [("hotkey", ["ctrl", "pagedown"])]
    devant["exe"] = "chrome.exe"                   # Chrome devant : rien n'est envoyé
    assert app.vscode_actions(acts, core, None, None, 2.0) == []
    assert "PAS DEVANT" in core.last_gesture[0]
