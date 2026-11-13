"""Gardien : relance seulement quand il faut (pas après STOP, pas en boucle, pas pendant le chargement)."""
import os

from motionzero import garde
from motionzero.garde import decide, too_many

ALIVE = lambda pid: True
DEAD = lambda pid: False


def beat(t, loop_age=0.0, pid=42):
    return {"pid": pid, "t": t, "loop_age": loop_age}


def test_tout_va_bien():
    assert decide(beat(100), False, ALIVE, 101, None) == "rien"


def test_iris_morte_sans_arret_voulu():
    assert decide(beat(100), False, DEAD, 101, None) == "lance"


def test_aucun_battement():
    assert decide(None, False, ALIVE, 101, None) == "lance"


def test_stop_volontaire_pas_de_relance():
    assert decide(beat(100), True, DEAD, 101, None) == "rien"
    assert decide(None, True, DEAD, 101, None) == "rien"


def test_battement_trop_vieux():
    assert decide(beat(100), False, ALIVE, 100 + garde.BEAT_STALE_S + 1, None) == "tue"


def test_boucle_figee():
    assert decide(beat(100, loop_age=garde.FREEZE_S + 1), False, ALIVE, 101, None) == "tue"
    assert decide(beat(100, loop_age=garde.FREEZE_S - 1), False, ALIVE, 101, None) == "rien"


def test_delai_apres_lancement():
    assert decide(None, False, DEAD, 110, last_launch=100) == "rien"
    assert decide(None, False, DEAD, 100 + garde.LAUNCH_GRACE_S + 1, last_launch=100) == "lance"


def test_trop_de_relances():
    assert not too_many([10, 20], 30)
    assert too_many([10, 20, 30], 40)
    assert not too_many([10, 20, 30], 30 + garde.WINDOW_S)


def test_battement_ecrit_et_relu(tmp_path):
    p = str(tmp_path / "b.json")
    garde.write_beat(3.0, path=p, pid=7, now=123.0)
    assert garde.read_beat(p) == {"pid": 7, "t": 123.0, "loop_age": 3.0}


def test_battement_illisible(tmp_path):
    p = tmp_path / "b.json"
    p.write_text("{coupe", encoding="utf-8")
    assert garde.read_beat(str(p)) is None
    p.write_text("[1]", encoding="utf-8")
    assert garde.read_beat(str(p)) is None
    assert garde.read_beat(str(tmp_path / "absent.json")) is None


def test_arret_voulu_note_puis_efface(tmp_path):
    p = str(tmp_path / "arret")
    garde.mark_stop(p)
    assert os.path.exists(p)
    garde.clear_stop(p)
    assert not os.path.exists(p)
    garde.clear_stop(p)          # déjà effacé : pas d'erreur


def test_pid_courant_vivant():
    assert garde.pid_alive(os.getpid())
