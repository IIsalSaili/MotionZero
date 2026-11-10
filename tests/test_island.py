"""Île Dot Iris : ce qu'elle affiche selon l'état (sans fenêtre)."""
from motionzero.ui import island_text


def test_mode_seul_au_repos():
    assert island_text({"mode": "LECTURE"}) == ("LECTURE", None, False)
    assert island_text({"mode": "DESACTIVE"})[0] == "PAUSE"


def test_priorites():
    st = {"mode": "SOURIS", "toast": "CLIC GAUCHE", "toast_age": 0.5, "lost": True}
    assert island_text(st)[1] == "Main non détectée"
    assert island_text({**st, "listening": True})[1] == "Iris écoute…"
    assert island_text({**st, "dictating": True})[1] == "Claude t'écoute"


def test_message_disparait_apres_2_5_s():
    assert island_text({"mode": "LECTURE", "toast": "CHROME", "toast_age": 1.0})[1] == "CHROME"
    assert island_text({"mode": "LECTURE", "toast": "CHROME", "toast_age": 3.0})[1] is None


def test_logo_de_l_ilot():
    from motionzero.ui import islet_logo
    assert islet_logo({"mode": "NEUTRE"}, False) == "neutre"
    assert islet_logo({"mode": "LECTURE"}, True) == "lecture_ferme"
    assert islet_logo({"mode": "SOURIS"}, False) == "souris"
    assert islet_logo({"mode": "SOURIS", "ok_flash": True}, True) == "ok"     # vert, sans clignement
    assert islet_logo({"mode": "DESACTIVE"}, False) == "neutre"
