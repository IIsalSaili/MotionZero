"""Lecture à voix haute (voix Windows SAPI, sur le processeur : la carte graphique n'est pas touchée).

Un fil « lecture » parle à partir d'une file bornée : la boucle principale n'attend jamais.
Voix absente ou en panne : rien n'est lu, le texte reste affiché dans l'île.
"""
import logging
import queue
import threading

log = logging.getLogger("motionzero.speech")

ASYNC, PURGE = 1, 2           # SpeechVoiceSpeakFlags
MAX_CHARS = 400               # au-delà, la lecture est coupée (« … la suite à l'écran »)


class Speaker:
    def __init__(self, rate=1, backlog=5, factory=None):
        self.rate = rate
        self._q = queue.Queue(maxsize=backlog)
        self._factory = factory or _sapi_voice
        self.enabled = True
        self.ok = True
        self._hush = threading.Event()
        threading.Thread(target=self._run, name="lecture", daemon=True).start()

    def say(self, text):
        if not self.enabled or not self.ok or not text:
            return False
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS].rsplit(" ", 1)[0] + ", la suite à l'écran"
        try:
            self._q.put_nowait(("say", text))
        except queue.Full:            # trop de messages d'un coup : on garde les premiers
            return False
        return True

    def hush(self):
        """Coupe la phrase en cours et oublie celles en attente."""
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self._hush.set()

    def _run(self):
        try:
            voice = self._factory(self.rate)
        except Exception:
            log.exception("voix Windows indisponible : pas de lecture a voix haute")
            self.ok = False
            return
        while True:
            kind, text = self._q.get()
            self._hush.clear()
            try:
                voice.Speak(text, ASYNC)
                while not voice.WaitUntilDone(100):     # une phrase après l'autre, interruptible
                    if self._hush.is_set():
                        voice.Speak("", ASYNC | PURGE)
                        break
            except Exception:
                log.exception("lecture a voix haute")


def _sapi_voice(rate):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    for v in voice.GetVoices():
        d = v.GetDescription().lower()
        if "french" in d or "fran" in d:
            voice.Voice = v
            break
    voice.Rate = rate
    return voice
