"""Tests des gestes v2 (aucune pose de doigts, aucun pincement), sur mains simulées."""
from synth import Clock, hand

from motionzero.config import Config
from motionzero.core import Core, Mode
from motionzero.filters import OneEuro
from motionzero.hand import HandTracker, Pose, compute_features
from motionzero.output import Controller, FakeBackend


def kinds(acts, kind):
    return [a for a in acts if a[0] == kind]


def mirror(pts):
    return [(1 - x, y) for x, y in pts]


# --- lecture : bords de l'image ---------------------------------------------
def test_bord_droit_page_suivante_une_seule_fois():
    core, clk = Core(READ), Clock()
    assert core.mode == Mode.READING
    clk.run(core, 0.5, cx=0.5)
    acts = clk.run(core, 0.2, cx=0.5, to_cx=0.9) + clk.run(core, 2.0, cx=0.9)
    assert kinds(acts, "key") == [("key", "right")]


def test_bord_gauche_page_precedente_apres_retour_au_centre():
    core, clk = Core(READ), Clock()
    clk.run(core, 0.5, cx=0.5)
    clk.run(core, 0.2, cx=0.5, to_cx=0.9)
    clk.run(core, 0.6, cx=0.9)
    clk.run(core, 0.3, cx=0.9, to_cx=0.5)  # retour au centre : réarmé
    clk.run(core, 0.8, cx=0.5)
    acts = clk.run(core, 0.2, cx=0.5, to_cx=0.1) + clk.run(core, 0.6, cx=0.1)
    assert kinds(acts, "key") == [("key", "left")]


def test_passage_rapide_au_bord_ne_tourne_pas_la_page():
    core, clk = Core(Config()), Clock()
    clk.run(core, 0.5, cx=0.5)
    acts = clk.run(core, 0.1, cx=0.5, to_cx=0.9) + clk.run(core, 0.1, cx=0.9, to_cx=0.5)
    assert kinds(acts, "key") == []


def test_aucune_forme_de_main_exigee():
    """Poing, main ouverte, n'importe quoi : seule la position compte."""
    for pose in ("open", "fist", "point", "thumb_up"):
        core, clk = Core(READ), Clock()
        clk.run(core, 0.5, pose, cx=0.5)
        acts = clk.run(core, 0.2, pose, cx=0.5, to_cx=0.9) + clk.run(core, 0.6, pose, cx=0.9)
        assert kinds(acts, "key") == [("key", "right")], pose


# --- défilement -----------------------------------------------------------------
def test_paume_en_bas_defile_vers_le_bas_tant_qu_elle_y_reste():
    core, clk = Core(READ), Clock()
    clk.run(core, 0.5, cx=0.5, cy=0.5)
    # (cy = poignet ; la paume est ~0,11 plus haut)
    # zone du bas étroite (paume au-delà de 0,88) : poignet à 1,02 -> paume ~0,91
    acts = clk.run(core, 0.1, cx=0.5, cy=0.5, to_cy=1.02) + clk.run(core, 1.0, cx=0.5, cy=1.02)
    scrolls = kinds(acts, "scroll")
    assert len(scrolls) >= 4 and all(s[1] < 0 for s in scrolls)
    acts = clk.run(core, 0.2, cx=0.5, cy=1.02, to_cy=0.5) + clk.run(core, 0.5, cx=0.5, cy=0.5)
    assert len(kinds(acts, "scroll")) <= 1  # s'arrête en revenant au centre


def test_paume_en_haut_defile_vers_le_haut_sans_bulle():
    core, clk = Core(READ), Clock()
    clk.run(core, 0.5, cx=0.5, cy=0.5)
    acts = clk.run(core, 0.1, cx=0.5, cy=0.5, to_cy=0.15) + clk.run(core, 3.0, cx=0.5, cy=0.15)
    assert kinds(acts, "scroll") and all(s[1] > 0 for s in kinds(acts, "scroll"))
    assert core.bubble is None and core.mode == Mode.READING


def test_passage_bref_en_bas_ne_defile_pas():
    core, clk = Core(Config()), Clock()
    clk.run(core, 0.5, cx=0.5, cy=0.5)
    acts = clk.run(core, 0.1, cx=0.5, cy=0.5, to_cy=0.95) + clk.run(core, 0.1, cx=0.5, cy=0.95, to_cy=0.5)
    assert kinds(acts, "scroll") == []


