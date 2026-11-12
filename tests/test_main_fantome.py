"""Main fantôme : en mode souris, tant que la paume n'est pas venue au centre, on voit où elle est."""
from motionzero.config import Config
from motionzero.core import Core, Mode


def _souris(palm):
    core = Core(Config())
    core.screen = (0, 0, 1000, 800)
    core.set_mode(Mode.MOUSE, 0.0, [])
    core.palm = palm
    return core


def test_main_au_centre_fantome_au_centre():
    x, y, r = _souris((0.5, 0.5)).ghost()
    assert (x, y) == (500, 400) and r == Config().arm_radius * 1000


def test_main_a_droite_en_haut():
    x, y, _ = _souris((0.75, 0.25)).ghost()
    assert (x, y) == (750, 200)


def test_fantome_reste_dans_l_ecran():
    x, y, _ = _souris((1.2, -0.3)).ghost()
    assert x == 999 and y == 0


def test_disparait_une_fois_arme():
    core = _souris((0.5, 0.5))
    core.armed = True
    assert core.ghost() is None


def test_rien_hors_souris_ou_sans_main():
    core = _souris(None)
    assert core.ghost() is None
    core = Core(Config())
    core.palm = (0.5, 0.5)
    assert core.ghost() is None


def test_geometrie_ecran():
    from motionzero.ui import ghost_geometry
    st = {"ghost": (300, 200, 80), "arming": True, "cursor": (500, 400)}
    hand, ctr, r = ghost_geometry(st, 2.0)
    assert (hand.x(), hand.y(), ctr.x(), ctr.y(), r) == (150, 100, 250, 200, 40)
    assert ghost_geometry({**st, "arming": False}, 1.0) is None
    assert ghost_geometry({**st, "ghost": None}, 1.0) is None
