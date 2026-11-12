"""La souris est un outil, pas un mode : « iris souris » garde le mode en cours (Chrome, lecture…)."""
from motionzero.config import Config
from motionzero.core import Core, Mode


def _chrome():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("chrome", 1.2)
    assert core.mode == Mode.CHROME
    return core


def test_souris_dans_chrome_garde_chrome():
    core = _chrome()
    core.voice("iris", 2.0)
    acts = core.voice("souris", 2.2)
    assert core.mouse and core.mode == Mode.CHROME and ("mouse", True) in acts
    assert core.voice("retour", 3.0) == [("chrome_keys", ["alt", "left"])]   # le mode Chrome marche toujours


def test_iris_souris_eteint_la_souris():
    core = _chrome()
    core.voice("iris", 2.0)
    core.voice("souris", 2.2)
    core.voice("iris", 3.0)
    acts = core.voice("souris", 3.2)
    assert not core.mouse and core.mode == Mode.CHROME and ("release_all",) in acts


def test_stop_eteint_la_souris_sans_quitter_chrome():
    core = _chrome()
    core.voice("iris", 2.0)
    core.voice("souris", 2.2)
    core.voice("stop", 3.0)
    assert not core.mouse and core.mode == Mode.CHROME
    core.voice("stop", 4.0)                          # second « stop » : quitte Chrome comme avant
    assert core.mode == Mode.NEUTRAL


def test_chrome_perdu_garde_la_souris():
    core = _chrome()
    core.voice("iris", 2.0)
    core.voice("souris", 2.2)
    core.chrome_front(True, 2.5)
    core.chrome_front(False, 3.0)
    assert core.mode == Mode.NEUTRAL and core.mouse


def test_pause_eteint_la_souris():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("souris", 1.2)
    core.voice("iris", 2.0)
    core.voice("pause", 2.2)
    assert core.mode == Mode.DISABLED and not core.mouse


def test_lecture_eteint_la_souris():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("souris", 1.2)
    core.voice("iris", 2.0)
    core.voice("lecture", 2.2)
    assert core.mode == Mode.READING and not core.mouse


def test_ilot_et_cercle_avec_souris():
    from motionzero.ui import ORANGE, island_text, islet_ring
    st = {"mode": "CHROME", "mouse": True}
    assert island_text(st)[0] == "CHROME · SOURIS"
    assert island_text({"mode": "NEUTRE", "mouse": True})[0] == "SOURIS"
    assert islet_ring(st, 0)[0] == ORANGE


def test_clic_sans_iris_quand_la_souris_est_allumee():
    core = Core(Config())
    core.voice("iris", 1.0)
    core.voice("souris", 1.2)
    assert core.voice("clic", 2.0)[-1] == ("click", "left")
    assert core.voice("double", 3.0)[-2:] == [("click", "left"), ("click", "left")]
    assert core.voice("menu", 4.0)[-1] == ("click", "right")


def test_clic_garde_iris_souris_eteinte():
    core = Core(Config())
    assert core.voice("clic", 1.0) == [] and core.voice("menu", 1.5) == []
