"""Île Dot Iris : ce qu'elle affiche selon l'état (sans fenêtre)."""
from motionzero.ui import island_text


def test_mode_seul_au_repos():
    assert island_text({"mode": "LECTURE"}) == ("LECTURE", None, False)
    assert island_text({"mode": "DESACTIVE"})[0] == "PAUSE"


def test_priorites():
    st = {"mode": "NEUTRE", "mouse": True, "toast": "CLIC GAUCHE", "toast_age": 0.5, "lost": True}
    assert island_text(st)[1] == "Main non détectée"
    assert island_text({**st, "listening": True})[1] == "Iris écoute…"
    assert island_text({**st, "dictating": True})[1] == "Claude t'écoute"


def test_message_disparait_apres_2_5_s():
    assert island_text({"mode": "LECTURE", "toast": "CHROME", "toast_age": 1.0})[1] == "CHROME"
    assert island_text({"mode": "LECTURE", "toast": "CHROME", "toast_age": 3.0})[1] is None


def test_logo_de_l_ilot_toujours_le_classique():
    from motionzero.ui import islet_logo
    for mode in ("NEUTRE", "LECTURE", "SOURIS", "CHROME", "DESACTIVE"):
        assert islet_logo({"mode": mode}, False) == "neutre"
        assert islet_logo({"mode": mode, "ok_flash": True}, True) == "neutre_ferme"


def test_cercle_du_logo_selon_le_mode():
    from motionzero.ui import BLUE, GREEN, ORANGE, RING_DEFAULT, islet_ring
    assert islet_ring({"mode": "NEUTRE"}, 0)[0] == RING_DEFAULT
    assert islet_ring({"mode": "SOURIS"}, 0)[0] == ORANGE
    assert islet_ring({"mode": "CHROME"}, 0)[0] == BLUE
    # commande comprise : vert, puis la couleur du mode, puis vert (clignote)
    assert islet_ring({"mode": "CHROME", "ok_flash": True}, 0.0)[0] == GREEN
    assert islet_ring({"mode": "CHROME", "ok_flash": True}, 0.2)[0] == BLUE
    assert islet_ring({"mode": "CHROME", "ok_flash": True}, 0.3)[0] == GREEN
