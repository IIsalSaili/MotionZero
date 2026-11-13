"""Souris à la tête : orientation de la tête (matrice MediaPipe) -> point virtuel -> même pavé tactile que la main.
Sans caméra : visage et matrice simulés."""
import math
import random

from motionzero.config import Config
from motionzero.core import Core, Mode
from motionzero.head import (BOTTOM_PTS, LEFT_PTS, NOSE_PTS, RIGHT_PTS, TOP_PTS, HeadPointer, head_offsets,
                             pose_angles)


def face(nose_x=0.5, nose_y=0.5, cx=0.5, cy=0.5, w=0.2, h=0.3):
    """Visage simplifié : seuls les groupes de points utiles sont placés."""
    lms = [(cx, cy)] * 478
    for i in NOSE_PTS:
        lms[i] = (nose_x, nose_y)
    for i in LEFT_PTS:
        lms[i] = (cx - w / 2, cy)
    for i in RIGHT_PTS:
        lms[i] = (cx + w / 2, cy)
    for i in TOP_PTS:
        lms[i] = (cx, cy - h / 2)
    for i in BOTTOM_PTS:
        lms[i] = (cx, cy + h / 2)
    return lms


def mat(yaw=0.0, pitch=0.0, flip_x=False):
    """Matrice 4x4 dont la direction du regard (3e colonne) correspond à ce lacet / tangage."""
    fx = math.sin(yaw) * math.cos(pitch) * (-1 if flip_x else 1)
    fy, fz = math.sin(pitch), math.cos(yaw) * math.cos(pitch)
    return [[1, 0, fx, 0], [0, 1, fy, 0], [0, 0, fz, 0], [0, 0, 0, 1]]


def turned(yaw=0.0, pitch=0.0, **kw):
    """Visage + matrice cohérents : tourner à droite pousse le nez à droite, lever la tête le monte."""
    return face(nose_x=0.5 + 0.12 * yaw, nose_y=0.5 - 0.12 * pitch, **kw), mat(yaw, pitch)


def test_angles_de_la_matrice():
    y, p = pose_angles(mat(0.3, -0.2))
    assert abs(y - 0.3) < 1e-9 and abs(p + 0.2) < 1e-9
    assert pose_angles(None) is None and pose_angles([[0] * 4] * 4) is None


def test_tourner_a_droite_et_lever_la_tete():
    hp = HeadPointer(scale=1.4, scale_y=2.0)
    assert hp.point(*turned()) == (0.5, 0.5)
    x, _ = hp.point(*turned(yaw=0.2))
    _, y = hp.point(*turned(pitch=0.2))
    assert abs(x - (0.5 + 1.4 * 0.2)) < 1e-9 and abs(y - (0.5 - 2.0 * 0.2)) < 1e-9   # curseur à droite, en haut


def test_bouger_le_buste_ne_bouge_rien():
    """Tout le visage glisse dans l'image sans tourner : l'orientation ne change pas."""
    hp = HeadPointer()
    hp.point(face(), mat())
    assert hp.point(face(nose_x=0.6, cx=0.6), mat()) == (0.5, 0.5)


def test_sens_d_un_axe_corrige_tout_seul():
    """Si la matrice a l'axe horizontal à l'envers, les mouvements nets du nez le révèlent et on corrige."""
    hp = HeadPointer(scale=1.4)
    hp.point(face(), mat(flip_x=True))
    for _ in range(4):                                      # tête franchement tournée à droite
        x, _ = hp.point(face(nose_x=0.53), mat(0.3, flip_x=True))
    assert hp.sign[0] == -1 and x > 0.5


def test_sens_correct_pas_de_correction():
    hp = HeadPointer()
    hp.point(*turned())
    for _ in range(10):
        hp.point(*turned(yaw=0.3, pitch=0.3))
    assert hp.sign == [1, -1]


