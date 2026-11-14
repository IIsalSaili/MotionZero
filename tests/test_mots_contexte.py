"""14/11 : mots à un seul sens, sans « iris » dans leur contexte, ignorés ailleurs."""
from motionzero.config import Config
from motionzero.core import Core, Mode, EDITOR_TABS


def _core(front=None):
    c = Core(Config())
    if front:
        c.front_app(front, 0.5)
    return c


def test_suivant_precedent_sans_iris_vscode_devant():
    c = _core("code.exe")
    assert c.voice("suivant", 1.0) == [("editor_tab", EDITOR_TABS["suivant"])]
    assert c.voice("précédent", 1.5) == [("editor_tab", EDITOR_TABS["précédent"])]


def test_suivant_seul_ignore_hors_vscode():
    for front in (None, "Discord.exe", "explorer.exe"):
        c = _core(front)
        assert c.voice("suivant", 1.0) == [], front
        assert not c.last_word[2]


def test_suivant_avec_iris_marche_toujours_hors_vscode():
    c = _core("Discord.exe")
    c.voice("iris", 1.0)
    assert c.voice("suivant", 1.2) == [("editor_tab", EDITOR_TABS["suivant"])]


def test_vscode_garde_par_fenetre_iris():
    """Une fenêtre d'Iris passe devant (raccourci Discord, aide) : VS Code reste l'appli de référence."""
    c = _core("code.exe")
    c.front_app("pythonw.exe", 0.8)
    assert c.voice("suivant", 1.0) == [("editor_tab", EDITOR_TABS["suivant"])]


def test_suivant_en_chrome_reste_onglet_chrome():
    c = _core("chrome.exe")
    assert c.mode == Mode.CHROME
    acts = c.voice("suivant", 1.0)
    assert acts and acts[0][0] == "chrome_keys"


def test_suivant_pendant_dictee_ignore():
    c = _core("code.exe")
    c.typing = True
    assert c.voice("suivant", 1.0) == []


def test_merci_ferme_sans_iris_si_affiche_partout():
    for front, w in (("code.exe", "merci"), ("code.exe", "ferme"), ("Discord.exe", "ferme"), (None, "merci")):
        c = _core(front)
        c.top_shown = True
        assert c.voice(w, 1.0) == [("rappel_merci",), ("ask_close",)], (front, w)


def test_merci_ferme_seuls_ignores_si_rien_affiche():
    for w in ("merci", "ferme"):
        c = _core("code.exe")
        assert c.voice(w, 1.0) == []
        assert not c.last_word[2]


def test_ferme_sans_iris_apres_heure():
    c = _core("code.exe")
    c.voice("iris", 1.0)
    c.voice("heure", 1.2)
    assert c.voice("ferme", 2.0) == [("rappel_merci",), ("ask_close",)]


def test_ferme_en_chrome_affichage_puis_onglet():
    c = _core("chrome.exe")
    c.top_shown = True
    assert c.voice("ferme", 1.0) == [("rappel_merci",), ("ask_close",)]
    c.top_shown = False
    acts = c.voice("ferme", 1.5)
    assert acts and acts[0][0] == "chrome_keys"


def test_plus_tard_sans_iris_seulement_rappel_affiche():
    c = _core()
    assert c.voice("plus tard", 1.0) == []
    c.reminder_shown = True
    assert c.voice("plus tard", 1.5) == [("rappel_tard",)]


def test_scroll_garde_iris():
    c = _core("code.exe")
    assert c.voice("scroll", 1.0) == []
