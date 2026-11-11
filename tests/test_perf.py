"""Lot 1 de performance : détection ralentie sans main, 2e avis réveillé par la parole, Whisper déchargé."""
import queue
import threading
import time

import numpy as np

from motionzero import ask, voice
from motionzero.app import DETECT_MAX_FPS, IDLE_DETECT_FPS, detect_period


def test_detection_ralentie_sans_main_et_en_pause():
    assert detect_period(False, last_hand_t=10.0, t=10.5) == 1.0 / DETECT_MAX_FPS   # main vue il y a 0,5 s
    assert detect_period(False, last_hand_t=10.0, t=13.0) == 1.0 / IDLE_DETECT_FPS  # plus de main : ralenti
    assert detect_period(True, last_hand_t=10.0, t=10.1) == 1.0 / IDLE_DETECT_FPS   # appli en pause


class FakeRec:
    def __init__(self):
        self.fed, self.resets = [], 0

    def AcceptWaveform(self, b):
        self.fed.append(b)
        return False

    def PartialResult(self):
        return '{"partial": ""}'

    def Result(self):
        return '{"text": ""}'

    def Reset(self):
        self.resets += 1


def _listener():
    v = voice.VoiceListener.__new__(voice.VoiceListener)
    voice.VoiceListener.__init__(v, "x")
    v.rec, v.free = FakeRec(), FakeRec()
    v._free_final = (0.0, "")
    from collections import deque
    v._free_pre = deque(maxlen=int(voice.FREE_PREROLL_S / 0.03))
    v._free_until, v._was_muted = 0.0, False
    v.samples = 0
    return v


def _block(level):
    return (np.full(480, level, np.int16)).tobytes()


def test_deuxieme_avis_dort_dans_le_silence_et_rejoue_le_debut_de_phrase():
    v = _listener()
    for _ in range(100):                       # 3 s de silence
        v.audio.put(_block(10))
        v._step()
    assert v.free.fed == []                    # reconnaissance libre jamais lancée
    assert len(v.rec.fed) == 100               # la grammaire (« iris ») écoute toujours
    v.audio.put(_block(5000))                  # quelqu'un parle
    v._step()
    # le son d'avant (1 s) lui est redonné, puis le morceau qui l'a réveillée
    assert len(v.free.fed) == v._free_pre.maxlen + 1


def test_sourdine_remet_a_zero_une_seule_fois():
    v = _listener()
    v.muted = True
    for _ in range(50):
        v.audio.put(_block(10))
        v._step()
    assert v.rec.resets == 1 and v.free.resets == 1


def test_enregistrement_plafonne():
    v = _listener()
    v.start_capture()
    v.capture.extend([b"x"] * int(voice.MAX_CAPTURE_S / 0.03))
    v.audio.put(_block(10))
    v._step()
    assert len(v.capture) == int(voice.MAX_CAPTURE_S / 0.03)


class FakeWhisper:
    loads = 0

    def __init__(self, *a, **k):
        FakeWhisper.loads += 1

    def transcribe(self, pcm, **k):
        class S:
            text = " bonjour "
        return [S()], None


def test_whisper_decharge_puis_recharge(monkeypatch):
    import faster_whisper
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisper)
    monkeypatch.setattr(ask, "_nvidia_dlls", lambda: None)
    a = ask.Asker()
    assert a._transcribe(b"\0\0" * 1600, 16000) == "bonjour"
    assert FakeWhisper.loads == 1
    a._used_t -= ask.WHISPER_IDLE_S + 1        # inutilisé depuis longtemps
    monkeypatch.setattr(time, "sleep", lambda s: None)
    calls = []

    def one_round():   # un seul tour de la boucle de veille
        if calls:
            raise SystemExit
        calls.append(1)
    monkeypatch.setattr(time, "sleep", lambda s: one_round())
    try:
        a._reaper()
    except SystemExit:
        pass
    assert a._whisper is None
    assert a._transcribe(b"\0\0" * 1600, 16000) == "bonjour"   # rechargé à la demande
    assert FakeWhisper.loads == 2


def test_whisper_en_panne_sur_carte_graphique_passe_au_processeur(monkeypatch):
    import faster_whisper
    seen = []

    def model(name, device, **k):
        seen.append((device, k.get("cpu_threads")))
        if device == "cuda":
            raise RuntimeError("pas de CUDA")
        return FakeWhisper()
    monkeypatch.setattr(faster_whisper, "WhisperModel", model)
    monkeypatch.setattr(ask, "_nvidia_dlls", lambda: None)
    a = ask.Asker()
    assert a._transcribe(b"\0\0" * 1600, 16000) == "bonjour"
    assert seen == [("cuda", None), ("cpu", ask.WHISPER_CPU_THREADS)]


def test_deux_transcriptions_en_meme_temps_un_seul_chargement(monkeypatch):
    import faster_whisper
    FakeWhisper.loads = 0
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisper)
    monkeypatch.setattr(ask, "_nvidia_dlls", lambda: None)
    a = ask.Asker()
    out = queue.Queue()
    ths = [threading.Thread(target=lambda: out.put(a._transcribe(b"\0\0" * 1600, 16000))) for _ in range(4)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert FakeWhisper.loads == 1 and out.qsize() == 4
