"""Correctifs de l'audit du 19/11 (#48, #51…)."""
import time

import numpy as np

from motionzero import camera as cam_mod
from motionzero.app import ERROR_NOTICE, note_error, pick_toast


class FakeCap:
    def __init__(self, frames):
        self.frames = list(frames)

    def read(self):
        return (True, self.frames.pop(0)) if self.frames else (False, None)

    def release(self):
        pass


def test_delai_de_reconnexion_croissant_et_plafonne():
    d = [cam_mod.reconnect_delay(n) for n in (1, 2, 3, 4, 5, 6, 20)]
    assert d == [1, 2, 4, 8, 16, 30, 30]


def _camera(monkeypatch, frames, opens):
    monkeypatch.setattr(cam_mod, "reconnect_delay", lambda n: 0.0)
    c = cam_mod.Camera(lost_after_s=0.0)
    c.cap = FakeCap(frames)
    c.running = True
    calls = []

    def fake_open():
        calls.append(1)
        if len(calls) >= opens:
            c.running = False
        return None
    c._open = fake_open
    return c, calls


def test_camera_absente_cause_autre_appli(monkeypatch):
    c, calls = _camera(monkeypatch, [], opens=3)
    c._run()
    assert c.fails >= 2 and "autre appli" in c.problem[0]


def test_images_rejetees_cause_illisible(monkeypatch):
    noir = np.zeros((480, 640, 3), np.uint8)    # uniforme : rejetée
    c, _ = _camera(monkeypatch, [noir] * 5, opens=1)
    c._run()
    assert "illisible" in c.problem[0]


def test_bonne_image_efface_le_probleme(monkeypatch):
    rng = np.random.default_rng(0)
    img = np.clip(np.cumsum(rng.integers(-3, 4, (480, 640, 3)), axis=1) + 120, 0, 255).astype(np.uint8)
    c, _ = _camera(monkeypatch, [img], opens=1)
    c.fails, c.problem = 4, ("x", 0.0)
    c._run()
    assert c.fails == 1 and c.problem[0] != "x"   # remis à 0 par la bonne image, puis une nouvelle perte


def test_erreur_simple_puis_repetee():
    ERROR_NOTICE.update(t=[], notice=None)
    note_error("boucle")
    assert ERROR_NOTICE["notice"][0].startswith("ERREUR (boucle)")
    for _ in range(4):
        note_error("boucle")
    assert "REPETEE" in ERROR_NOTICE["notice"][0]


def test_toast_le_plus_recent_gagne():
    assert pick_toast(None, ("a", 1.0), ("b", 3.0), ("c", 2.0)) == ("b", 3.0)
    assert pick_toast(None, None) is None
