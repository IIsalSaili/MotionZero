"""Commandes vocales hors ligne (Vosk, petit modèle français, grammaire fermée).

- Seuls les mots de WORDS sont reconnus ; tout le reste devient « [unk] » et est ignoré.
- En veille par défaut : seul le mot de réveil « iris » (ou un geste) ouvre l'écoute quelques secondes.
- Les événements sont horodatés (time.perf_counter) pour être fusionnés avec la position de la main.
"""
import json
import logging
import queue
import threading
import time
from collections import deque
from .voice_base import (AFTER_IRIS_S, ALWAYS_HEARD, BYPASS_EXCLUDED, BYPASS_LONE_CONF, BYPASS_MIN_CONF, CAL_ONLY, END_SILENCE_S, FREE_MAX_WORDS, FREE_PREROLL_S, FREE_TAIL_S, FREE_WAKE_RATIO, GRAMMAR, GRAMMARS, IRIS_GAP_S, IRIS_MIN_CONF, IRIS_SURE_CONF, LONE_MIN_CONF, MAX_CAPTURE_S, MODE_SPLIT, MOUSE_ONLY, QUIET_CHOICES, QUIET_FROM_H, QUIET_IRIS_CONF, QUIET_TO_H, QUIET_WAKE_RATIO, SHORT_PHRASE, SOLO_TOO, SPLIT, SPOKEN, STALL_RETRY_S, STALL_S, VIA_INSTRUCTION, VoiceEvent, WAKE_WORD, WORDS, _calendar_words, _dedupe, _gap, _grammars, _join_demute, _rms, accepted_words, apercu, bypassable, cand_grammar, confirmed, default_model_dir, grammar, quiet_active, rejection)  # noqa: F401

log = logging.getLogger("motionzero.voice")


