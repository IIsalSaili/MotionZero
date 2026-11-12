"""Sons d'Iris : fichiers de assets/sounds (packs libres, voir assets/sounds/CREDITS.md), mélangés par un flux
sounddevice. Plusieurs sons peuvent jouer ensemble ; l'alarme boucle et monte doucement (comme un réveil de
téléphone) jusqu'à stop_alarm(). Une carte son absente ou en panne ne fait jamais planter Iris : tout se tait.
"""
import logging
import os
import threading
import wave

import numpy as np

log = logging.getLogger(__name__)
RATE = 44100
# événement -> fichier. Les modes (et la souris) partagent le même son ; « CLIC » n'a plus de son (choix du 12/11).
FILES = {"ECOUTE": "ecoute", "OK": "ok", "NON": "non", "MODE": "mode", "PARLE": "parle", "COUPE": "coupe",
         "RAPPEL": "rappel", "ALARME": "alarme"}
ALIASES = {"LECTURE": "MODE", "CHROME": "MODE", "NEUTRE": "MODE", "REPOS": "MODE", "SOURIS": "MODE",
           "DESACTIVE": "MODE"}
RAMP_S = 5.0                  # alarme : de léger au volume normal en 5 s (60 s : inaudible pendant que la voix lit)
RAMP_FROM_DB, RAMP_TO_DB = -30.0, -4.0
STOP_FADE_S = 0.03            # « stop » : fondu très court, pas de clic
CUT_FADE_S = 0.02             # un nouveau son coupe le précédent (« iris stop » dit d'un trait : 2 sons au même
                              # instant qui s'additionnaient, mesuré le 12/11)


def ramp_gain(t):
    """Gain de l'alarme après t secondes : linéaire en dB (ressenti régulier), plafonné. Pur : testable."""
    db = RAMP_FROM_DB + (RAMP_TO_DB - RAMP_FROM_DB) * min(max(t, 0.0) / RAMP_S, 1.0)
    return 10 ** (db / 20)


def _load(path):
    with wave.open(path, "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data


class Mixer:
    """Mélange des voix (tableaux float32) ; l'alarme est une voix en boucle avec gain progressif.
    Indépendant de la carte son : fill() remplit un bloc, appelé par le flux (ou par les tests)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.voices = []          # [tableau, position, fondu restant ou None]
        self.volume = 1.0         # volume général (sons et alarme)
        self.alarm = None         # tableau de l'alarme en cours, ou None
        self.alarm_pos = 0
        self.alarm_t = 0          # échantillons joués depuis le début de l'alarme
        self.alarm_fade = None    # échantillons restants du fondu d'arrêt

    def add(self, data):
        """Un seul son d'interface à la fois : ceux en cours s'effacent en 20 ms (l'alarme n'est pas touchée)."""
        with self.lock:
            for v in self.voices:
                if v[2] is None:
                    v[2] = int(CUT_FADE_S * RATE)
            self.voices.append([data, 0, None])

    def start_alarm(self, data):
        with self.lock:
            if self.alarm is not None and self.alarm_fade is None:
                return            # déjà en train de sonner : on ne repart pas de zéro
            self.alarm, self.alarm_pos, self.alarm_t, self.alarm_fade = data, 0, 0, None

    def stop_alarm(self):
        with self.lock:
            if self.alarm is not None and self.alarm_fade is None:
                self.alarm_fade = int(STOP_FADE_S * RATE)

    @property
    def ringing(self):
        return self.alarm is not None

    def fill(self, n):
        out = np.zeros(n, dtype=np.float32)
        with self.lock:
            keep = []
            for v in self.voices:
                data, pos, fade = v
                chunk = data[pos:pos + n]
                if fade is not None:
                    total = int(CUT_FADE_S * RATE)
                    ramp = np.clip((fade - np.arange(len(chunk))) / total, 0, 1).astype(np.float32)
                    chunk = chunk * ramp
                    v[2] = fade - n
                out[:len(chunk)] += chunk
                v[1] = pos + n
                if v[1] < len(data) and (v[2] is None or v[2] > 0):
                    keep.append(v)
            self.voices = keep
            if self.alarm is not None:
                data = self.alarm
                idx = (self.alarm_pos + np.arange(n)) % len(data)
                t = (self.alarm_t + np.arange(n)) / RATE
                gain = 10 ** ((RAMP_FROM_DB + (RAMP_TO_DB - RAMP_FROM_DB) * np.minimum(t / RAMP_S, 1.0)) / 20)
                block = data[idx] * gain.astype(np.float32)
                if self.alarm_fade is not None:
                    left = self.alarm_fade
                    fade = np.clip((left - np.arange(n)) / max(int(STOP_FADE_S * RATE), 1), 0, 1).astype(np.float32)
                    block *= fade
                    self.alarm_fade = left - n
                    if self.alarm_fade <= 0:
                        self.alarm = None
                out += block
                self.alarm_pos = (self.alarm_pos + n) % len(data)
                self.alarm_t += n
            out *= self.volume
        np.clip(out, -1.0, 1.0, out=out)
        return out


class Sounds:
    """play(nom) ne bloque jamais et ne lève jamais d'exception."""

    def __init__(self, folder, enabled=True, stream_factory=None, volume=0.5):
        self.enabled = enabled
        self.data = {}
        self.mixer = Mixer()
        self.mixer.volume = max(0.0, min(1.0, volume))
        self.stream = None
        self._factory = stream_factory
        self._failed = False
        if not enabled:
            return
        for name, base in FILES.items():
            path = os.path.join(folder, base + ".wav")
            try:
                self.data[name] = _load(path)
            except (OSError, wave.Error, EOFError):
                log.warning("son absent ou illisible : %s", path)

    def _ensure_stream(self):
        if self.stream is not None or self._failed:
            return self.stream is not None
        try:
            if self._factory is not None:
                self.stream = self._factory(self.mixer)
            else:
                import sounddevice as sd

                def callback(outdata, frames, time_info, status):
                    outdata[:, 0] = self.mixer.fill(frames)

                self.stream = sd.OutputStream(samplerate=RATE, channels=1, dtype="float32", callback=callback)
                self.stream.start()
            return True
        except Exception:
            log.exception("sortie son indisponible : Iris continue sans son")
            self._failed = True
            self.stream = None
            return False

    def play(self, name):
        if not self.enabled:
            return
        name = ALIASES.get(name, name)
        data = self.data.get(name)
        if data is None or not self._ensure_stream():
            return
        if name == "ALARME":
            self.mixer.start_alarm(data)       # boucle, volume qui monte ; rejouer ne la relance pas
        else:
            self.mixer.add(data)

    def stop_alarm(self):
        self.mixer.stop_alarm()

    @property
    def ringing(self):
        return self.mixer.ringing

    def close(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None


FAILURE_MARKS = ("RIEN ENTENDU", "PAS COMPRIS", "IMPOSSIBLE", "PAS DEVANT", "ABSENT", "OCCUPE",
                 "SEULEMENT EN MODE", "INCOMPRISE", "INTROUVABLE", "INCONNU", "ECHEC")


def is_failure(label):
    """Le texte de l'île signale-t-il un échec (son « pas compris ») ? Pur : testable."""
    if not label:
        return False
    up = label.upper()
    return any(m in up for m in FAILURE_MARKS)
