"""Issue #15 : en mode souris, le curseur ne bouge qu'une fois la paume amenée au centre de l'image."""
from synth import Clock, hand

from motionzero.config import Config
from motionzero.core import Core, Mode
from motionzero.hand import compute_features
from motionzero.ui import island_text

CFG = Config()
_p = compute_features(hand(cx=0.5, cy=0.6), CFG).palm
OX, OY = _p[0] - 0.5, _p[1] - 0.6          # décalage poignet simulé -> paume


def at(px, py):
    """Arguments de Clock.run pour une paume en (px, py)."""
    return {"cx": px - OX, "cy": py - OY}


def moves(acts):
    return [a for a in acts if a[0] == "move"]


def entre_en_souris(core, clk, px, py):
    clk.run(core, 0.5, **at(px, py))
    core.voice("iris", clk.t)
    core.voice("souris", clk.t + 0.2)
    assert core.mode == Mode.MOUSE and not core.armed


def test_main_deja_au_centre_arme_apres_le_maintien():
    core, clk = Core(Config()), Clock()
    entre_en_souris(core, clk, 0.5, 0.5)
    clk.run(core, 0.1, **at(0.5, 0.5))
    assert not core.armed                                   # moins de arm_hold_s
    clk.run(core, 0.2, **at(0.5, 0.5))
    assert core.armed


def test_main_jamais_au_centre_le_curseur_ne_bouge_pas():
    core, clk = Core(Config()), Clock()
    entre_en_souris(core, clk, 0.2, 0.5)
    acts = clk.run(core, 1.0, **at(0.2, 0.5), to_cx=0.1 - OX) + clk.run(core, 2.0, **at(0.1, 0.5))
    assert not core.armed and not moves(acts) and core.cursor == (960, 540)
    st = {"mode": "SOURIS", "arming": True}
    assert island_text(st)[1] == "Main au centre pour démarrer"


def test_passage_rapide_au_centre_n_arme_pas():
    core, clk = Core(Config()), Clock()
    entre_en_souris(core, clk, 0.2, 0.5)
    clk.run(core, 0.2, **at(0.2, 0.5), to_cx=0.8 - OX)       # traverse le centre en 0,2 s
    assert not core.armed


def test_armement_sans_saut_puis_suivi():
    core, clk = Core(Config()), Clock()
    entre_en_souris(core, clk, 0.2, 0.5)
    clk.run(core, 0.5, **at(0.2, 0.5), to_cx=0.5 - OX)
    acts = clk.run(core, 0.4, **at(0.5, 0.5))
    assert core.armed and all(abs(m[1] - 960) < 20 for m in moves(acts))
    clk.run(core, 0.5, **at(0.5, 0.5), to_cx=0.7 - OX)
    assert core.cursor[0] > 1100


def _arme(core, clk):
    entre_en_souris(core, clk, 0.5, 0.5)
    clk.run(core, 0.4, **at(0.5, 0.5))
    assert core.armed


def test_absence_courte_pas_de_rearmement():
    core, clk = Core(Config()), Clock()
    _arme(core, clk)
    clk.run(core, 0.2, absent=True)
    clk.run(core, 0.1, **at(0.3, 0.5))
    assert core.armed


def test_absence_longue_rearmement():
    core, clk = Core(Config()), Clock()
    _arme(core, clk)
    clk.run(core, 1.0, absent=True)
    acts = clk.run(core, 1.0, **at(0.3, 0.5), to_cx=0.1 - OX)
    assert not core.armed and moves(acts) == [("move", 960, 540)]


def test_bords_gauche_et_droit_atteignables_en_lent():
    """Armé au centre, la main a la même course des deux côtés : les deux bords sont atteints."""
    for bord, attendu in ((0.95, 1919), (0.05, 0)):
        core, clk = Core(Config()), Clock()
        _arme(core, clk)
        clk.run(core, 4.0, **at(0.5, 0.5), to_cx=bord - OX)   # ~0,11 image/s : plutôt lent
        assert abs(core.cursor[0] - attendu) <= CFG.deadzone_px, (bord, core.cursor)


def test_arreter_puis_reprendre_la_souris_rearme():
    core, clk = Core(Config()), Clock()
    _arme(core, clk)
    core.voice("iris", clk.t)
    core.voice("lecture", clk.t + 0.2)
    core.voice("iris", clk.t + 0.5)
    core.voice("souris", clk.t + 0.7)
    assert core.mode == Mode.MOUSE and not core.armed
