"""« iris alt-tab » (#75) : fenêtre d'avant, liste numérotée en haut, chiffres sans « iris »."""
import json

from motionzero.alttab import list_text, number_of, window_labels
from motionzero.config import Config
from motionzero.core import Core


def _alttab(core, t=1.0):
    core.voice("iris", t)
    return core.voice("alt-tab", t + 0.5)


def test_chiffre_pendant_la_liste_sans_iris():
    core = Core(Config())
    assert _alttab(core) == [("alt_tab", 2)]
    assert core.voice("trois", 3.0) == [("alt_tab", 3)]
    assert core.voice("quatre", 5.0) == [("alt_tab", 4)]   # la liste reste : on peut enchaîner


def test_chiffre_apres_la_liste_ignore():
    core = Core(Config())
    _alttab(core)
    assert core.voice("trois", 20.0) == []


def test_chiffre_sans_alt_tab_ignore():
    core = Core(Config())
    assert core.voice("trois", 1.0) == []


def test_ferme_retire_la_liste():
    core = Core(Config())
    _alttab(core)
    core.voice("merci", 2.5)
    assert t_closed(core, 3.0)
    assert core.voice("trois", 3.0) == []


def t_closed(core, t):
    return t >= core.alttab_until


def test_alt_tab_trois_d_un_trait():
    core = Core(Config())
    core.voice("iris", 1.0)
    assert core.voice("alt-tab trois", 1.4) == [("alt_tab", 3)]


def test_stop_reste_prioritaire_pendant_la_liste():
    core = Core(Config())
    _alttab(core)
    assert ("release_all", "force") in core.voice("stop", 2.5)


def test_accepted_words_recolle_alt_tab_et_le_chiffre():
    from motionzero.voice import accepted_words
    w = lambda word, s, c=0.95: {"word": word, "conf": c, "start": s, "end": s + 0.2}
    res = {"result": [w("iris", 0.0), w("alt", 0.25), w("tab", 0.45), w("trois", 0.7)]}
    assert [x["word"] for x in accepted_words(res)] == ["iris", "alt-tab trois"]
    res = {"result": [w("iris", 0.0), w("alt", 0.25), w("tab", 0.45)]}
    assert [x["word"] for x in accepted_words(res)] == ["iris", "alt-tab"]
    res = {"result": [w("iris", 0.0), w("alt", 0.25), w("tab", 0.45), w("trois", 0.7, 0.3)]}
    assert [x["word"] for x in accepted_words(res)] == ["iris", "alt-tab"]   # chiffre mal entendu : pas de saut


def test_grammaires():
    from motionzero.voice import GRAMMARS
    base = json.loads(GRAMMARS["base"])
    assert "alt tab" in base and "alt tab trois" in base and "tab" not in base and "trois" not in base
    assert "trois" in json.loads(GRAMMARS["alttab"]) and "trois" in json.loads(GRAMMARS["alttab_chrome"])
    assert "clic" in json.loads(GRAMMARS["alttab_souris"])
    assert "tab" in json.loads(GRAMMARS["candidature"])        # le « tab » du formulaire ne bouge pas


def test_noms_courts_et_texte():
    titles = ["motionzero - Visual Studio Code", "YouTube - Google Chrome", "Discord", "Gmail - Google Chrome"]
    assert window_labels(titles) == ["VS Code", "YouTube", "Discord", "Gmail"]
    assert list_text(titles) == "2 YouTube   3 Discord   4 Gmail"
    assert list_text(["Seule"]) is None and list_text([]) is None
    assert len(window_labels(["un titre beaucoup trop long pour l ilot"])[0]) <= 14


def test_number_of():
    assert number_of("alt-tab") == 2 and number_of("alt-tab cinq") == 5 and number_of("six") == 6
    assert number_of("sept") is None and number_of("clic") is None


def test_alt_tab_to_echecs_et_ordre():
    from motionzero.vscode import alt_tab_to
    wins = [(1, "A"), (2, "B"), (3, "C")]
    assert alt_tab_to(3, wins, front=lambda h: True) == (True, None, ["C", "A", "B"])
    assert alt_tab_to(2, wins, front=lambda h: True)[2] == ["B", "A", "C"]
    ok, err, _ = alt_tab_to(5, wins, front=lambda h: True)
    assert not ok and "PAS DE FENETRE 5" in err
    ok, err, _ = alt_tab_to(2, wins, front=lambda h: False)
    assert not ok and "ECHEC" in err
    ok, err, _ = alt_tab_to(2, [(1, "A")], front=lambda h: True)
    assert not ok


def test_appli_exception_ne_plante_pas(monkeypatch):
    import motionzero.vscode as vs
    from motionzero.app_actions import vscode_actions
    def boom(n):
        raise OSError("fenetre fermee")
    monkeypatch.setattr(vs, "alt_tab_to", boom)
    core = Core(Config())
    _alttab(core)
    vscode_actions([("alt_tab", 2)], core, None, None, 2.0)
    assert core.alttab_text is None and core.alttab_until < 0
    assert "ECHEC" in core.last_gesture[0]


def test_bandeau_se_dessine_sans_erreur():
    """25/11 : le bandeau plantait à chaque image (« erreur répétée ») : il doit se dessiner, centré."""
    from PySide6.QtGui import QImage, QPainter
    from motionzero.ui import QApplication, _IslandPainter
    QApplication.instance() or QApplication([])
    p = _IslandPainter(1920, 1080)
    img = QImage(1920, 1080, QImage.Format.Format_ARGB32)
    for st in ({"mode": "NEUTRE", "alttab": "2 Chrome   3 Steam"},
               {"mode": "NEUTRE", "alttab": "2 Chrome", "timers": {"timer": {"text": "2:00"}}}):
        p.update(st, 1.0)
        painter = QPainter(img)
        p.paint(painter)
        painter.end()


def test_coin_haut_droit_timer_et_rappel():
    """26/11 : timer, chronomètre et rappel déclenché en haut à droite ; l'instruction reste au centre."""
    from PySide6.QtGui import QImage, QPainter
    from motionzero.ui import QApplication, _IslandPainter
    from motionzero.ui_ile_base import reminder_view
    QApplication.instance() or QApplication([])
    cur = {"text": "Appeler le médecin", "when": "14:00", "ringing": True}
    plan = {"title": "Dis « oui » pour le faire", "lines": ["1. Discord : expulser Paul du serveur"]}
    st = {"mode": "NEUTRE", "plan": plan,
          "reminders": {"current": cur, "timers": {"timer": {"text": "4:59"}, "chrono": {"text": "0:12", "done": False}}}}
    assert reminder_view(st) == ("current", cur)                    # ancien comportement, sans le coin
    assert reminder_view(st, corner=True) == ("plan", plan)         # l'instruction n'est plus cachée
    p = _IslandPainter(1920, 1080)
    p.update(st, 1.0)
    assert p.corner_rem == cur and len(p.timer_pills) == 2 and p.rect().right() >= 1919
    img = QImage(1920, 1080, QImage.Format.Format_ARGB32)
    img.fill(0xFF808080)
    painter = QPainter(img)
    p.paint(painter)
    painter.end()
    assert img.pixel(1920 - 30, 40) != 0xFF808080                   # quelque chose dans le coin
    assert img.pixel(1919, 0) != 0xFF808080                         # 27/11 : collé aux bords, rien autour
    assert img.pixel(1920 - 421, 5) == 0xFF808080
    p.update({"mode": "NEUTRE"}, 2.0)                               # plus rien : zone du coin effacée une fois
    assert p.rect().right() >= 1919 and p.corner_rem is None
