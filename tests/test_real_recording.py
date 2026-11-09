"""Tests sur le vrai enregistrement de l'utilisateur (sauté s'il est absent)."""
import json
import os

import pytest

from motionzero.config import Config
from motionzero.gestures import PinchDetector
from motionzero.hand import compute_features

REC = os.path.join(os.path.dirname(__file__), "..", "recordings", "essai1.jsonl")


@pytest.mark.skipif(not os.path.exists(REC), reason="enregistrement absent")
def test_pincements_reels_sans_coupure_due_au_tremblement():
    cfg = Config()
    det, downs, ups = PinchDetector(cfg), 0, []
    for line in open(REC, encoding="utf-8"):
        r = json.loads(line)
        if r["phase"] != "pinch" or not r["pts"]:
            continue
        ev = det.update(compute_features([tuple(p) for p in r["pts"]], cfg), r["t"])
        if ev and ev[0] == "down":
            downs += 1
        elif ev:
            ups.append(ev[2])
    assert downs == 2                      # 2 pincements complets (le 3e coupé par la fin de phase)
    assert all(d <= cfg.pinch_click_max_s for d in ups)