def test_sans_matrice_on_se_rabat_sur_le_nez_dans_le_visage():
    hp = HeadPointer(rel_scale=1.5)
    assert hp.point(face()) == (0.5, 0.5)
    x, _ = hp.point(face(nose_x=0.52))
    assert abs(x - (0.5 + 1.5 * 0.1)) < 1e-9


def test_visage_absent_ou_trop_petit():
    assert head_offsets(None) is None and head_offsets([]) is None
    assert HeadPointer().point(None) is None
    assert HeadPointer().point(face(w=0.01)) is None


def test_tete_immobile_le_curseur_ne_tremble_pas():
    """Orientation qui tremble de ±0,15° : le point ne bouge pas."""
    rnd = random.Random(1)
    hp = HeadPointer()
    pts = [hp.point(face(), mat(rnd.uniform(-0.0026, 0.0026), rnd.uniform(-0.0026, 0.0026)), i / 30)
           for i in range(60)]
    assert max(abs(p[0] - 0.5) + abs(p[1] - 0.5) for p in pts[10:]) < 0.005


def test_petit_geste_lent_passe_quand_meme():
    """Rotation lente de 2° : elle doit bouger le curseur (la zone morte ne mange pas les petits gestes)."""
    hp = HeadPointer()
    for i in range(60):
        x, _ = hp.point(face(), mat(0.035 * i / 59), i / 30)
    assert x > 0.52


def test_vitesse_propre_a_la_tete():
    core = Core(Config())
    lent_main = core._gain(0.0)
    core.pointer = "tete"
    assert core._gain(0.0) < lent_main and core._gain(10.0) == Config().head_gain_max


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
        lms, m = turned()
        acts += core.step_head(lms, t, m)
        t += 0.05
    assert core.armed
    moves = []
    for i in range(15):                                     # on tourne la tête vers la droite
        lms, m = turned(yaw=0.03 * (i + 1))
        moves += [a for a in core.step_head(lms, t, m) if a[0] == "move"]
        t += 0.05
    assert moves and moves[-1][1] > 500


def test_tete_absente_relache():
    core = _tete_souris()
    lms, m = turned()
    core.step_head(lms, 1.0, m)
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
    lms, m = turned(yaw=0.1)
    core.step_head(lms, 1.0, m)
    core.voice("iris", 2.0)
    acts = core.voice("centre", 2.1)
    assert core.head.base is None and any(a[0] == "move" for a in acts)


def test_pause_la_tete_ne_fait_rien():
    core = _tete_souris()
    core.voice("iris", 1.0)
    core.voice("pause", 1.1)
    lms, m = turned()
    assert core.mode == Mode.DISABLED and core.step_head(lms, 2.0, m) == []


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


# --- « défile » à la tête --------------------------------------------------------
def _tete_defile(pitches, core=None, t=1.0):
    core = core or _tete_souris()
    acts = []
    for p in pitches:
        lms, m = turned(pitch=p)
        acts += core.step_head(lms, t, m)
        t += 1 / 30
    return core, acts, t


def test_defile_tete_petit_mouvement_suffit():
    core, _, t = _tete_defile([0.0] * 10)                  # souris armée tête de face
    core.voice("iris", t)
    core.voice("défile", t)
    core, acts, t = _tete_defile([0.0] * 10 + [-0.08] * 60, core, t)   # tête baissée d'environ 5°, 2 s
    scrolls = [a for a in acts if a[0] == "scroll"]
    assert 1 <= len(scrolls) <= 5 and all(s[1] < 0 for s in scrolls)
    assert not [a for a in acts if a[0] == "move"]          # le curseur ne bouge pas pendant le défilement
    core, acts, t = _tete_defile([0.08] * 90, core, t)       # tête levée : ça remonte
    ups = [a[1] for a in acts if a[0] == "scroll"]
    assert ups and ups[-1] > 0 and sum(u > 0 for u in ups) >= 2   # un cran de transition (filtre) toléré