def test_molette_envoyee_a_windows():
    fake = FakeBackend()
    Controller(fake, Config()).execute([("scroll", -120)], 0.0)
    assert fake.events == [("wheel", -120)]


# --- entrer en souris ---------------------------------------------------------
READ = Config(start_mode="LECTURE")   # tests du mode lecture : il n'est plus le mode de départ
BUBBLE = Config(mouse_bubble=True, start_mode="LECTURE")   # ancienne bulle « SOURIS ? », gardée en option


def _enter_mouse_bubble(core, clk):
    clk.run(core, 1.7, cx=0.5, cy=0.6, jitter=0.004)       # immobile (avec tremblement) -> bulle
    assert core.bubble is not None
    acts = clk.run(core, 0.25, cx=0.5, cy=0.6, to_cy=0.52)  # petit mouvement vers le haut
    assert core.mouse
    return acts


def _enter_mouse(core, clk):
    """« iris souris » (la bulle sur main immobile n'existe plus par défaut)."""
    clk.run(core, 0.5, cx=0.5, cy=0.6)
    core.voice("iris", clk.t)
    acts = core.voice("souris", clk.t + 0.2)
    assert core.mouse
    return acts + clk.run(core, 0.25, cx=0.5, cy=0.6, to_cy=0.52)


def test_immobile_puis_haut_entre_en_souris():
    core, clk = Core(BUBBLE), Clock()
    acts = _enter_mouse_bubble(core, clk)
    assert ("mouse", True) in acts


def test_bulle_ignoree_ne_revient_pas_sans_bouger():
    core, clk = Core(BUBBLE), Clock()
    clk.run(core, 1.7, cx=0.5)
    assert core.bubble is not None
    clk.run(core, 2.5, cx=0.5)          # rien : la bulle disparaît
    assert core.bubble is None and core.mode == Mode.READING
    clk.run(core, 3.0, cx=0.5)          # toujours immobile : pas de nouvelle bulle
    assert core.bubble is None


def test_main_posee_au_bord_pas_de_bulle():
    core, clk = Core(Config()), Clock()
    clk.run(core, 0.5, cx=0.9)
    clk.run(core, 3.0, cx=0.9)
    assert core.bubble is None


# --- souris -----------------------------------------------------------------------
def test_curseur_relatif_suit_la_main():
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    x0 = core.cursor[0]
    acts = clk.run(core, 0.5, cx=0.5, cy=0.52, to_cx=0.6)
    assert kinds(acts, "move") and core.cursor[0] > x0 + 100


def test_pas_de_menu_en_entrant_sans_bouger():
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    acts = clk.run(core, 3.0, cx=0.5, cy=0.52)
    assert not core.menu.is_open and kinds(acts, "click") == []


MENU = Config(click_menu_on_still=True, start_mode="LECTURE")   # ancien menu de clic, gardé en option


def _open_menu(core, clk):
    _enter_mouse(core, clk)
    clk.run(core, 0.5, cx=0.5, cy=0.52, to_cx=0.6)
    clk.run(core, 1.0, cx=0.6, cy=0.52, jitter=0.003)
    assert core.menu.is_open


def test_menu_gauche_clic_gauche():
    core, clk = Core(MENU), Clock()
    _open_menu(core, clk)
    acts = clk.run(core, 0.2, cx=0.6, cy=0.52, to_cx=0.52)
    assert kinds(acts, "click") == [("click", "left")]


def test_menu_droite_clic_droit_et_haut_double_clic():
    core, clk = Core(MENU), Clock()
    _open_menu(core, clk)
    assert kinds(clk.run(core, 0.2, cx=0.6, cy=0.52, to_cx=0.68), "click") == [("click", "right")]
    core2, clk2 = Core(MENU), Clock()
    _open_menu(core2, clk2)
    acts = clk2.run(core2, 0.2, cx=0.6, cy=0.52, to_cy=0.44)
    assert kinds(acts, "click") == [("click", "left"), ("click", "left")]


