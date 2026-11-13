"""Petites issues du 14/11 : undo / redo (#36), « ferme » en Chrome (#34), Iris et pas Claude (#37),
effets d'animation de Windows (#11), volume d'Iris dans l'accueil (#28)."""
import queue
from types import SimpleNamespace

from motionzero.config import Config
from motionzero.core import Core, Mode


def _say(core, word, t):
    core.voice("iris", t)
    return core.voice(word, t + 0.3)


def test_undo_redo():
    core = Core(Config())
    assert _say(core, "undo", 1) == [("hotkey", ["ctrl", "z"])]
    assert core.voice("undo", 2.0) == [("hotkey", ["ctrl", "z"])]       # redit seul : répété
    assert _say(core, "redo", 5) == [("hotkey", ["ctrl", "y"])]


def test_redo_entendu_en_deux_morceaux():
    from motionzero.voice import accepted_words
    res = {"result": [{"word": "iris", "conf": 1.0, "start": 0, "end": .3},
                      {"word": "re", "conf": 1.0, "start": .4, "end": .5},
                      {"word": "do", "conf": 1.0, "start": .5, "end": .6}]}
    assert [w["word"] for w in accepted_words(res)][-1] == "redo"


def _chrome():
    core = Core(Config())
    core.set_mode(Mode.CHROME, 0.0, [])
    return core


def test_ferme_en_chrome_retire_d_abord_l_affichage():
    core = _chrome()
    core.top_shown = True
    acts = core.voice("ferme", 1.0)
    assert ("rappel_merci",) in acts and ("ask_close",) in acts
    assert not any(a[0] == "chrome_keys" for a in acts)
    core.top_shown = False                                    # plus rien d'affiché : l'onglet se ferme
    assert ("chrome_keys", ["ctrl", "w"]) in core.voice("ferme", 3.0)


def test_ferme_en_chrome_retire_l_heure():
    core = _chrome()
    core.clock_until = 10.0
    acts = core.voice("ferme", 1.0)
    assert not any(a[0] == "chrome_keys" for a in acts) and core.clock_until < 0


def test_top_shown_ne_plante_jamais():
    from motionzero.app import top_shown
    assert top_shown(SimpleNamespace(asker=None), 1.0) is False
    broken = SimpleNamespace(asker=SimpleNamespace(snapshot=lambda: 1 / 0))
    assert top_shown(broken, 1.0) is False
    desk = SimpleNamespace(r=SimpleNamespace(active=[]), list_until=5.0)
    assert top_shown(SimpleNamespace(asker=None, desk=desk), 1.0) is True     # liste affichée
    assert top_shown(SimpleNamespace(asker=None, desk=desk), 6.0) is False


def test_jamais_claude_ni_haiku_pour_le_personnage():
    from motionzero.ask import SYSTEM
    from motionzero.ui import island_text
    for phase in ("thinking", "answer"):
        assert "Iris" in island_text({"qa": {"phase": phase}})[1]
    assert "Claude t'écoute" == island_text({"dictating": True})[1]    # micro de Claude dans VS Code : logique
    assert SYSTEM.startswith("Tu es Iris") and "internet" in SYSTEM


def test_animations_coupees():
    from motionzero.ui import GREEN, clock_anim, islet_ring
    assert clock_anim(0.1, 0.0, None, motion=False) == (1.0, 0.0)       # heure : tout de suite à sa taille
    assert clock_anim(0.1, 0.0, 0.05, motion=False) == (0.0, 0.0)
    for age in (0.0, 0.2, 0.4):
        assert islet_ring({"ok_flash": True}, age, motion=False)[0] == GREEN    # vert fixe, pas de clignement


def test_reglage_windows_illisible(monkeypatch):
    import motionzero.ui as ui
    monkeypatch.setattr(ui.ctypes, "windll", None, raising=False)
    assert ui.windows_animations() is True


def test_volume_de_l_accueil(tmp_path, monkeypatch):
    import motionzero.app as app
    from motionzero.ui import volume_button_text
    assert [app.next_volume(v) for v in (0.3, 0.5, 0.7, 1.0, 0.42)] == [0.5, 0.7, 1.0, 0.3, 0.5]
    assert app.read_volume(str(tmp_path / "absent"), 0.5) == 0.5
    bad = tmp_path / "v.txt"
    bad.write_text("fort", encoding="utf-8")
    assert app.read_volume(str(bad), 0.5) == 0.5
    bad.write_text("7", encoding="utf-8")
    assert app.read_volume(str(bad), 0.5) == 0.5                    # hors de 0..1
    monkeypatch.setattr(app, "VOLUME_FILE", str(tmp_path / "vol.txt"))
    played, emitted = [], []
    d = SimpleNamespace(volume_requests=queue.Queue(),
                        sounds=SimpleNamespace(mixer=SimpleNamespace(volume=0.5), play=played.append),
                        bridge=SimpleNamespace(iris_volume=SimpleNamespace(emit=emitted.append)))
    eng = app.Engine.__new__(app.Engine)
    eng.d = d
    d.volume_requests.put(1)
    eng._volume()
    assert d.sounds.mixer.volume == 0.7 and emitted == [0.7] and played == ["OK"]
    assert app.read_volume(app.VOLUME_FILE, 0.5) == 0.7
    assert volume_button_text(0.7) == "Volume d'Iris : 70 %"
    eng.d = SimpleNamespace()                                       # sans file : rien ne plante
    eng._volume()
