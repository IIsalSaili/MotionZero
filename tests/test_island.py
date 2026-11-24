"""Île Dot Iris : ce qu'elle affiche selon l'état (sans fenêtre)."""
from motionzero.ui import island_text


def test_mode_seul_au_repos():
    assert island_text({"mode": "LECTURE"}) == ("LECTURE", None, False)
    assert island_text({"mode": "DESACTIVE"})[0] == "PAUSE"


def test_priorites():
    st = {"mode": "NEUTRE", "mouse": True, "toast": "CLIC GAUCHE", "toast_age": 0.5, "lost": True}
    assert island_text(st)[1] == "Main perdue"
    assert island_text({**st, "listening": True})[1] == "Écoute"
    assert island_text({**st, "dictating": True})[1] == "Claude écoute"


def test_message_disparait_apres_4_s():
    assert island_text({"mode": "LECTURE", "toast": "CHROME", "toast_age": 1.0})[1] == "CHROME"
    assert island_text({"mode": "LECTURE", "toast": "CHROME", "toast_age": 4.5})[1] is None


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
    # commande comprise : vert, puis la couleur du mode, puis vert (clignote, moins de 3 fois par seconde)
    assert islet_ring({"mode": "CHROME", "ok_flash": True}, 0.0)[0] == GREEN
    assert islet_ring({"mode": "CHROME", "ok_flash": True}, 0.2)[0] == BLUE
    assert islet_ring({"mode": "CHROME", "ok_flash": True}, 0.36)[0] == GREEN


def test_mode_tete_parle_du_visage():
    from motionzero.ui import island_text
    st = {"mouse": True, "pointer": "tete", "lost": True}
    assert island_text(st)[1] == "Visage perdu"
    assert island_text({"mouse": True, "pointer": "tete", "lost": False, "arming": True})[1] == "Tête de face"
    assert island_text({"mouse": True, "pointer": "tete", "lost": False, "arming": False})[1] is None


# ---- #18 / #27 (24/11) : un ou deux mots en haut, une ligne courte en bas
def test_haut_deux_mots_au_plus_le_reste_en_bas():
    st = {"mode": "CHROME", "mouse": True, "focus": True, "bypass": True}
    top, bas, actif = island_text(st)
    assert top == "CHROME · SOURIS" and bas == "focus · bypass" and not actif   # rien n'est caché
    assert island_text({"mode": "NEUTRE"})[0] == "NEUTRE"
    assert island_text({"mode": "NEUTRE", "candidature": True, "focus": True, "bypass": True})[:2] ==         ("CANDIDATURE · FOCUS", "bypass")
    assert island_text({"mode": "NEUTRE", "mouse": True, "dragging": True})[0] == "AGRIPPE · SOURIS"
    assert island_text({**st, "toast": "ONGLET FERME", "toast_age": 0.5})[1] == "ONGLET FERME"   # le retour passe devant
    for s in ({"mode": m, "mouse": a, "focus": b, "bypass": c, "candidature": d, "dragging": e}
              for m in ("NEUTRE", "CHROME", "LECTURE") for a in (0, 1) for b in (0, 1) for c in (0, 1)
              for d in (0, 1) for e in (0, 1)):
        assert len(island_text(s)[0].split(" · ")) <= 2


def test_ligne_du_bas_defile_seulement_si_trop_longue():
    from motionzero.ui import TICKER_PAUSE_S, ticker_offset
    assert ticker_offset(100, 200, 5.0) == 0.0
    assert ticker_offset(500, 200, 0.1) == 0.0                              # pause au début
    assert ticker_offset(500, 200, TICKER_PAUSE_S + 1.0) < 0
    assert ticker_offset(500, 200, TICKER_PAUSE_S + 60.0) >= -300            # jamais au-delà du bout du texte