def test_menu_bas_retour_lecture():
    core, clk = Core(MENU), Clock()
    _open_menu(core, clk)
    mode = core.mode
    clk.run(core, 0.2, cx=0.6, cy=0.52, to_cy=0.60)
    assert not core.mouse and core.mode == mode      # menu bas : souris éteinte, le mode reste


def test_menu_ignore_aucun_clic():
    core, clk = Core(MENU), Clock()
    _open_menu(core, clk)
    acts = clk.run(core, 2.0, cx=0.6, cy=0.52)
    assert kinds(acts, "click") == [] and not core.menu.is_open


def test_un_seul_clic_tant_qu_on_ne_bouge_pas():
    """La cause des 19 clics involontaires : rester immobile ne doit pas recliquer."""
    core, clk = Core(MENU), Clock()
    _open_menu(core, clk)
    acts = clk.run(core, 0.2, cx=0.6, cy=0.52, to_cx=0.52)
    acts += clk.run(core, 6.0, cx=0.52, cy=0.52, jitter=0.003)
    assert len(kinds(acts, "click")) == 1


def test_main_absente_relache_mais_reste_en_souris():
    """La main absente relâche tout, mais le mode souris reste (on en sort par « iris stop »)."""
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    acts = clk.run(core, 5.0, absent=True)
    assert core.mouse and ("release_all",) in acts


def test_iris_souris_main_baissee_reste_en_souris():
    """Mesuré le 10/11 : « iris souris » main baissée -> ressorti du mode souris 30 ms plus tard."""
    core, clk = Core(Config()), Clock()
    clk.run(core, 0.5, cx=0.5, cy=0.6)
    clk.run(core, 4.0, absent=True)                         # main baissée depuis 4 s
    core.voice("iris", clk.t)
    core.voice("souris", clk.t + 0.2)
    clk.run(core, 1.0, absent=True)
    assert core.mouse


# --- deux mains ---------------------------------------------------------------------
def test_deux_mains_celle_qui_bouge_agit():
    tr = HandTracker()
    t = 0.0
    left, right = mirror(hand("open", cx=0.7)), hand("open", cx=0.7)  # positions miroir : 0.3 et 0.7
    for i in range(10):
        t += 1 / 30
        tr.update([left, right], t)
    for i in range(10):  # la main droite bouge, la gauche reste posée
        t += 1 / 30
        moved = hand("open", cx=0.7 + 0.01 * (i + 1))
        pts = tr.update([left, moved], t)
    assert pts is moved
    for i in range(10):  # maintenant la gauche bouge, la droite s'arrête
        t += 1 / 30
        movedl = mirror(hand("open", cx=0.7 + 0.015 * (i + 1)))
        pts = tr.update([movedl, moved], t)
    assert pts is movedl


def test_main_perdue_une_ou_deux_images_conservee():
    tr = HandTracker()
    h = hand("open")
    tr.update([h], 0.0)
    assert tr.update([], 0.033) is h
    assert tr.update([], 0.066) is h
    tr.update([], 0.1)
    assert tr.update([], 0.133) is None


def test_main_gauche_comme_droite():
    cfg = Config()
    for name, pose in {"open": Pose.OPEN, "fist": Pose.FIST, "point": Pose.POINT}.items():
        assert compute_features(mirror(hand(name)), cfg).pose == pose


# --- sécurité -------------------------------------------------------------------------
def test_controleur_relache_tout_et_plafond():
    cfg = Config()
    fake = FakeBackend()
    ctl = Controller(fake, cfg)
    ctl.execute([("press", "mouse", "left")], 0.0)
    ctl.execute([], cfg.max_hold_s + 0.1)
    assert ("button", "left", False) in fake.events
    ctl.execute([("press", "key", "space")], 10.0)
    ctl.execute([("release_all",)], 10.1)
    assert fake.events[-1] == ("key", "space", False) and ctl.held == {}


def test_desactive_ignore_tout():
    core, clk = Core(Config()), Clock()
    core.disable(0.0)
    acts = clk.run(core, 2.0, cx=0.5, to_cx=0.9)
    assert acts == [] and core.mode == Mode.DISABLED


def test_one_euro_lisse_le_tremblement():
    f = OneEuro(1.0, 0.01)
    out = [f(100 + (3 if i % 2 else -3), i / 30) for i in range(60)]
    assert max(out[30:]) - min(out[30:]) < 2.0


