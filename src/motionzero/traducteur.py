"""« iris traducteur » (#14) : le son qui sort du PC, traduit en anglais par Whisper, en sous-titres en bas
de l'écran. « iris traducteur » une deuxième fois l'arrête.

Réutilise le Whisper de la voix (pas de deuxième modèle) : pendant une commande dictée, les sous-titres
attendent leur tour. Langue détectée seule ; Whisper ne traduit que vers l'anglais (suffisant).
Précision avant délai : le son est coupé aux silences, en phrases de 2 à 15 s (environ 3-5 s de retard)."""
import logging
import queue
import threading
import time

import numpy as np

log = logging.getLogger("motionzero.traducteur")

SR = 16000
FRAME_S = 0.03            # analyse du niveau par tranches de 30 ms
SPEECH_RMS = 0.004        # au-dessus : quelqu'un parle (ou de la musique : Whisper trie ensuite)
END_SILENCE_S = 0.7       # blanc qui termine une phrase
MIN_SPEECH_S = 1.0        # plus court : un bruit, pas envoyé à Whisper
MAX_CHUNK_S = 15.0        # phrase sans blanc (musique, débit rapide) : coupée quand même
SHOW_S = 7.0              # une ligne de sous-titres reste ce temps
MAX_LINES = 2
MAX_PENDING = 3           # Whisper en retard : les plus vieilles phrases sont jetées (on suit le direct)


def to_mono_16k(data, rate, channels):
    """int16 entrelacé -> float32 mono 16 kHz. Pur : testable."""
    pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm[: len(pcm) - len(pcm) % channels].reshape(-1, channels).mean(axis=1)
    if rate == SR or len(pcm) == 0:
        return pcm
    n = int(round(len(pcm) * SR / rate))
    return np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm).astype(np.float32)


class Decoupeur:
    """Coupe un flux 16 kHz en phrases aux silences. feed() rend les phrases terminées."""

    def __init__(self):
        self.frame = int(SR * FRAME_S)
        self.rest = np.zeros(0, np.float32)
        self.buf = []          # tranches de la phrase en cours
        self.speech = 0        # tranches parlées dans la phrase
        self.silence = 0       # tranches muettes depuis la dernière parole

    def feed(self, pcm):
        out = []
        pcm = np.concatenate([self.rest, pcm])
        n = len(pcm) // self.frame
        self.rest = pcm[n * self.frame:]
        for i in range(n):
            f = pcm[i * self.frame:(i + 1) * self.frame]
            loud = float(np.sqrt(np.mean(f * f))) > SPEECH_RMS
            if not self.buf and not loud:
                continue                       # blanc avant la phrase : rien à garder
            self.buf.append(f)
            if loud:
                self.speech += 1
                self.silence = 0
            else:
                self.silence += 1
            if self.silence * FRAME_S >= END_SILENCE_S or len(self.buf) * FRAME_S >= MAX_CHUNK_S:
                chunk = self._take()
                if chunk is not None:
                    out.append(chunk)
        return out

    def _take(self):
        enough = self.speech * FRAME_S >= MIN_SPEECH_S
        chunk = np.concatenate(self.buf) if enough else None
        self.buf, self.speech, self.silence = [], 0, 0
        return chunk


def open_loopback():
    """Flux WASAPI loopback de la sortie son par défaut : (lire(), fermer(), rate, canaux)."""
    import pyaudiowpatch as pa
    p = pa.PyAudio()
    try:
        dev = p.get_default_wasapi_loopback()
        rate, ch = int(dev["defaultSampleRate"]), int(dev["maxInputChannels"])
        block = int(rate * 0.1)
        stream = p.open(format=pa.paInt16, channels=ch, rate=rate, input=True,
                        input_device_index=dev["index"], frames_per_buffer=block)
    except Exception:
        p.terminate()
        raise

    def close():
        try:
            stream.stop_stream()
            stream.close()
        finally:
            p.terminate()
    return (lambda: stream.read(block, exception_on_overflow=False)), close, rate, ch


class Traducteur:
    """translate(pcm float32 16 kHz) -> texte anglais. Tout tourne dans deux fils à lui ; Core n'est jamais touché."""

    def __init__(self, translate, opener=open_loopback):
        self.translate, self.opener = translate, opener
        self.lock = threading.Lock()
        self.lines = []        # [(texte, instant)]
        self.error = None
        self.on = False
        self._stop = threading.Event()
        self._threads = []

    def start(self):
        if self.on:
            return
        self.on, self.error, self.lines = True, None, []
        self._stop = threading.Event()
        jobs = queue.Queue()
        self._threads = [threading.Thread(target=self._capture, args=(self._stop, jobs), name="trad-son", daemon=True),
                         threading.Thread(target=self._work, args=(self._stop, jobs), name="trad-whisper", daemon=True)]
        for th in self._threads:
            th.start()
        log.info("traducteur allume")

    def stop(self):
        if not self.on:
            return
        self.on = False
        self._stop.set()
        with self.lock:
            self.lines = []
        log.info("traducteur eteint")

    def _fail(self, msg):
        with self.lock:
            self.error = msg

    def _capture(self, stop, jobs):
        try:
            read, close, rate, ch = self.opener()
        except Exception:
            log.exception("son du PC impossible a capter")
            self._fail("Son du PC impossible à capter")
            return
        cut = Decoupeur()
        try:
            while not stop.is_set():
                for chunk in cut.feed(to_mono_16k(read(), rate, ch)):
                    if jobs.qsize() >= MAX_PENDING:
                        try:
                            jobs.get_nowait()
                        except queue.Empty:
                            pass
                    jobs.put(chunk)
        except Exception:
            log.exception("capture du son interrompue")
            self._fail("Capture du son interrompue")
        finally:
            try:
                close()
            except Exception:
                log.exception("fermeture du flux son")
            jobs.put(None)

    def _work(self, stop, jobs):
        while True:
            chunk = jobs.get()
            if chunk is None or stop.is_set():
                return
            try:
                text = self.translate(chunk).strip()
            except Exception:
                log.exception("traduction echouee")
                continue                       # une phrase perdue, pas le traducteur
            if text and not stop.is_set():
                with self.lock:
                    self.lines = (self.lines + [(text, time.perf_counter())])[-MAX_LINES:]

    def snapshot(self):
        """Pour l'overlay : None (éteint) ou {"lines": [...], "error": str|None}."""
        if not self.on:
            return None
        now = time.perf_counter()
        with self.lock:
            self.lines = [(s, t) for s, t in self.lines if now - t < SHOW_S]
            return {"lines": [s for s, _ in self.lines], "error": self.error}
