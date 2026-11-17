"""« iris traducteur » (#14) : découpage du son, fils de travail, échecs, commande, bandeau."""
import time

import numpy as np

from motionzero import traducteur as tr
from motionzero.traducteur import Decoupeur, Traducteur, to_mono_16k
from motionzero.ui import subs_text


def _tone(s, amp=0.1):
    t = np.arange(int(tr.SR * s)) / tr.SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _blank(s):
    return np.zeros(int(tr.SR * s), np.float32)


def _wait(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_stereo_48k_devient_mono_16k():
    st = np.stack([np.full(4800, 16384, np.int16), np.zeros(4800, np.int16)], axis=1).ravel()
    out = to_mono_16k(st.tobytes(), 48000, 2)
    assert len(out) == 1600 and abs(out.mean() - 0.25) < 1e-3


def test_phrase_coupee_au_silence():
    cut = Decoupeur()
    assert cut.feed(_tone(2.0)) == []                  # toujours en train de parler
    chunks = cut.feed(_blank(1.0))
    assert len(chunks) == 1 and 2.0 <= len(chunks[0]) / tr.SR < 3.0


def test_bruit_trop_court_ignore_et_silence_seul_rien():
    cut = Decoupeur()
    assert cut.feed(_blank(3.0)) == []
    assert cut.feed(np.concatenate([_tone(0.3), _blank(1.0)])) == []


def test_parole_sans_blanc_coupee_au_maximum():
    chunks = Decoupeur().feed(_tone(tr.MAX_CHUNK_S + 1))
    assert len(chunks) == 1


def _opener(blocks):
    """Faux flux loopback 16 kHz mono : rend les blocs puis du silence."""
    closed = []

    def opener():
        it = iter(blocks)

        def read():
            time.sleep(0.001)
            b = next(it, None)
            return (b if b is not None else _blank(0.1)).__mul__(32767).astype(np.int16).tobytes()
        return read, lambda: closed.append(True), tr.SR, 1
    return opener, closed


def test_traduit_et_affiche_puis_s_eteint():
    opener, closed = _opener([_tone(1.5), _blank(1.0)])
    t = Traducteur(lambda pcm: "Hello world", opener=opener)
    assert t.snapshot() is None
    t.start()
    assert _wait(lambda: t.snapshot()["lines"] == ["Hello world"])
    t.stop()
    assert t.snapshot() is None
    assert _wait(lambda: closed == [True])             # flux son rendu à l'arrêt


def test_rien_entendu_pas_de_ligne():
    opener, _ = _opener([_tone(1.5), _blank(1.0)])
    t = Traducteur(lambda pcm: "   ", opener=opener)
    t.start()
    time.sleep(0.3)
    assert t.snapshot() == {"lines": [], "error": None}
    t.stop()


def test_whisper_en_erreur_le_traducteur_continue():
    calls = []

    def flaky(pcm):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("CUDA")
        return "second"
    opener, _ = _opener([_tone(1.5), _blank(1.0), _tone(1.5), _blank(1.0)])
    t = Traducteur(flaky, opener=opener)
    t.start()
    assert _wait(lambda: t.snapshot()["lines"] == ["second"])
    t.stop()


def test_pas_de_son_capte_message_affiche():
    def broken():
        raise OSError("pas de loopback")
    t = Traducteur(lambda pcm: "x", opener=broken)
    t.start()
    assert _wait(lambda: t.snapshot()["error"] is not None)
    assert subs_text(t.snapshot()) == "Son du PC impossible à capter"
    t.stop()


def test_lignes_expirees_et_deux_au_plus(monkeypatch):
    t = Traducteur(lambda pcm: "", opener=None)
    t.on = True
    now = time.perf_counter()
    t.lines = [("vieille", now - tr.SHOW_S - 1), ("a", now), ("b", now)]
    assert t.snapshot()["lines"] == ["a", "b"]
    assert subs_text(t.snapshot()) == "a\nb"
    assert subs_text({"lines": [], "error": None}) is None


def test_commande_bascule():
    from motionzero.core import Core
    core = Core.__new__(Core)
    core.translating = False
    acts = []
    assert core._cmd_translator("traducteur", 0.0, acts) == "TRADUCTEUR ALLUME"
    assert core._cmd_translator("traducteur", 1.0, acts) == "TRADUCTEUR ETEINT"
    assert acts == [("traducteur", True), ("traducteur", False)]


def test_mot_ecoute_et_commande_connue():
    from motionzero.core import COMMANDS
    from motionzero.voice import GRAMMAR, WORDS
    assert WORDS["traducteur"] == "traducteur" and COMMANDS["traducteur"] == "translator"
    assert '"traducteur"' in GRAMMAR