class VoiceListener:
    """Thread micro + reconnaissance. Les mots reconnus arrivent dans self.events (queue)."""

    def __init__(self, model_dir, min_conf=0.6, samplerate=16000):
        self.model_dir = model_dir
        self.min_conf = min_conf
        self.sr = samplerate
        self.events = queue.Queue()
        self.audio = queue.Queue(maxsize=200)
        self.running = False
        self.muted = False
        # « tu parles / tu te tais » au volume du micro (sert à couper la dictée Claude au bon moment)
        self.ambient = 200.0        # niveau du bruit de fond (RMS int16), appris pendant les moments calmes
        self._loud = 0.0
        self.thread = None
        self.stream = None
        self.t_stream0 = None
        self.last_speech_t = time.perf_counter()
        self.last_rms = 0.0         # pour le journal pendant la dictée
        self._partial = ""          # dernier texte provisoire de la reconnaissance
        self.last_rejected = None   # (texte affiché, instant) : commande entendue mais bloquée (pour l'île)
        self.capture = None         # morceaux de son gardés pendant « iris question »
        self.quiet = False          # voix basse : écrit par la boucle principale (un booléen), lu ici
        self.conversation = True    # bouton « mode conversation » de l'accueil : décoché, pas de 2e vérification
        self.bypass = False         # « iris bypass » : écrit par la boucle principale (un booléen), lu ici
        self.relaxed = frozenset()  # mots attendus maintenant (« envoie / annule » après une dictée) : idem
        self._iris_ok_t = -1e9      # dernier « iris » accepté (le mot qui suit n'est pas re-vérifié)
        self.iris_heard_t = -1e9    # dernier « iris » repéré dans le texte PROVISOIRE (fige le curseur tôt)
        self.last_block_t = -1e9    # dernier morceau de son reçu du micro (même silencieux)
        self._stall_try_t = -1e9    # dernière réouverture automatique (micro figé)
        # liste de mots voulue (« base » / « chrome ») : écrite par la boucle, appliquée par le fil voix
        self.grammar = "base"
        self._grammar = "base"

    def start(self):
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        self.model = Model(self.model_dir)
        self.rec = KaldiRecognizer(self.model, self.sr, GRAMMAR)
        self.rec.SetWords(True)
        self.free = KaldiRecognizer(self.model, self.sr)   # sans grammaire : sert à vérifier (voir confirmed)
        self._free_final = (0.0, "")
        self._free_pre = deque(maxlen=int(FREE_PREROLL_S / 0.03))
        self._free_until = 0.0
        self._was_muted = False
        self.running = True
        self.t_stream0 = time.perf_counter()
        self.samples = 0
        # mode partagé (par défaut) : les autres applis peuvent utiliser le micro en même temps
        self.stream = sd.RawInputStream(samplerate=self.sr, blocksize=int(self.sr * 0.03), dtype="int16",
                                        channels=1, callback=self._callback)
        self.stream.start()
        self.thread = threading.Thread(target=self._run, name="voice", daemon=True)
        self.thread.start()
        log.info("ecoute vocale demarree")
        return self

    def _callback(self, indata, frames, time_info, status):
        self.last_block_t = time.perf_counter()
        try:
            self.audio.put_nowait(bytes(indata))
        except queue.Full:
            pass  # on préfère perdre un bloc que bloquer l'audio

    def _run(self):
        # une erreur sur un morceau de son ne doit jamais arrêter l'écoute (mesuré : une phrase vide
        # faisait planter le fil, et plus aucune commande vocale n'était entendue)
        while self.running:
            try:
                self._step()
            except Exception:
                log.exception("erreur dans l'ecoute vocale (on continue)")

    def _step(self):
        """Traite un morceau de son (30 ms)."""
        try:
            block = self.audio.get(timeout=0.2)
        except queue.Empty:
            self.check_stalled()
            return
        start_samples = self.samples
        self.samples += len(block) // 2
        capture = self.capture   # lu une seule fois : stop_capture (autre fil) peut le remettre à None
        if capture is not None and len(capture) < MAX_CAPTURE_S / 0.03:
            capture.append(block)
        rms = _rms(block)
        self.last_rms = rms
        if rms < self.ambient * 1.5:  # seulement les moments calmes : la voix ne fausse pas le bruit de fond
            self.ambient = 0.98 * self.ambient + 0.02 * rms
        if rms >= min(max(self.ambient * 3.0, 400.0), 1500.0):
            self._loud += len(block) / 2 / self.sr
            if self._loud >= 0.15:  # un bruit bref ne compte pas comme de la parole
                self.last_speech_t = time.perf_counter()
        else:
            self._loud = 0.0
        if self.muted:
            if not self._was_muted:          # une seule remise à zéro, pas une à chaque morceau
                self.rec.Reset()
                self.free.Reset()
                self._free_pre.clear()
                self._was_muted = True
            return
        self._was_muted = False
        want = self.grammar
        if want != self._grammar and want in GRAMMARS:
            self.rec.Reset()                      # Vosk refuse de changer la liste en pleine phrase
            self.rec.SetGrammar(GRAMMARS[want])   # entre deux morceaux de son, dans ce fil uniquement
            self._grammar = want
            log.info("liste de mots : %s", want)
        now = time.perf_counter()
        # Reconnaissance libre (la plus chère) : seulement quand quelqu'un parle. Le reste du temps, le
        # son est gardé ~1 s et lui est redonné au réveil, pour ne pas perdre le début de la phrase.
        if rms >= self.ambient * (QUIET_WAKE_RATIO if self.quiet else FREE_WAKE_RATIO) or self._partial:
            self._free_until = now + FREE_TAIL_S
        if now < self._free_until:
            for old in self._free_pre:
                self.free.AcceptWaveform(old)
            self._free_pre.clear()
            if self.free.AcceptWaveform(block):
                self._free_final = (now, json.loads(self.free.Result()).get("text", ""))
        else:
            self._free_pre.append(block)
        if self.rec.AcceptWaveform(block):
            self._partial = ""
            t_free, text = self._free_final
            if now - t_free > 1.5:   # la reconnaissance libre n'a pas encore fini sa phrase
                text = json.loads(self.free.PartialResult()).get("partial", "")
            self._emit(json.loads(self.rec.Result()), text)
        else:
            # la reconnaissance entend un mot de plus (même inconnu) : c'est de la parole, quel que
            # soit le volume du micro (mesuré : VS Code le fait chuter à ~0-300 pendant sa dictée).
            # Seul un texte qui CHANGE compte : le dernier mot reste affiché un moment après la parole.
            partial = json.loads(self.rec.PartialResult()).get("partial", "").strip()
            if partial and partial != self._partial:
                self.last_speech_t = time.perf_counter()
                if WAKE_WORD in partial.split():
                    self.iris_heard_t = time.perf_counter()
            self._partial = partial

    def _emit(self, res, free_text=None):
        why = rejection(res, self.min_conf)
        if why:
            log.info("iris rejete : %s", why)
        relaxed = getattr(self, "relaxed", frozenset())   # (écouteurs de test créés sans __init__)
        bypass = getattr(self, "bypass", False)
        words = accepted_words(res, self.min_conf, relaxed=relaxed, bypass=bypass)
        if not words:
            return
        after_iris = time.perf_counter() - self._iris_ok_t < AFTER_IRIS_S
        if free_text is not None and getattr(self, "conversation", True) and not confirmed(words, free_text, len(res.get("result", [])), after_iris,
                                                   self.quiet, relaxed, bypass):
            said = " ".join(w["word"] for w in words)
            log.info("non confirme : %s (entendu librement : %s)", said, apercu(free_text))
            self.last_rejected = (f"« {said} » ignoré : pas sûr de l'avoir entendu", time.perf_counter())
            return
        # Dates sur l'horloge de l'appli, pas sur celle du flux audio : celle-ci dérive avec le temps et
        # repart de zéro quand l'écoute est mise en sourdine (dictée Claude). Mesuré : le clic vocal
        # ramenait alors le curseur à une position vieille de plusieurs secondes.
        # La phrase vient de finir (Vosk rend le résultat après un court silence) : on recale sur « maintenant ».
        now = time.perf_counter() - END_SILENCE_S
        last_end = max(w["end"] for w in words)
        # mesure de la lenteur (14/11) : attente du silence par Vosk, et son en retard dans la file
        stream_t = getattr(self, "samples", 0) / self.sr if getattr(self, "sr", 0) else 0.0
        audio = getattr(self, "audio", None)
        log.info("delai : fin du mot -> resultat %.2f s, file %.2f s",
                 max(0.0, stream_t - last_end), (audio.qsize() * 0.03) if audio is not None else 0.0)
        for w in words:
            ev = VoiceEvent(w["word"], w["conf"], now - (last_end - w["start"]), now - (last_end - w["end"]))
            if w["word"] == WAKE_WORD:
                self._iris_ok_t = time.perf_counter()
            self.events.put(ev)   # noté au journal par la boucle (avec « acceptée / ignorée »)

    def reopen(self):
        """Rouvre le micro (après « réparer le son ») : l'ancien flux est abandonné sans l'attendre (il peut
        être figé), PortAudio relit la liste des micros, puis un nouveau flux s'ouvre sur le micro par défaut."""
        import sounddevice as sd
        old, self.stream = self.stream, None
        if old is not None:
            def close():
                try:
                    old.abort()
                    old.close()
                except Exception:
                    pass
            t = threading.Thread(target=close, name="ferme-micro", daemon=True)
            t.start()
            t.join(3.0)
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            log.exception("reinitialisation de l'audio")
        finally:
            after = getattr(self, "after_reopen", None)
            if after is not None:
                after()                   # la sortie des sons d'Iris est morte avec PortAudio : à rouvrir
        self.stream = sd.RawInputStream(samplerate=self.sr, blocksize=int(self.sr * 0.03), dtype="int16",
                                        channels=1, callback=self._callback)
        self.stream.start()
        log.info("micro rouvert : %s", sd.query_devices(kind="input")["name"])

    def check_stalled(self, now=None):
        """Micro figé (14/11 : plus aucun son reçu, Iris sourde jusqu'à sa relance) : rouvre le flux tout seul.
        Un casque muté par son bouton envoie encore du silence : ça ne compte pas comme figé."""
        if self.stream is None or self.t_stream0 is None:
            return False
        now = time.perf_counter() if now is None else now
        last = max(self.last_block_t, self.t_stream0)
        if now - last < STALL_S or now - self._stall_try_t < STALL_RETRY_S:
            return False
        self._stall_try_t = now
        log.warning("micro fige (aucun son depuis %.1f s) : flux rouvert", now - last)
        try:
            self.reopen()
        except Exception:
            log.exception("reouverture du micro fige")
        return True

    def heard_since(self, t):
        return self.last_block_t > t

    def start_capture(self):
        self.capture = []

    def stop_capture(self):
        """Son enregistré depuis start_capture (int16, 16 kHz, mono) ; ou le texte d'un MP Discord (#43),
        déposé dans `typed` par la boucle principale : il remplace l'enregistrement, Whisper est sauté."""
        typed, self.typed = getattr(self, "typed", None), None
        if typed is not None:
            self.capture = None
            return typed
        blocks, self.capture = self.capture or [], None
        return b"".join(blocks)

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    def stop(self):
        self.running = False
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
        if self.thread is not None:
            self.thread.join(timeout=2.0)
