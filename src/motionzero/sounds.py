"""Petits sons graves et doux (même style que la notification validée, encore plus bas)."""
import math
import os
import struct
import wave

try:
    import winsound
except ImportError:  # hors Windows
    winsound = None

RATE = 44100
TONES = {  # nom: (fréquence Hz, durée s)
    "LECTURE": (196.0, 0.35),
    "SOURIS": (246.9, 0.35),
    "REPOS": (146.8, 0.35),
    "DESACTIVE": (110.0, 0.5),
    "CLIC": (220.0, 0.12),
    "ECOUTE": (174.6, 0.25),
    "PARLE": (329.6, 0.22),    # micro de Claude prêt : parle
    "COUPE": (130.8, 0.3),     # micro de Claude coupé
}
AMP = 0.05


def _write(path, freq, dur):
    n = int(dur * RATE)
    fade = min(0.08, dur / 3)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        frames = bytearray()
        for i in range(n):
            t = i / RATE
            env = 1.0
            if t < fade:
                env = 0.5 - 0.5 * math.cos(math.pi * t / fade)
            elif t > dur - fade:
                env = 0.5 - 0.5 * math.cos(math.pi * (dur - t) / fade)
            v = (math.sin(2 * math.pi * freq * t) + 0.55 * math.sin(4 * math.pi * freq * t)) / 1.55
            frames += struct.pack("<h", int(AMP * env * v * 32767))
        w.writeframes(bytes(frames))


class Sounds:
    def __init__(self, folder, enabled=True):
        self.enabled = enabled and winsound is not None
        self.paths = {}
        if not self.enabled:
            return
        os.makedirs(folder, exist_ok=True)
        for name, (freq, dur) in TONES.items():
            path = os.path.join(folder, f"{name.lower()}.wav")
            if not os.path.exists(path):
                _write(path, freq, dur)
            self.paths[name] = path

    def play(self, name):
        path = self.paths.get(name)
        if self.enabled and path:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
