"""Souris à la tête : orientation du visage -> point virtuel -> même pavé tactile que la main. Sans caméra."""
from motionzero.config import Config
from motionzero.core import Core, Mode
from motionzero.head import NOSE, HeadPointer, nose_position


def face(nose_x=0.5, nose_y=0.5, cx=0.5, cy=0.5, w=0.2, h=0.3):
    """Visage simplifié : seuls les 5 points utiles sont placés (les autres au centre)."""
    lms = [(cx, cy)] * 478
    lms[NOSE] = (nose_x, nose_y)
    return lms


def test_nez_dans_l_image():
    assert nose_position(face(nose_x=0.6, nose_y=0.4)) == (0.6, 0.4)
    assert nose_position(None) is None and nose_position([]) is None


def test_bouger_le_buste_bouge_le_curseur():
    """Choix de l'utilisateur : tout le visage qui glisse (nez compris) déplace le point."""
    hp = HeadPointer(scale=7.5)
    assert hp.point(face()) == (0.5, 0.5)
    x, _ = hp.point(face(nose_x=0.52, cx=0.52))
    assert abs(x - (0.5 + 7.5 * 0.02)) < 1e-9


def test_reference_prise_au_premier_visage():
    hp = HeadPointer(scale=2.0)
    assert hp.point(face(nose_x=0.53)) == (0.5, 0.5)       # tête un peu décalée au départ = centre
    x, _ = hp.point(face(nose_x=0.55))
    assert abs(x - (0.5 + 2.0 * 0.02)) < 1e-9
    hp.reset()
    assert hp.point(face(nose_x=0.55)) == (0.5, 0.5)       # « iris centre »


def test_visage_absent():
    assert HeadPointer().point(None) is None


def test_point_borne_a_l_image():
    hp = HeadPointer(scale=10)
    hp.point(face())
    assert hp.point(face(nose_x=0.6)) == (1.0, 0.5)


def _tete_souris():
    core = Core(Config())
    core.screen = (0, 0, 1000, 800)
    core.voice("iris", 0.0)
    core.voice("tête", 0.1)
    core.voice("iris", 0.2)
    core.voice("souris", 0.3)
    return core


def test_iris_tete_puis_souris_suit_la_tete():
    core = _tete_souris()
    assert core.pointer == "tete" and core.mouse
    t, acts = 1.0, []
    for _ in range(10):                                     # tête de face : armement au centre
        acts += core.step_head(face(), t)
        t += 0.05
    assert core.armed
    moves = []
    for i in range(10):                                     # on tourne la tête vers la droite
        moves += [a for a in core.step_head(face(nose_x=0.5 + 0.005 * (i + 1)), t) if a[0] == "move"]
        t += 0.05
    assert moves and moves[-1][1] > 500


def test_tete_absente_relache():
    core = _tete_souris()
    core.step_head(face(), 1.0)
    acts = core.step_head(None, 5.0)
    assert ("release_all",) in acts


def test_iris_main_revient_a_la_main_et_signale():
    core = _tete_souris()
    core.voice("iris", 1.0)
    acts = core.voice("main", 1.1)
    assert core.pointer == "main" and ("pointer", "main") in acts and ("release_all",) in acts


def test_bouton_de_l_accueil_bascule():
    core = Core(Config())
    assert ("pointer", "tete") in core.set_pointer_toggle(1.0) and core.pointer == "tete"
    core.set_pointer_toggle(2.0)
    assert core.pointer == "main"


def test_iris_centre():
    core = _tete_souris()
    core.step_head(face(nose_x=0.53), 1.0)
    core.voice("iris", 2.0)
    acts = core.voice("centre", 2.1)
    assert core.head.base is None and any(a[0] == "move" for a in acts)


def test_pause_la_tete_ne_fait_rien():
    core = _tete_souris()
    core.voice("iris", 1.0)
    core.voice("pause", 1.1)
    assert core.mode == Mode.DISABLED and core.step_head(face(), 2.0) == []


def test_choix_garde_au_redemarrage(tmp_path):
    from motionzero.app import read_pointer, write_pointer
    f = str(tmp_path / "pointeur.txt")
    assert read_pointer(f) == "main"                        # rien d'enregistré
    write_pointer(f, "tete")
    assert read_pointer(f) == "tete"
    (tmp_path / "pointeur.txt").write_text("n'importe quoi")
    assert read_pointer(f) == "main"


def test_texte_du_bouton():
    from motionzero.ui import pointer_button_text
    assert "tête" in pointer_button_text("main") and "main" in pointer_button_text("tete")


def test_tete_immobile_le_curseur_ne_tremble_pas():
    """Bruit du maillage du visage (tête immobile) : le point virtuel ne bouge pas (mesuré : ça tremblait)."""
    import random
    rnd = random.Random(1)
    hp = HeadPointer(scale=7.5, scale_y=10.0)
    pts = []
    for i in range(60):                                     # 2 s à 30 images/s, nez qui tremble de ±0,1 %
        p = hp.point(face(nose_x=0.5 + rnd.uniform(-0.001, 0.001), nose_y=0.5 + rnd.uniform(-0.001, 0.001)), i / 30)
        pts.append(p)
    spread = max(abs(p[0] - 0.5) for p in pts[10:])
    assert spread < 0.003


def test_tete_qui_tourne_suit_quand_meme():
    hp = HeadPointer(scale=7.5, scale_y=10.0)
    for i in range(30):
        x, _ = hp.point(face(nose_x=0.5 + 0.0015 * i), i / 30)   # rotation franche
    assert x > 0.6


def test_vertical_plus_sensible():
    """Lever la tête déplace moins le nez que la tourner : la verticale est amplifiée davantage."""
    hp = HeadPointer(scale=7.5, scale_y=10.0)
    hp.point(face())
    x, _ = hp.point(face(nose_x=0.52))
    _, y = hp.point(face(nose_y=0.53))
    assert abs((x - 0.5) - 7.5 * 0.02) < 1e-9 and abs((y - 0.5) - 10.0 * 0.03) < 1e-9
    from motionzero.config import Config
    assert Config().head_scale_y > Config().head_scale