def test_main_immobile_n_ouvre_rien_ni_clic():
    """Réfléchir main immobile en mode souris : aucun menu, aucun clic, même 30 s."""
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    clk.run(core, 0.5, cx=0.5, cy=0.52, to_cx=0.6)
    acts = clk.run(core, 30.0, cx=0.6, cy=0.52, jitter=0.003)
    assert not core.menu.is_open and kinds(acts, "click") == [] and core.progress() is None


def test_iris_ne_fige_plus_le_curseur_mais_le_clic_vise_juste():
    """Demande de l'utilisateur (12/11) : « iris » ne fige plus le curseur. Le clic revient là où était le
    curseur au début de « iris », puis clique ; la main peut avoir dérivé en parlant."""
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    clk.run(core, 0.5, cx=0.5, cy=0.52, to_cx=0.6)
    aimed, t_iris = core.cursor, clk.t
    core.freeze_for_voice(clk.t)                            # « iris » dans le texte provisoire : sans effet
    acts = clk.run(core, 0.6, cx=0.6, cy=0.52, to_cx=0.66)  # la main dérive en parlant
    assert kinds(acts, "move") and core.cursor != aimed     # le curseur suit toujours la main
    core.voice("iris", clk.t, t_start=t_iris)
    acts = core.voice("clic", clk.t + 0.1)
    assert acts == [("move", *aimed), ("click", "left")] and core.cursor == aimed


def test_clic_chrome_sans_iris_vise_le_debut_du_mot():
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    core.mode = Mode.CHROME
    clk.run(core, 0.5, cx=0.5, cy=0.52, to_cx=0.6)
    aimed, t0 = core.cursor, clk.t
    clk.run(core, 0.4, cx=0.6, cy=0.52, to_cx=0.65)
    acts = core.voice("clic", clk.t, t_start=t0)
    assert acts == [("move", *aimed), ("click", "left")]


def test_main_immobile_en_lecture_ne_propose_plus_la_souris():
    """La bulle « SOURIS ? » est remplacée par « iris souris » : rien ne s'ouvre main immobile."""
    core, clk = Core(READ), Clock()
    clk.run(core, 10.0, cx=0.5, cy=0.6, jitter=0.004)
    assert core.bubble is None and core.mode == Mode.READING and not core.listening(clk.t)


def test_demarrage_en_neutre_la_main_ne_fait_rien():
    """Main posée sur la cuisse, qui bouge un peu : en neutre, ni page, ni défilement, ni rien."""
    core, clk = Core(Config()), Clock()
    assert core.mode == Mode.NEUTRAL
    acts = clk.run(core, 5.0, cx=0.9, cy=0.9, jitter=0.01) + clk.run(core, 2.0, cx=0.5, cy=0.1, to_cx=0.1)
    assert [a for a in acts if a[0] != "move"] == []
    core.voice("iris", clk.t)
    core.voice("lecture", clk.t + 0.2)
    assert core.mode == Mode.READING


def test_clic_vocal_date_absurde_ne_deplace_pas_le_curseur():
    """Horloge audio décalée (repartie de zéro) : le curseur ne doit pas sauter vers une vieille position."""
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    clk.run(core, 0.5, cx=0.5, cy=0.52, to_cx=0.6)
    clk.run(core, 6.0, cx=0.6, cy=0.52)                     # main immobile
    here = core.cursor
    core.voice("iris", clk.t, t_start=clk.t - 50.0)          # date fausse, bien plus vieille que l'historique
    acts = core.voice("clic", clk.t + 0.1, t_start=clk.t - 49.0)
    assert acts == [("click", "left")] and core.cursor == here


# --- souris : centre, retour au centre, index = clic -----------------------------------------------
def test_mode_souris_commence_au_centre():
    core, clk = Core(Config()), Clock()
    core.cursor = core._cursor_f = (100, 1000)               # curseur laissé n'importe où
    acts = _enter_mouse(core, clk)
    assert ("move", 960, 540) in acts


def test_main_revenue_le_curseur_repart_du_centre():
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    clk.run(core, 0.5, cx=0.5, cy=0.52, to_cx=0.7)
    assert core.cursor[0] > 1100
    clk.run(core, 1.0, absent=True)
    acts = clk.run(core, 0.1, cx=0.3, cy=0.52)
    assert ("move", 960, 540) in acts


