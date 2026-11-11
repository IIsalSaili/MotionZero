"""Balayage : des milliers de commandes vocales et d'états au hasard ne doivent jamais lever d'erreur."""
import random

from motionzero.config import Config
from motionzero.core import Core
from motionzero.voice import WORDS


def _hand(rng):
    cx, cy = rng.random(), rng.random()
    return [(min(max(cx + rng.uniform(-0.1, 0.1), 0), 1), min(max(cy + rng.uniform(-0.1, 0.1), 0), 1))
            for _ in range(21)]


def test_commandes_au_hasard_ne_plantent_jamais():
    import numpy as np
    from motionzero.overlay import render
    view = np.zeros((480, 640, 3), np.uint8)
    words = list(WORDS) + ["inconnu", "[unk]"]
    for seed in range(30):
        rng = random.Random(seed)
        core = Core(Config(), (0, 0, 1920, 1080))
        t, speech = 0.0, 0.0
        for _ in range(1500):
            t += rng.uniform(0.01, 0.6)
            r = rng.random()
            if r < 0.3:
                core.voice(rng.choice(words), t, t_start=t - 0.2)
            elif r < 0.6:
                core.step(_hand(rng) if rng.random() < 0.8 else None, t)
            if rng.random() < 0.5:
                speech = t
            for tick in (core.dictation_tick, core.ask_tick, core.type_tick, core.open_tick):
                tick(t, speech)
            core.listening(t)
            core.confirming(t)
            core.progress()
            if rng.random() < 0.05:   # l'aperçu (là où « iris ouvre » avait planté) : dessiné dans tous les états
                render(view, core, [], 30.0, False, rng.choice(["ok", "perdue"]), None, voice_on=True)


def test_ile_avec_etats_au_hasard():
    from motionzero.ui import island_text
    rng = random.Random(1)
    choices = {
        "mode": ["SOURIS", "LECTURE", "NEUTRE", "DESACTIVE", None, ""],
        "qa": [None, {}, {"phase": "listening"}, {"phase": "thinking", "question": "q"},
               {"phase": "answer", "question": "", "answer": "r", "left": 3.0}, {"phase": "error", "answer": ""}],
        "toast": [None, "", "CLIC GAUCHE", "PAS COMPRIS : x" * 10],
        "toast_age": [0.0, 0.5, 5.0, 1e9],
    }
    for _ in range(3000):
        st = {k: rng.choice(v) for k, v in choices.items() if rng.random() < 0.8}
        for k in ("dictating", "typing", "confirming", "listening", "lost"):
            if rng.random() < 0.5:
                st[k] = rng.random() < 0.5
        island_text(st)