def test_defile_tete_tremblement_ne_defile_pas():
    core, _, t = _tete_defile([0.0] * 10)
    core.voice("iris", t)
    core.voice("défile", t)
    core, acts, t = _tete_defile([0.03 * (-1) ** i for i in range(60)], core, t)
    assert not [a for a in acts if a[0] == "scroll"]


def test_defile_tete_stop_rend_la_souris():
    core, _, t = _tete_defile([0.0] * 10)
    core.voice("iris", t)
    core.voice("défile", t)
    core, _, t = _tete_defile([0.0] * 10, core, t)
    assert core.scrolling(t)
    core.voice("stop", t)
    assert not core.scrolling(t) and core.mouse
    core, acts, t = _tete_defile([0.0] * 10 + [0.03 * i for i in range(20)], core, t)
    assert [a for a in acts if a[0] == "move"]               # se réarme au centre puis suit la tête


def test_defile_tete_butee_un_petit_retour_suffit():
    """Tête baissée à fond : un léger relèvement ramène tout de suite au neutre (pas tout le chemin)."""
    core, _, t = _tete_defile([0.0] * 10)
    core.voice("iris", t)
    core.voice("défile", t)
    core, acts, t = _tete_defile([0.0] * 10 + [-0.3] * 30, core, t)   # yeux au sol
    assert [a for a in acts if a[0] == "scroll"]
    assert core.scroll_gauge(t)[0] <= 0.95                             # curseur juste sous le vert, pas en bas
    core, acts, t = _tete_defile([-0.2] * 15, core, t)                 # relevée de quelques degrés
    core, acts, t = _tete_defile([-0.2] * 15, core, t)
    assert not [a for a in acts if a[0] == "scroll"]                   # neutre en moins de 0,5 s
    core, acts, t = _tete_defile([0.3] * 60, core, t)                  # yeux au plafond
    ups = [a[1] for a in acts if a[0] == "scroll"]
    assert ups and ups[-1] > 0
    core, acts, t = _tete_defile([0.2] * 15, core, t)
    core, acts, t = _tete_defile([0.2] * 15, core, t)
    assert not [a for a in acts if a[0] == "scroll"]


def test_defile_tete_vitesse_douce_a_fond():
    """Tête à fond : au plus quelques crans par seconde (avant : envoyé « à l'autre bout de la planète »)."""
    core, _, t = _tete_defile([0.0] * 10)
    core.voice("iris", t)
    core.voice("défile", t)
    core, acts, t = _tete_defile([0.0] * 10 + [-0.3] * 90, core, t)    # 3 s yeux au sol
    assert len([a for a in acts if a[0] == "scroll"]) <= 9


def test_defile_tete_ne_s_arrete_pas_si_le_visage_disparait():
    core, _, t = _tete_defile([0.0] * 10)
    core.voice("iris", t)
    core.voice("défile", t)
    core, _, t = _tete_defile([0.0] * 10, core, t)
    core.step_head(None, t + 2.0)
    assert core.scrolling(t + 2.0)                      # seule la voix en sort


def test_defile_tete_bouger_un_peu_reste_dans_le_vert():
    """Tête levée ou baissée d'environ 2° : on reste au neutre, rien ne défile."""
    core, _, t = _tete_defile([0.0] * 10)
    core.voice("iris", t)
    core.voice("défile", t)
    core, acts, t = _tete_defile([0.0] * 10 + [0.04] * 45 + [-0.04] * 45, core, t)
    assert not [a for a in acts if a[0] == "scroll"]


def test_sensibilite_tete_douce():
    """Tête tournée d'environ 6° (0,1 rad) en 0,5 s : le curseur bouge, mais reste loin du bord (avant :
    jugé « impossible à contrôler »)."""
    core = _tete_souris()
    t = 1.0
    for _ in range(10):
        lms, m = turned()
        core.step_head(lms, t, m)
        t += 0.05
    x0 = core.cursor[0]
    for i in range(15):
        lms, m = turned(yaw=0.1 * (i + 1) / 15)
        core.step_head(lms, t, m)
        t += 1 / 30
    assert 20 < core.cursor[0] - x0 < 350