def _poses(core, monkeypatch, seq):
    """Fait « voir » une suite de poses au moteur (sans vraie main en 3D)."""
    import motionzero.core as mc
    it = iter(seq)
    monkeypatch.setattr(mc, "flexion", lambda w: None)
    monkeypatch.setattr(mc, "classify", lambda f, c: (next(it), None))
    core.pose_cents = {"x": 1}
    core.cfg.hand_click_enabled = True   # clic par la main : désactivé par défaut, testé quand même


def test_clic_par_la_main_desactive_par_defaut(monkeypatch):
    """Réglage par défaut : rouvrir la main ne clique plus (clic à la voix, pédale plus tard)."""
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    _poses(core, monkeypatch, ["closed"] * 10 + ["open"] * 60 + ["closed"] * 10)
    core.cfg.hand_click_enabled = False
    acts = []
    for _ in range(80):
        clk.t += 0.05
        acts += core.step(hand_pts(), clk.t, world="x")
    assert not [a for a in acts if a[0] in ("press", "release", "click")]


def test_ouvrir_la_main_clique(monkeypatch):
    """Ouverte brièvement puis refermée : un clic simple, rien de maintenu."""
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    _poses(core, monkeypatch, ["closed"] * 10 + ["open"] * 20 + ["closed"] * 10)   # ouverte ~1 s
    acts = []
    for _ in range(40):
        clk.t += 0.05
        acts += core.step(hand_pts(), clk.t, world="x")
    assert [a for a in acts if a[0] in ("press", "release", "click")] == [("click", "left")]


def test_gardee_ouverte_plus_de_2_s_maintient_puis_relache(monkeypatch):
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    _poses(core, monkeypatch, ["closed"] * 10 + ["open"] * 60 + ["closed"] * 10)   # ouverte ~3 s
    acts = []
    for _ in range(80):
        clk.t += 0.05
        acts += core.step(hand_pts(), clk.t, world="x")
    assert [a for a in acts if a[0] in ("press", "release", "click")] == [
        ("click", "left"), ("press", "mouse", "left"), ("release", "mouse", "left")]


def test_main_revenue_deja_ouverte_ne_clique_pas(monkeypatch):
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    _poses(core, monkeypatch, ["open"] * 30 + ["point"] * 10 + ["open"] * 10)   # index puis ouverte : non plus
    acts = []
    for _ in range(50):
        clk.t += 0.05
        acts += core.step(hand_pts(), clk.t, world="x")
    assert [a for a in acts if a[0] in ("click", "press")] == []


def hand_pts():
    return hand("open", 0.5, 0.52)


def test_clic_index_ne_bouge_pas_le_curseur(monkeypatch):
    """Le clic part là où est le curseur : aucun déplacement au moment du clic."""
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    _poses(core, monkeypatch, ["closed"] * 10 + ["open"] * 5)
    acts = []
    for i in range(15):
        clk.t += 0.05
        acts += core.step(hand_pts(), clk.t, world="x")
    i_click = acts.index(("click", "left"))
    assert acts[i_click - 1][0] != "move" or acts[i_click - 1] == ("move", *core.cursor)
    assert [a for a in acts[i_click:] if a[0] == "move"] == []


def test_main_perdue_pendant_l_appui_relache(monkeypatch):
    core, clk = Core(Config()), Clock()
    _enter_mouse(core, clk)
    _poses(core, monkeypatch, ["closed"] * 10 + ["open"] * 60)
    for _ in range(70):
        clk.t += 0.05
        core.step(hand_pts(), clk.t, world="x")
    assert core.pressing
    acts = clk.run(core, 1.0, absent=True)
    assert ("release_all",) in acts and not core.pressing


def test_main_un_peu_basse_ne_defile_plus():
    """Mesuré : la zone de défilement (25 % en bas) était beaucoup trop large. Paume à ~0,84 : rien."""
    core, clk = Core(READ), Clock()
    clk.run(core, 0.5, cx=0.5, cy=0.5)
    acts = clk.run(core, 0.1, cx=0.5, cy=0.5, to_cy=0.95) + clk.run(core, 2.0, cx=0.5, cy=0.95)
    assert kinds(acts, "scroll") == []
